"""Difficulty: non_linear_state_machine — revision loop, dispute loop, parallel dimensions."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    accept_application,
    api_client,
    confirm_assignment,
    create_settlement,
    decide_application,
    get_application,
    issue_fine,
    make_vendor_headers,
    provision_assignment,
    reconcile_settlement,
    report_sale,
    request_changes,
    respond_fine,
    setup_active_assignment,
    setup_reserved_assignment,
    setup_submitted_application,
    start_review,
    submit_application,
    validate_error,
    validate_success,
)

VM = TEST_USERS["vendor_manager_headers"]
OPS = TEST_USERS["ops_headers"]
FIN1 = TEST_USERS["finance_headers"]


class TestApplicationRevisionAndWaitlistLoops:
    def test_revision_cycle_supersedes_and_increments_round(self, api):
        """PRD §3.2: "The vendor answers by resubmitting: a new application whose
        `supersedes_application_id` points at the `CHANGES_REQUESTED` one."
        PRD §3.2: "The supersede is valid only when the source is in
        `CHANGES_REQUESTED` and belongs to the same vendor and the same festival,
        otherwise `ERR_SUPERSEDE_SOURCE_INVALID`; on success the source moves to
        `SUPERSEDED` and the new application enters `SUBMITTED` with
        `review_round` set to the source's round plus one."

        Design: Difficulty/non_linear_state_machine/application_revision_cycle_and_waitlist_reentry
        """
        scen = setup_submitted_application(name="Cycle Fest", proposed_flat_fee_cents=70000)
        app1 = scen["app"]
        assert app1["review_round"] == 0, "fresh application"
        start_review(app1["id"])
        request_changes(app1["id"], notes="fix menu")

        resp = api.create_application(
            {"vendor_id": scen["vendor"]["id"], "festival_id": scen["festival"]["id"],
             "category": "FOOD_HOT", "fee_model": "FLAT_FEE", "proposed_flat_fee_cents": 75000,
             "power_needed_amps": 20, "requires_water": False,
             "supersedes_application_id": app1["id"]},
            make_vendor_headers(scen["vendor"]["id"]),
        )
        app2 = validate_success(resp, expected_status=201)
        assert app2["status"] == "SUBMITTED"
        assert app2["review_round"] == 1, "supersede chain inherits source round + 1"
        assert get_application(app1["id"])["status"] == "SUPERSEDED", "revision loop closed"

    def test_waitlist_reentry_returns_to_under_review(self, api):
        """PRD §3.2: "A `VendorManager` begins evaluation by starting review,
        moving the application from `SUBMITTED` — or from `WAITLISTED`, for
        example after an automatic promotion — to `UNDER_REVIEW`."

        Design: Difficulty/non_linear_state_machine/application_revision_cycle_and_waitlist_reentry
        """
        scen = setup_submitted_application(name="Cycle Fest", proposed_flat_fee_cents=70000)
        app1 = scen["app"]
        start_review(app1["id"])
        request_changes(app1["id"], notes="fix menu")
        resp = api.create_application(
            {"vendor_id": scen["vendor"]["id"], "festival_id": scen["festival"]["id"],
             "category": "FOOD_HOT", "fee_model": "FLAT_FEE", "proposed_flat_fee_cents": 75000,
             "power_needed_amps": 20, "requires_water": False,
             "supersedes_application_id": app1["id"]},
            make_vendor_headers(scen["vendor"]["id"]),
        )
        app2 = validate_success(resp, expected_status=201)

        start_review(app2["id"])
        waitlisted = decide_application(app2["id"], "WAITLISTED")
        assert waitlisted["status"] == "WAITLISTED"
        reentered = start_review(app2["id"])
        assert reentered["status"] == "UNDER_REVIEW", "waitlist re-entry loop"
        accepted = accept_application(app2["id"], "FLAT_FEE", flat_fee_cents=75000)
        assert accepted["status"] == "ACCEPTED"
        assert accepted["curated_flat_fee_cents"] == 75000


def _setup_dispute_loop():
    """LIVE festival; ACTIVE REVENUE_SHARE 1000bp MARGINAL assignment; two
    100000-cent REPORTED sales; settlement reconciled (provisional gross 200000)."""
    scen = setup_active_assignment(
        name="Loop Fest", fee_model="REVENUE_SHARE",
        terms={"revenue_share_pct_bp": 1000, "tier_mode": "MARGINAL"},
    )
    asg_id = scen["assignment"]["id"]
    report_sale(asg_id, scen["vendor"], 100000, "lp1")
    report_sale(asg_id, scen["vendor"], 100000, "lp2", occurred_at="2026-07-10T15:00:00Z")
    stl = create_settlement(asg_id)
    scen["settlement"] = reconcile_settlement(stl["id"])
    return scen


class TestSettlementDisputeCycle:
    def test_reconcile_after_dispute_recomputes_current_reported_set(self, api):
        """PRD §3.6: "a re-reconcile from `DISPUTED` recomputes over the current
        `REPORTED` set so that voids and late reports since the last reconcile
        are reflected."
        PRD §3.6: "A vendor who disagrees with a reconciliation disputes it,
        moving the settlement from `RECONCILING` to `DISPUTED`".

        Design: Difficulty/non_linear_state_machine/settlement_dispute_reconciliation_cycle
        """
        scen = _setup_dispute_loop()
        stl = scen["settlement"]
        assert stl["provisional_gross_cents"] == 200000, "before the loop"

        disputed = validate_success(
            api.dispute_settlement(stl["id"], {"reason": "missing sales"},
                                   make_vendor_headers(scen["vendor"]["id"]))
        )
        assert disputed["status"] == "DISPUTED"

        report_sale(scen["assignment"]["id"], scen["vendor"], 40000, "lp3",
                    occurred_at="2026-07-11T10:00:00Z")
        rec = reconcile_settlement(stl["id"], headers=TEST_USERS["finance2_headers"])
        assert rec["status"] == "RECONCILING", "cycle back"
        assert rec["provisional_gross_cents"] == 240000, "late report reflected"
        assert rec["provisional_share_cents"] == 24000
        assert rec["provisional_payout_cents"] == 216000

    def test_dispute_cycle_is_repeatable_not_one_shot(self, api):
        """PRD §3.6: "Reconciliation moves a settlement from `OPEN` — or, after a
        dispute, from `DISPUTED` — to `RECONCILING`".
        PRD §3.6: "The loop back to `RECONCILING` is another reconcile."

        Design: Difficulty/non_linear_state_machine/settlement_dispute_reconciliation_cycle
        """
        scen = _setup_dispute_loop()
        stl = scen["settlement"]
        d1 = validate_success(
            api.dispute_settlement(stl["id"], {"reason": "missing sales"},
                                   make_vendor_headers(scen["vendor"]["id"]))
        )
        assert d1["status"] == "DISPUTED"
        rec = reconcile_settlement(stl["id"], headers=TEST_USERS["finance2_headers"])
        assert rec["status"] == "RECONCILING"
        d2 = validate_success(
            api.dispute_settlement(stl["id"], {"reason": "still wrong"},
                                   make_vendor_headers(scen["vendor"]["id"]))
        )
        assert d2["status"] == "DISPUTED", "the loop is repeatable"
        again = reconcile_settlement(stl["id"])
        assert again["status"] == "RECONCILING"


class TestAssignmentParallelDimensions:
    def test_confirm_and_provision_move_independent_axes(self, api):
        """PRD §3.3: "The assignment's `status` (its lifecycle) and its
        `utility_status` (`PENDING` or `PROVISIONED`) are parallel dimensions
        that evolve independently; only activation couples them."

        Design: Difficulty/non_linear_state_machine/assignment_parallel_status_and_utility_dimensions
        """
        scen = setup_reserved_assignment(name="Parallel Fest")
        asg = scen["assignment"]
        assert asg["status"] == "RESERVED" and asg["utility_status"] == "PENDING"

        confirmed = confirm_assignment(asg["id"])
        assert confirmed["status"] == "CONFIRMED", "confirm moves only the status axis"
        assert confirmed["utility_status"] == "PENDING"
        assert confirmed["flat_fee_cents"] == 50000, "fee snapshot pinned at confirm"

        provisioned = provision_assignment(asg["id"])
        assert provisioned["status"] == "CONFIRMED", "provision moves only the utility axis"
        assert provisioned["utility_status"] == "PROVISIONED"

    def test_reprovision_rejected_on_utility_axis(self, api):
        """PRD §3.3: "Utility provisioning moves `utility_status` from `PENDING`
        to `PROVISIONED` and is permitted only while `status` is `CONFIRMED` —
        otherwise `ERR_INVALID_STATE_TRANSITION`."

        Design: Difficulty/non_linear_state_machine/assignment_parallel_status_and_utility_dimensions
        """
        scen = setup_reserved_assignment(name="Parallel Fest")
        asg_id = scen["assignment"]["id"]
        confirm_assignment(asg_id)
        provision_assignment(asg_id)
        resp = api.provision_utilities(asg_id, OPS)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
