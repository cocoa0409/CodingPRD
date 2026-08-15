"""Damage reporting, competitive bidding negotiation, and repair conversion."""
from test_helpers import ApiErrorId, validate_error, validate_success
from test_helpers.fixtures import (
    assign_work_order,
    complete_work_order,
    create_bid,
    create_crew,
    setup_bid_requested_report,
    start_work_order,
    submit_bid,
    submit_work_order,
    upload_minimum_photos,
)
from test_helpers.test_users import TEST_USERS, make_field_crew_headers, make_servicer_headers

ADMIN = TEST_USERS["vendor_admin_headers"]
QA = TEST_USERS["quality_reviewer_headers"]


def _two_crew_bid_scenario(api):
    """BID_REQUESTED report with crew1's bid SUBMITTED and crew2's bid SUBMITTED;
    crew1's bid COUNTERED at 65000. Returns (ctx, crew2, b1, b2)."""
    ctx = setup_bid_requested_report()
    crew2 = create_crew()
    cr1 = ctx["crew_id"]
    dr_v = ctx["damage_report_version"]
    b1 = create_bid(ctx["damage_report_id"], cr1, 80000, dr_v)
    submit_bid(b1["id"], cr1)
    b2 = create_bid(ctx["damage_report_id"], crew2["id"], 90000, dr_v + 1)
    submit_bid(b2["id"], crew2["id"])
    validate_success(api.counter_bid(b1["id"], {"counter_amount_cents": 65000},
                                     make_servicer_headers(ctx["servicer_id"])))
    return ctx, crew2, b1, b2


class TestBidNegotiationCycle:
    def test_bid_revise_increments_round(self, api):
        """PRD: "The crew answers a counter by revising — `COUNTERED → SUBMITTED` —
        with a fresh `amount_cents`; ownership is checked again (`ERR_NOT_BID_OWNER`),
        and the `round_number` increments with each revision, so the negotiation loop
        from `SUBMITTED` to `COUNTERED` and back is cyclic."

        Design: Difficulty/non_linear_state_machine/bid_negotiation_rounds_cycle
        """
        ctx, _crew2, b1, _b2 = _two_crew_bid_scenario(api)
        revised = validate_success(api.revise_bid(b1["id"], {"amount_cents": 70000},
                                                  make_field_crew_headers(ctx["crew_id"])))
        assert revised["status"] == "SUBMITTED", f"revision returns to SUBMITTED, got {revised['status']}"
        assert revised["round_number"] == 2, f"round incremented to 2, got {revised['round_number']}"
        assert revised["amount_cents"] == 70000

    def test_bid_approval_spawns_negotiated_work_order(self, api):
        """PRD: "On approval — `SUBMITTED → APPROVED`, terminal — the system spawns
        a repair work order: `order_type` `DAMAGE_REPAIR`, `source` `BID_CONVERTED`,
        its `bid_id` set to this bid, `due_date` fourteen days out from the clock
        date, its allowable schedule pinned from the current `DAMAGE_REPAIR` row per
        §2.11 but with `allowable_cap_cents` equal to the bid's `amount_cents` — the
        negotiated cap. The bid's `approved_work_order_id` points at the spawned
        order, the damage report moves to `REPAIR_IN_PROGRESS`, and every other bid
        on the same report in `SUBMITTED` or `COUNTERED` is rejected."

        Design: Difficulty/non_linear_state_machine/bid_negotiation_rounds_cycle
        """
        ctx, crew2, b1, b2 = _two_crew_bid_scenario(api)
        validate_success(api.revise_bid(b1["id"], {"amount_cents": 70000},
                                        make_field_crew_headers(ctx["crew_id"])))
        approved = validate_success(api.approve_bid(b1["id"],
                                                    make_servicer_headers(ctx["servicer_id"])))
        assert approved["status"] == "APPROVED"
        spawned = validate_success(api.get_work_order(approved["approved_work_order_id"], ADMIN))
        assert spawned["source"] == "BID_CONVERTED"
        assert spawned["order_type"] == "DAMAGE_REPAIR"
        assert spawned["allowable_cap_cents"] == 70000, (
            f"negotiated cap from the revised amount, got {spawned['allowable_cap_cents']}")
        assert spawned["due_date"] == "2026-08-15", (
            f"due_date fourteen days out from clock 2026-08-01, got {spawned['due_date']}")
        loser = validate_success(api.get_bid(b2["id"], ADMIN))
        assert loser["status"] == "REJECTED", "competing open bid auto-rejected on approval"
        report = validate_success(api.get_damage_report(ctx["damage_report_id"], ADMIN))
        assert report["status"] == "REPAIR_IN_PROGRESS"


