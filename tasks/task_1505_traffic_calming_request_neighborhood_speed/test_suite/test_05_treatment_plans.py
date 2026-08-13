"""Treatment plans: OCC-gated creation, supersession, the review cycle,
segregation of duties, and the three-link approval cascade with its
budget re-baseline (PRD §2.7, §2.8, §3.5)."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    api_client,
    approve_plan,
    assert_cycle_budget_invariant,
    create_treatment_plan,
    create_treatment_plan_payload,
    get_funding_cycle,
    get_request,
    get_treatment_plan,
    make_city_engineer_headers,
    make_traffic_engineer_headers,
    setup_funded,
    submit_plan_for_review,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestPlanApprovalCascade:
    """Provisional allocation 21500 (ask 20000); plan estimate 30000 ->
    final allocation 32250; cycle budget 80000."""

    def _setup(self):
        ctx = setup_funded(
            name="Birch Way",
            resident_prefix="tc1",
            requested_budget_cents=20000,
            cycle_budget_total_cents=80000,
        )
        assert ctx["request"]["allocated_cents"] == 21500
        plan = create_treatment_plan(
            ctx["request"]["id"], "CHICANE", 30000, "te-1"
        )
        submit_plan_for_review(plan["id"], "te-1")
        return ctx, plan

    def test_approval_moves_plan_and_request(self):
        """PRD §3.5: "Approval then fires a three-link cascade. Link one: the plan becomes `APPROVED`, stamping `approved_at` and recording the approver as `approved_by_user_id`. Link two: the request advances from `DESIGN_IN_PROGRESS` to `BALLOT_READY`."

        Design: Difficulty/transitive_cascade/plan_approval_rebaselines_budget_depth3
        """
        ctx, plan = self._setup()
        approved = validate_success(
            api_client.approve_plan(
                plan["id"], make_city_engineer_headers("ce-1")
            ),
            200,
        )
        assert approved["status"] == "APPROVED", (
            f"link 1: plan must be APPROVED, got {approved['status']}"
        )
        assert approved["approved_by_user_id"] == "ce-1"
        req = get_request(ctx["request"]["id"])
        assert req["status"] == "BALLOT_READY", (
            f"link 2: request must reach BALLOT_READY, got {req['status']}"
        )

    def test_approval_rebaselines_cycle_budget(self):
        """PRD §3.5: "Link three re-baselines the funding cycle: the final allocation is the plan's `estimated_cost_cents` plus a contingency of seven and a half percent of that estimate, rounded half-up to a whole cent; the delta between that final allocation and the request's current `allocated_cents` must fit within the cycle's `budget_available_cents`, or the entire approval is rejected with `ERR_REBASELINE_EXCEEDS_BUDGET`. When it fits, the delta is added to the cycle's `budget_committed_cents`, subtracted from its `budget_available_cents`, and the request's `allocated_cents` takes the final allocation."

        Design: Difficulty/transitive_cascade/plan_approval_rebaselines_budget_depth3
        """
        ctx, plan = self._setup()
        cycle_before = get_funding_cycle(ctx["cycle"]["id"])
        assert cycle_before["budget_committed_cents"] == 21500
        assert cycle_before["budget_available_cents"] == 58500

        approve_plan(plan["id"], "ce-1")

        # final = 30000 + round_half_up(2250.00) = 32250; delta = +10750.
        req = get_request(ctx["request"]["id"])
        assert req["allocated_cents"] == 32250, (
            f"re-baselined allocation must be 32250, got {req['allocated_cents']}"
        )
        cycle = get_funding_cycle(ctx["cycle"]["id"])
        assert cycle["budget_committed_cents"] == 32250
        assert cycle["budget_available_cents"] == 47750
        assert_cycle_budget_invariant(cycle)


class TestPlanLifecycleGates:
    def test_approve_plan_from_draft_rejected(self):
        """PRD §3.5: "Approval requires the plan to be `SUBMITTED_FOR_REVIEW` (otherwise `ERR_PLAN_INVALID_STATE`)"

        Design: Corner/state_machines/approve_plan_from_draft_rejected
        """
        ctx = setup_funded(name="Draft Ave", resident_prefix="drf")
        plan = create_treatment_plan(
            ctx["request"]["id"], "CHICANE", 8000, "te-1"
        )
        assert plan["status"] == "DRAFT"
        resp = api_client.approve_plan(
            plan["id"], make_city_engineer_headers("ce-1")
        )
        validate_error(resp, ApiErrorId.ERR_PLAN_INVALID_STATE)
        assert get_treatment_plan(plan["id"])["status"] == "DRAFT"

    def test_rebaseline_exceeds_budget_rejected_at_approval(self):
        """PRD §3.5: "the delta between that final allocation and the request's current `allocated_cents` must fit within the cycle's `budget_available_cents`, or the entire approval is rejected with `ERR_REBASELINE_EXCEEDS_BUDGET`."

        Design: Corner/validations/rebaseline_exceeds_budget_rejected_at_approval
        """
        ctx = setup_funded(
            name="Fiscal Ave",
            resident_prefix="fis",
            requested_budget_cents=10000,
            cycle_budget_total_cents=11000,
        )
        # Provisional 10750 leaves only 250 available.
        cycle = get_funding_cycle(ctx["cycle"]["id"])
        assert cycle["budget_available_cents"] == 250

        plan = create_treatment_plan(
            ctx["request"]["id"], "SPEED_HUMP", 50000, "te-1"
        )
        submit_plan_for_review(plan["id"], "te-1")
        # final = 53750; delta = 53750 - 10750 = 43000 > 250.
        resp = api_client.approve_plan(
            plan["id"], make_city_engineer_headers("ce-1")
        )
        validate_error(resp, ApiErrorId.ERR_REBASELINE_EXCEEDS_BUDGET)
        cycle_after = get_funding_cycle(ctx["cycle"]["id"])
        assert cycle_after["budget_committed_cents"] == 10750, (
            "the rejected approval must leave the committed balance unchanged"
        )
        assert get_treatment_plan(plan["id"])["status"] == "SUBMITTED_FOR_REVIEW"

    def test_treatment_prohibited_on_emergency_route(self):
        """PRD §3.5: "One safety rule is checked at this gate: on a segment whose `emergency_route` is true, `SPEED_HUMP` and `CHICANE` are prohibited and only `SIGNAGE` may be selected — a prohibited selection is rejected with `ERR_TREATMENT_PROHIBITED_ON_EMERGENCY_ROUTE`."
        PRD §3.5: "Plans can be listed, optionally filtered by `request_id` or `status`."

        Design: Corner/validations/treatment_prohibited_on_emergency_route
        """
        ctx = setup_funded(
            name="Emergency Ave", resident_prefix="emr", emergency_route=True
        )
        version = get_request(ctx["request"]["id"])["version"]
        resp = api_client.create_treatment_plan(
            ctx["request"]["id"],
            create_treatment_plan_payload(
                treatment_type="SPEED_HUMP",
                estimated_cost_cents=9000,
                expected_request_version=version,
            ),
            make_traffic_engineer_headers("te-1"),
        )
        validate_error(resp, ApiErrorId.ERR_TREATMENT_PROHIBITED_ON_EMERGENCY_ROUTE)
        rows, _ = validate_paginated(
            api_client.list_treatment_plans(
                ADMIN, params={"request_id": ctx["request"]["id"]}
            )
        )
        assert rows == [], "no plan row may be created by the rejected call"


class TestSegregationOfDuties:
    def test_approver_who_authored_plan_rejected(self):
        """PRD §3.5: "Approval requires the plan to be `SUBMITTED_FOR_REVIEW` (otherwise `ERR_PLAN_INVALID_STATE`) and enforces segregation of duties: the approver's `X-User-ID` must differ from the plan's `created_by_user_id`, and a self-approval is rejected with `ERR_APPROVER_IS_PLAN_AUTHOR`."

        Design: Corner/rbac/segregation_of_duties_approver_is_author
        """
        ctx = setup_funded(name="SoD Ave", resident_prefix="sod")
        plan = create_treatment_plan(
            ctx["request"]["id"], "SPEED_HUMP", 9000, "eng-shared"
        )
        assert plan["created_by_user_id"] == "eng-shared"
        submit_plan_for_review(plan["id"], "eng-shared")

        self_approval = api_client.approve_plan(
            plan["id"], make_city_engineer_headers("eng-shared")
        )
        validate_error(self_approval, ApiErrorId.ERR_APPROVER_IS_PLAN_AUTHOR)

        other = validate_success(
            api_client.approve_plan(
                plan["id"], make_city_engineer_headers("ce-2")
            ),
            200,
        )
        assert other["status"] == "APPROVED"


class TestPlanCreateOcc:
    def test_stale_request_version_rejected_on_plan_create(self):
        """PRD §2.7: "Creating a treatment plan against a traffic calming request requires `expected_request_version`, carrying the client's last observed `version` of that request; if another writer has advanced the request's version since the client last read it, the creation is rejected with `ERR_STALE_VERSION` (HTTP 412)"
        PRD §3.5: "Any existing plan of the same request sitting in `DRAFT`, `SUBMITTED_FOR_REVIEW`, or `REVISION_REQUESTED` moves automatically to `WITHDRAWN`; the new plan is born in `DRAFT` with its `created_by_user_id` taken from the author's `X-User-ID`; and the request's `version` increments by one."

        Design: Corner/cross_cutting_layers/occ_stale_version_on_plan_create
        """
        ctx = setup_funded(name="OCC Ave", resident_prefix="occ")
        req_id = ctx["request"]["id"]
        v0 = get_request(req_id)["version"]

        plan1 = validate_success(
            api_client.create_treatment_plan(
                req_id,
                create_treatment_plan_payload(
                    treatment_type="SPEED_HUMP",
                    estimated_cost_cents=9000,
                    expected_request_version=v0,
                ),
                make_traffic_engineer_headers("te-1"),
            ),
            201,
        )

        stale = api_client.create_treatment_plan(
            req_id,
            create_treatment_plan_payload(
                treatment_type="CHICANE",
                estimated_cost_cents=7000,
                expected_request_version=v0,
            ),
            make_traffic_engineer_headers("te-2"),
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

        v1 = get_request(req_id)["version"]
        plan2 = validate_success(
            api_client.create_treatment_plan(
                req_id,
                create_treatment_plan_payload(
                    treatment_type="CHICANE",
                    estimated_cost_cents=7000,
                    expected_request_version=v1,
                ),
                make_traffic_engineer_headers("te-2"),
            ),
            201,
        )
        assert plan2["status"] == "DRAFT"
        assert get_treatment_plan(plan1["id"])["status"] == "WITHDRAWN", (
            "the successful retry must supersede the earlier draft"
        )


class TestImmediateConsistency:
    def test_cascaded_writes_visible_on_immediate_read(self):
        """PRD §2.8: "Child-side changes that determine a parent's stage propagate upward immediately, so a parent and its children never disagree about where the workflow stands."

        Design: Corner/consistency_model/immediate_visibility_of_cascaded_writes
        """
        ctx = setup_funded(
            name="Imm Read Ave", resident_prefix="imr",
            requested_budget_cents=10000, cycle_budget_total_cents=50000,
        )
        plan = create_treatment_plan(
            ctx["request"]["id"], "SPEED_HUMP", 9000, "te-1"
        )
        submit_plan_for_review(plan["id"], "te-1")
        approve_plan(plan["id"], "ce-1")

        # The very next reads must already show the cascaded writes.
        req = get_request(ctx["request"]["id"])
        assert req["status"] == "BALLOT_READY", (
            f"no read-your-writes lag: expected BALLOT_READY, "
            f"got {req['status']}"
        )
        cycle = get_funding_cycle(ctx["cycle"]["id"])
        # final allocation = 9000 + 675 = 9675.
        assert cycle["budget_committed_cents"] == 9675, (
            f"re-baselined committed balance must be visible immediately, "
            f"got {cycle['budget_committed_cents']}"
        )
        assert_cycle_budget_invariant(cycle)
