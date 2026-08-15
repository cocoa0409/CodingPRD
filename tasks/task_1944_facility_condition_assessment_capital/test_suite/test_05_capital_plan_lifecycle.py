"""Capital plan lifecycle: draft creation, submit/approve/reject/revise/
archive, segregation of duties, and facility-version OCC."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_capital_plan,
    create_capital_plan_payload,
    create_deficiency,
    create_draft_plan,
    create_facility,
    create_scenario,
    get_capital_plan,
    get_deficiency,
    get_facility,
    make_approver_headers,
    make_capital_planner_headers,
    remediate_to_corrected,
    run_scenario,
    setup_approved_plan,
    setup_facility_with_system,
    setup_funded_plan,
    setup_submitted_plan,
    submit_plan,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import APPROVER, MANAGER, PLANNER

FUNDED_WORKSPACE_KWARGS = dict(
    deficiency_specs=[{"description": "d", "cost_estimate_cents": 5000000,
                       "severity": 3, "urgency": 3, "recommended_year": 2027}],
    plan_overrides={"title": "P", "start_year": 2027, "horizon_years": 1},
    scenario_overrides={"name": "S", "annual_budget_cents": 10000000,
                        "escalation_rate": 0.0},
    system_overrides={"system_category": "HVAC", "name": "S",
                      "install_year": 2010, "design_life_years": 25,
                      "replacement_cost_cents": 50000000,
                      "condition_rating": 3})


class TestPlanCreation:
    def test_capital_plan_initial_state_is_draft(self, api):
        """PRD §3.6: "A new plan starts in `status` `DRAFT` with
        `total_programmed_cents` at 0, and its creation increments the owning
        facility's `version`."

        Design: Corner/state_machines/capital_plan_initial_state_is_draft
        """
        facility = create_facility()
        version_before = facility["version"]
        plan = create_draft_plan(facility["id"], title="P", start_year=2027,
                                 horizon_years=5)
        assert_capital_plan(plan)
        assert plan["status"] == "DRAFT"
        assert plan["total_programmed_cents"] == 0
        assert get_facility(facility["id"])["version"] == version_before + 1

    @pytest.mark.parametrize("bad_horizon", [0, 11])
    def test_horizon_out_of_range_rejected(self, api, bad_horizon):
        """PRD §3.6: "a `horizon_years` span of at least 1 and at most 10
        years — horizons outside that band are `ERR_INVALID_REQUEST`."

        Design: Corner/validations/horizon_out_of_range_rejected
        """
        facility = create_facility()
        resp = api.create_capital_plan(
            create_capital_plan_payload(facility["id"], facility["version"],
                                        title="P", start_year=2027,
                                        horizon_years=bad_horizon),
            PLANNER,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_occ_stale_facility_version_on_plan_create(self, api):
        """PRD §2.6: "First, creating a capital plan against a facility
        requires the request to carry `expected_facility_version`, set to the
        facility's `version` as the client last observed it. If the facility's
        current `version` has advanced past that value — for example because
        another planner has just created a plan for the same facility, which
        itself bumps the facility's version — the create is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_stale_facility_version_on_plan_create
        """
        facility = create_facility()
        observed_version = facility["version"]
        first = api.create_capital_plan(
            create_capital_plan_payload(facility["id"], observed_version,
                                        title="P1", start_year=2027,
                                        horizon_years=1),
            PLANNER,
        )
        validate_success(first, 201)
        assert get_facility(facility["id"])["version"] > observed_version, (
            "plan creation bumps the facility version")

        stale = api.create_capital_plan(
            create_capital_plan_payload(facility["id"], observed_version,
                                        title="P2", start_year=2028,
                                        horizon_years=1),
            PLANNER,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)


class TestSubmitRejectRevise:
    def test_submit_without_funded_items_rejected(self, api):
        """PRD §3.6: "Submission by a `CapitalPlanner` moves a plan from
        `DRAFT` to `SUBMITTED` and requires the program to be non-empty: at
        least one line item of the plan must have `funding_status` of
        `FUNDED`, otherwise the submission is rejected with
        `ERR_PRECONDITION_UNMET`."

        Design: Corner/state_machines/submit_without_funded_items_rejected
        """
        facility = create_facility()
        plan = create_draft_plan(facility["id"], title="P", start_year=2027,
                                 horizon_years=5)
        resp = api.submit_plan(plan["id"], PLANNER)
        validate_error(resp, ApiErrorId.ERR_PRECONDITION_UNMET)
        assert get_capital_plan(plan["id"])["status"] == "DRAFT"

    def test_reject_revise_cycle_is_repeatable(self, api):
        """PRD §3.6: "An `Approver` may instead reject a submitted plan,
        moving it from `SUBMITTED` to `REJECTED` with the version incremented.
        Rejection is not terminal: a `CapitalPlanner` may revise the plan,
        moving it from `REJECTED` back to `DRAFT` — again incrementing the
        version — after which scenarios may be re-run and the plan
        resubmitted."

        Design: Difficulty/non_linear_state_machine/capital_plan_reject_revise_cycle
        """
        workspace = setup_funded_plan(
            deficiency_specs=[{"description": "Head corrosion",
                               "cost_estimate_cents": 10000000, "severity": 3,
                               "urgency": 3, "recommended_year": 2027}],
            plan_overrides={"title": "P1", "start_year": 2027,
                            "horizon_years": 2},
            scenario_overrides={"name": "Base",
                                "annual_budget_cents": 50000000,
                                "escalation_rate": 0.0},
            system_overrides={"system_category": "FIRE_PROTECTION",
                              "name": "Sprinklers", "install_year": 2008,
                              "design_life_years": 25,
                              "replacement_cost_cents": 80000000,
                              "condition_rating": 3})
        plan_id = workspace["plan"]["id"]

        submitted = submit_plan(plan_id)
        assert submitted["status"] == "SUBMITTED"

        rejected = validate_success(api.reject_plan(plan_id, APPROVER))
        assert rejected["status"] == "REJECTED"

        revised = validate_success(api.revise_plan(plan_id, PLANNER))
        assert revised["status"] == "DRAFT", "revision loops back to DRAFT"

        resubmitted = submit_plan(plan_id)
        assert resubmitted["status"] == "SUBMITTED", "the cycle is repeatable"

    def test_loop_transitions_enforce_source_state(self, api):
        """PRD §3.6: "An `Approver` may instead reject a submitted plan,
        moving it from `SUBMITTED` to `REJECTED` with the version
        incremented."
        PRD §3.6: "a `CapitalPlanner` may revise the plan, moving it from
        `REJECTED` back to `DRAFT`"
        PRD §2.7: "**State legality** — the target resource must be in a state
        that permits the requested transition (submit requires `DRAFT`,
        approve requires `SUBMITTED`, verify requires `remediation_status` of
        `CORRECTED`, and so on); otherwise `ERR_INVALID_STATE`."

        Design: Difficulty/non_linear_state_machine/capital_plan_reject_revise_cycle
        """
        workspace = setup_funded_plan(**FUNDED_WORKSPACE_KWARGS)
        plan_id = workspace["plan"]["id"]

        # reject requires SUBMITTED; revise requires REJECTED: both illegal
        # while the plan is DRAFT.
        validate_error(api.reject_plan(plan_id, APPROVER),
                       ApiErrorId.ERR_INVALID_STATE)
        validate_error(api.revise_plan(plan_id, PLANNER),
                       ApiErrorId.ERR_INVALID_STATE)

        submit_plan(plan_id)
        # submit requires DRAFT: a second submit is illegal.
        validate_error(api.submit_plan(plan_id, PLANNER),
                       ApiErrorId.ERR_INVALID_STATE)
        assert get_capital_plan(plan_id)["status"] == "SUBMITTED"


class TestApproval:
    def test_terminal_approved_plan_rejects_revise(self, api):
        """PRD §3.6: "a `CapitalPlanner` may revise the plan, moving it from
        `REJECTED` back to `DRAFT`"
        PRD §3.6: "Both `APPROVED` and `ARCHIVED` are terminal states of the
        plan machine."
        PRD §2.7: "**State legality** — the target resource must be in a state
        that permits the requested transition (submit requires `DRAFT`,
        approve requires `SUBMITTED`, verify requires `remediation_status` of
        `CORRECTED`, and so on); otherwise `ERR_INVALID_STATE`."

        Design: Corner/state_machines/terminal_approved_plan_rejects_revise
        """
        workspace = setup_approved_plan(submitter_id="planner-x",
                                        approver_id="approver-y",
                                        **FUNDED_WORKSPACE_KWARGS)
        plan_id = workspace["plan"]["id"]
        assert workspace["approved"]["status"] == "APPROVED"
        resp = api.revise_plan(plan_id, PLANNER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_capital_plan(plan_id)["status"] == "APPROVED"

    def test_approve_moves_funded_deficiency_to_in_progress(self, api):
        """PRD §3.6: "On approval, every funded line item's linked deficiency
        has its `remediation_status` advanced from `OPEN` to `IN_PROGRESS`;
        deficiencies already `DEFERRED` or already `IN_PROGRESS` are left
        exactly as they are. Because open findings have now moved into
        in-progress work (both remain in the backlog set, but the membership
        mix changed), the facility's `backlog_cost_cents` and
        `facility_condition_index` are recomputed, and the plan's `version`
        increments."

        Design: Corner/state_machines/approve_side_effect_moves_open_deficiency_to_in_progress
        """
        workspace = setup_submitted_plan(submitter_id="planner-a",
                                         **FUNDED_WORKSPACE_KWARGS)
        deficiency_id = workspace["deficiencies"][0]["id"]
        approved = validate_success(api.approve_plan(
            workspace["plan"]["id"], make_approver_headers("approver-b")))
        assert approved["status"] == "APPROVED"

        deficiency = get_deficiency(deficiency_id)
        assert deficiency["remediation_status"] == "IN_PROGRESS", (
            "approval advances funded OPEN findings into IN_PROGRESS")
        facility = get_facility(workspace["facility"]["id"])
        assert facility["backlog_cost_cents"] == 5000000, (
            "IN_PROGRESS remains in the backlog set")
        # 5000000 / 50000000 = 0.10 -> 0.1000.
        assert facility["facility_condition_index"] == pytest.approx(0.10,
                                                                     abs=1e-9)

    def test_segregation_of_duties_blocks_submitter_approving(self, api):
        """PRD §3.6: "Segregation of duties is enforced here: the approving
        identity must differ from the identity that submitted the plan, and a
        match is rejected with `ERR_SEGREGATION_OF_DUTIES`."
        PRD §2.1: "when a plan is submitted, the server records the
        submitter's `X-User-ID`, and a later approval attempt whose
        `X-User-ID` equals that recorded submitter identity is rejected with
        `ERR_SEGREGATION_OF_DUTIES`"

        Design: Corner/validations/segregation_of_duties_blocks_submitter_approving
        """
        workspace = setup_submitted_plan(submitter_id="shared-user-1",
                                         **FUNDED_WORKSPACE_KWARGS)
        plan_id = workspace["plan"]["id"]
        resp = api.approve_plan(plan_id, make_approver_headers("shared-user-1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        assert get_capital_plan(plan_id)["status"] == "SUBMITTED"

        # A distinct approver identity clears the same plan.
        approved = validate_success(api.approve_plan(
            plan_id, make_approver_headers("approver-distinct")))
        assert approved["status"] == "APPROVED"


class TestValidationCascadeOnApprove:
    def test_state_error_precedes_segregation_check_on_approve(self, api):
        """PRD §2.7: "Every request is screened by an ordered validation
        cascade, and the order is part of the contract — it determines which
        error a request with multiple problems surfaces."
        PRD §2.7: "5. **State legality** — the target resource must be in a
        state that permits the requested transition (submit requires `DRAFT`,
        approve requires `SUBMITTED`, verify requires `remediation_status` of
        `CORRECTED`, and so on); otherwise `ERR_INVALID_STATE`."
        PRD §2.7: "7. **Segregation of duties** — the approving `Approver`'s
        identity must differ from the submitting identity; otherwise
        `ERR_SEGREGATION_OF_DUTIES`."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_approve
        """
        facility = create_facility()
        plan = create_draft_plan(facility["id"], title="P", start_year=2027,
                                 horizon_years=1)
        # Approve on a DRAFT plan: the state check (earlier in the cascade)
        # masks every later business-safety check.
        resp = api.approve_plan(plan["id"],
                                make_approver_headers("same-user-1"))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_capital_plan(plan["id"])["status"] == "DRAFT", (
            "no side effects fired")

    def test_approve_from_rejected_state_also_state_error(self, api):
        """PRD §3.6: "Approval belongs to the `Approver` and moves the plan
        from `SUBMITTED` to `APPROVED`."
        PRD §2.7: "5. **State legality** — the target resource must be in a
        state that permits the requested transition (submit requires `DRAFT`,
        approve requires `SUBMITTED`, verify requires `remediation_status` of
        `CORRECTED`, and so on); otherwise `ERR_INVALID_STATE`."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_approve
        """
        workspace = setup_submitted_plan(submitter_id="planner-s",
                                         **FUNDED_WORKSPACE_KWARGS)
        plan_id = workspace["plan"]["id"]
        rejected = validate_success(
            api.reject_plan(plan_id, make_approver_headers("approver-r")))
        assert rejected["status"] == "REJECTED"

        # REJECTED is not SUBMITTED: the state gate fires regardless of who
        # calls approve (submitter or anyone else).
        resp = api.approve_plan(plan_id, make_approver_headers("planner-s"))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_capital_plan(plan_id)["status"] == "REJECTED"


class TestArchiveGate:
    def test_archive_blocked_until_funded_work_closed_out(self, api):
        """PRD §3.6: "Archival is gated on close-out: every deficiency linked
        by the plan's funded line items must have `remediation_status` of
        either `CORRECTED` or `DEFERRED`; any funded finding still open or in
        progress causes the archive attempt to be rejected with
        `ERR_PRECONDITION_UNMET`."
        PRD §3.6: "On approval, every funded line item's linked deficiency has
        its `remediation_status` advanced from `OPEN` to `IN_PROGRESS`"

        Design: Difficulty/cross_entity_state_dependency/archive_requires_funded_deficiencies_closed_out
        """
        workspace = setup_approved_plan(
            submitter_id="planner-1", approver_id="approver-9",
            deficiency_specs=[{"description": "Battery strings EOL",
                               "cost_estimate_cents": 10000000, "severity": 3,
                               "urgency": 3, "recommended_year": 2027}],
            plan_overrides={"title": "P", "start_year": 2027,
                            "horizon_years": 1},
            scenario_overrides={"name": "S",
                                "annual_budget_cents": 20000000,
                                "escalation_rate": 0.0},
            system_overrides={"system_category": "ELECTRICAL", "name": "UPS",
                              "install_year": 2013, "design_life_years": 15,
                              "replacement_cost_cents": 50000000,
                              "condition_rating": 3})
        plan_id = workspace["plan"]["id"]
        deficiency_id = workspace["deficiencies"][0]["id"]
        assert get_deficiency(deficiency_id)["remediation_status"] == \
            "IN_PROGRESS", "approval moved the funded finding to IN_PROGRESS"

        blocked = api.archive_plan(plan_id, PLANNER)
        validate_error(blocked, ApiErrorId.ERR_PRECONDITION_UNMET)
        assert get_capital_plan(plan_id)["status"] == "APPROVED"

        remediate_to_corrected(deficiency_id)
        archived = validate_success(api.archive_plan(plan_id, PLANNER))
        assert archived["status"] == "ARCHIVED"

    def test_archive_succeeds_with_funded_deficiency_deferred(self, api):
        """PRD §3.6: "every deficiency linked by the plan's funded line items
        must have `remediation_status` of either `CORRECTED` or `DEFERRED`"
        PRD §3.6: "deficiencies already `DEFERRED` or already `IN_PROGRESS`
        are left exactly as they are."
        PRD §3.7: "The candidate pool is every deficiency of the plan's
        facility whose `remediation_status` is `OPEN` or `DEFERRED`, whose
        owning system is not `RETIRED`, and whose `recommended_year` falls
        inside the plan horizon"

        Design: Difficulty/cross_entity_state_dependency/archive_requires_funded_deficiencies_closed_out
        """
        # Defer the finding BEFORE the run: DEFERRED findings are still
        # waterfall candidates, and approval leaves DEFERRED untouched.
        facility, system = setup_facility_with_system(
            {"system_category": "ELECTRICAL", "name": "UPS",
             "install_year": 2013, "design_life_years": 15,
             "replacement_cost_cents": 50000000, "condition_rating": 3})
        deficiency = create_deficiency(
            system["id"], description="Battery strings EOL",
            cost_estimate_cents=10000000, severity=3, urgency=3,
            recommended_year=2027)
        deferred = validate_success(api.defer_deficiency(deficiency["id"],
                                                         MANAGER))
        assert deferred["remediation_status"] == "DEFERRED"
        plan = create_draft_plan(facility["id"], title="P", start_year=2027,
                                 horizon_years=1)
        scenario = create_scenario(plan["id"], name="S",
                                   annual_budget_cents=20000000,
                                   escalation_rate=0.0)
        run_scenario(scenario["id"])
        submit_plan(plan["id"], make_capital_planner_headers("planner-d"))
        approved = validate_success(api.approve_plan(
            plan["id"], make_approver_headers("approver-d")))
        assert approved["status"] == "APPROVED"
        assert get_deficiency(deficiency["id"])["remediation_status"] == \
            "DEFERRED", "approval leaves DEFERRED findings exactly as they are"

        archived = validate_success(api.archive_plan(plan["id"], PLANNER))
        assert archived["status"] == "ARCHIVED", (
            "DEFERRED satisfies the archive close-out gate")