class TestBidGateAfterApproval:
    def _setup_draft_bid_after_approval(self, api):
        """bid1 (crew1) submitted and approved; bid2 (crew2) left DRAFT."""
        ctx = setup_bid_requested_report()
        crew2 = create_crew()
        dr_v = ctx["damage_report_version"]
        b1 = create_bid(ctx["damage_report_id"], ctx["crew_id"], 80000, dr_v)
        b2 = create_bid(ctx["damage_report_id"], crew2["id"], 75000, dr_v + 1)
        submit_bid(b1["id"], ctx["crew_id"])
        validate_success(api.approve_bid(b1["id"], make_servicer_headers(ctx["servicer_id"])))
        return ctx, crew2, b2

    def test_bid_submit_after_competing_approval_rejected(self, api):
        """PRD: "Only a report in `BID_REQUESTED` accepts bids at any point in the
        bidding workflow; attempts to create, submit, or approve a bid against a
        report in any other status are rejected with
        `ERR_DAMAGE_NOT_ACCEPTING_BIDS`."

        Design: Difficulty/cross_entity_state_dependency/bid_submit_blocked_after_competing_approval
        """
        ctx, crew2, b2 = self._setup_draft_bid_after_approval(api)
        resp = api.submit_bid(b2["id"], make_field_crew_headers(crew2["id"]))
        validate_error(resp, ApiErrorId.ERR_DAMAGE_NOT_ACCEPTING_BIDS)

    def test_bid_submit_after_competing_approval_stays_draft(self, api):
        """PRD: "Submitting a draft — `DRAFT → SUBMITTED`" never fires for the
        rejected attempt: the bid starts in `DRAFT` ("starts the bid in `DRAFT` with
        `round_number` 1") and remains there.

        Design: Difficulty/cross_entity_state_dependency/bid_submit_blocked_after_competing_approval
        """
        ctx, crew2, b2 = self._setup_draft_bid_after_approval(api)
        api.submit_bid(b2["id"], make_field_crew_headers(crew2["id"]))
        after = validate_success(api.get_bid(b2["id"], ADMIN))
        assert after["status"] == "DRAFT", f"rejected submit leaves the bid DRAFT, got {after['status']}"
        report = validate_success(api.get_damage_report(ctx["damage_report_id"], ADMIN))
        assert report["status"] == "REPAIR_IN_PROGRESS"


class TestBidOwnershipAndTerminal:
    def test_bid_withdraw_then_submit_returns_invalid_state(self, api):
        """PRD: "The owning crew may instead withdraw — from `DRAFT` or `SUBMITTED`
        to the terminal `WITHDRAWN` — with the same ownership check", so a later
        submit fails: "The target resource must be in a state that permits the
        requested transition; failures surface as `ERR_INVALID_STATE`".

        Design: Corner/state_machines/bid_withdraw_then_submit_returns_invalid_state
        """
        ctx = setup_bid_requested_report()
        b = create_bid(ctx["damage_report_id"], ctx["crew_id"], 40000,
                       ctx["damage_report_version"])
        validate_success(api.withdraw_bid(b["id"], make_field_crew_headers(ctx["crew_id"])))
        resp = api.submit_bid(b["id"], make_field_crew_headers(ctx["crew_id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_bid_submit_by_other_crew_rejected(self, api):
        """PRD: "Submitting a draft — `DRAFT → SUBMITTED` — is restricted to the
        owning crew: the caller's `X-User-ID` must equal the bid's
        `submitted_by_crew_id` (`ERR_NOT_BID_OWNER`)".

        Design: Corner/rbac/bid_submit_by_other_crew_rejected
        """
        ctx = setup_bid_requested_report(damage_overrides={"damage_type": "FIRE",
                                                           "is_interior": True,
                                                           "description": "scorched wall"})
        crew2 = create_crew()
        b = create_bid(ctx["damage_report_id"], ctx["crew_id"], 45000,
                       ctx["damage_report_version"])
        resp = api.submit_bid(b["id"], make_field_crew_headers(crew2["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_BID_OWNER)


class TestDamageClosureGates:
    def test_damage_close_with_open_bids_rejected(self, api):
        """PRD: "From `REPAIR_IN_PROGRESS`, closing with outcome `CLOSED` requires
        that no bid on the report stands in `DRAFT`, `SUBMITTED`, or `COUNTERED`
        (`ERR_OPEN_BIDS`)"; on approval "every other bid on the same report in
        `SUBMITTED` or `COUNTERED` is rejected" — a never-submitted DRAFT bid
        survives approval, so with the repair itself COMPLETED the open DRAFT bid
        is the only failing gate.

        Design: Corner/errors/damage_close_with_open_bids_rejected
        """
        ctx = setup_bid_requested_report()
        crew2 = create_crew()
        dr_v = ctx["damage_report_version"]
        # Lingering DRAFT bid (never submitted; survives the approval cascade).
        create_bid(ctx["damage_report_id"], crew2["id"], 30000, dr_v)
        winning = create_bid(ctx["damage_report_id"], ctx["crew_id"], 60000, dr_v + 1)
        submit_bid(winning["id"], ctx["crew_id"])
        approved = validate_success(api.approve_bid(winning["id"],
                                                    make_servicer_headers(ctx["servicer_id"])))
        wo_id = approved["approved_work_order_id"]
        assign_work_order(wo_id, ctx["crew_id"], scheduled_date="2026-08-02")
        start_work_order(wo_id, ctx["crew_id"])
        upload_minimum_photos(wo_id, "DAMAGE_REPAIR", ctx["crew_id"], hash_prefix="rep")
        submit_work_order(wo_id, ctx["crew_id"], 60000)
        validate_success(api.approve_work_order(wo_id, QA))
        complete_work_order(wo_id)
        resp = api.close_damage_report(ctx["damage_report_id"], {"outcome": "CLOSED"}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_OPEN_BIDS)

    def test_damage_close_before_repair_completed_rejected(self, api):
        """PRD: "From `REPAIR_IN_PROGRESS`, closing with outcome `CLOSED` requires
        that no bid on the report stands in `DRAFT`, `SUBMITTED`, or `COUNTERED`
        (`ERR_OPEN_BIDS`) and that the work order referenced by the approved bid
        stands `COMPLETED` (`ERR_REPAIR_NOT_COMPLETED`)".

        Design: Corner/errors/damage_close_before_repair_completed_rejected
        """
        ctx = setup_bid_requested_report()
        b = create_bid(ctx["damage_report_id"], ctx["crew_id"], 60000,
                       ctx["damage_report_version"])
        submit_bid(b["id"], ctx["crew_id"])
        validate_success(api.approve_bid(b["id"], make_servicer_headers(ctx["servicer_id"])))
        resp = api.close_damage_report(ctx["damage_report_id"], {"outcome": "CLOSED"}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_REPAIR_NOT_COMPLETED)


class TestBidCreationOcc:
    def test_occ_bid_create_stale_damage_version_rejected(self, api):
        """PRD: "If the report's current `version` has advanced since that read —
        noting that every successfully created bid itself increments the report's
        `version` by one — the creation is rejected with `ERR_STALE_VERSION`
        (HTTP 412), ensuring each crew prices against a report it has actually
        read."

        Design: Corner/cross_cutting_layers/occ_bid_create_stale_damage_version_rejected
        """
        ctx = setup_bid_requested_report()
        crew2 = create_crew()
        dr_v = ctx["damage_report_version"]
        first = validate_success(api.create_bid(
            ctx["damage_report_id"],
            {"amount_cents": 40000, "expected_damage_report_version": dr_v},
            make_field_crew_headers(ctx["crew_id"])), expected_status=201)
        assert first["status"] == "DRAFT", "first create at the observed version succeeds"
        stale = api.create_bid(
            ctx["damage_report_id"],
            {"amount_cents": 38000, "expected_damage_report_version": dr_v},
            make_field_crew_headers(crew2["id"]))
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
