"""Estimate lifecycle: decisions, tiered routing, supersession, and the
optimistic-concurrency guards (PRD §2.7, §3.4)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_estimate,
    create_estimate,
    create_estimate_payload,
    create_program,
    create_submitted_work_order,
    get_estimate_for_order,
    get_program,
    get_success_data,
    get_work_order,
    post_charge,
    setup_charging_world,
    setup_variance_hold_world,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
ENGINEER = TEST_USERS["engineer_headers"]
SUPERVISOR = TEST_USERS["supervisor_headers"]
CONTROLLER = TEST_USERS["controller_headers"]
CLERK = TEST_USERS["clerk_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


class TestEstimateReject:
    def test_estimate_reject_happy_path_and_lockdown(self, api):
        """PRD §3.4: "Rejection is the parallel decision with equal rigor and no financial rewiring: the same order-state set, the same tier routing computed the same way, and the same segregation-of-duties rule against `submitted_by_user_id`, but no version field on the request and no budget or variance adjustment — the estimate simply becomes `REJECTED` with `decided_by_user_id` recorded."
        PRD §3.4: "Deciding an estimate — approval or rejection — is permitted only while the work order stands at `SUBMITTED`, `AUTHORIZED`, `IN_PROGRESS`, or `SUSPENDED`; any other order state is rejected with `ERR_INVALID_STATE`, and the estimate itself must still be `PROPOSED`."

        Design: Corner/state_machines/estimate_reject_happy_path_and_lockdown
        """
        program = create_program(code="CAP-EREJ", authorized_amount_cents=50_000_000)
        wo, est = create_submitted_work_order(program["id"], title="Rejectable",
                                              initial_estimated_cost_cents=100_000)

        rejected = validate_success(api.reject_estimate(est["id"], SUPERVISOR))
        assert rejected["status"] == "REJECTED"
        assert rejected["decided_by_user_id"] == "sup-1"

        # The rejected estimate is terminal: a later approve attempt fails.
        fresh_version = get_work_order(wo["id"])["version"]
        resp = api.approve_estimate(est["id"], fresh_version, SUPERVISOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


class TestSupersessionLookup:
    def test_estimates_reverse_lookup_by_supersedes_estimate_id(self, api):
        """PRD §3.4: "The previously `APPROVED` estimate, when one exists, becomes `SUPERSEDED`, and the newly approved estimate's `supersedes_estimate_id` points back at that predecessor; the order's `approved_estimate_cents` takes the new `estimated_cost_cents`; and the estimate records its `routing_tier` (`SUPERVISOR` or `CONTROLLER`) and its `decided_by_user_id`."
        PRD §3.4: "Estimates may be listed filtered by `work_order_id`, `status`, or `supersedes_estimate_id`, which makes the supersession chain directly traversable."

        Design: Corner/entities/estimates_reverse_lookup_by_supersedes_estimate_id
        """
        program = create_program(code="CAP-SUP", authorized_amount_cents=50_000_000)
        wo, est1 = create_submitted_work_order(
            program["id"], title="Supersede order",
            initial_estimated_cost_cents=100_000)
        approve_estimate(est1["id"], wo["id"], SUPERVISOR)

        # +5% delta -> SUPERVISOR tier.
        est2 = create_estimate(wo["id"], 105_000)
        approved2 = approve_estimate(est2["id"], wo["id"], SUPERVISOR)
        assert approved2["supersedes_estimate_id"] == est1["id"]

        superseded_view = validate_success(api.get_estimate(est1["id"], AUDITOR))
        assert superseded_view["status"] == "SUPERSEDED"

        data, meta = validate_paginated(api.list_estimates(
            AUDITOR, params={"supersedes_estimate_id": est1["id"]}))
        assert meta["total_count"] == 1
        assert len(data) == 1
        assert data[0]["id"] == est2["id"]


class TestRoutingTierBoundary:
    def test_estimate_routing_tier_boundary_10_percent(self, api):
        """PRD §3.4: "The decision routes by tier, computed at decision time rather than at submission: when the order has no currently approved estimate — the first estimate is always such a case — the tier is `SUPERVISOR`; otherwise the absolute difference between the new `estimated_cost_cents` and the current `approved_estimate_cents`, scaled by one hundred, is compared against the current approved amount scaled by ten, and reaching or exceeding that bound routes the decision to `CONTROLLER` — the boundary is inclusive, so a change of exactly 10.00% requires the `Controller` — while anything smaller stays `SUPERVISOR`. A `WorkOrderSupervisor` who attempts a `CONTROLLER`-tier decision is rejected with `ERR_APPROVAL_TIER_REQUIRED`; a `Controller` may decide any tier."
        PRD §3.4: "The previously `APPROVED` estimate, when one exists, becomes `SUPERSEDED`, and the newly approved estimate's `supersedes_estimate_id` points back at that predecessor; the order's `approved_estimate_cents` takes the new `estimated_cost_cents`; and the estimate records its `routing_tier` (`SUPERVISOR` or `CONTROLLER`) and its `decided_by_user_id`."

        Design: Corner/calculations/estimate_routing_tier_boundary_10_percent
        """
        program = create_program(code="CAP-TIER")
        wo, est1 = create_submitted_work_order(program["id"], title="Tier boundary",
                                               initial_estimated_cost_cents=10_000)
        approve_estimate(est1["id"], wo["id"], SUPERVISOR)

        # Exactly +10.00% (11,000 vs 10,000) routes to CONTROLLER.
        est2 = create_estimate(wo["id"], 11_000)
        version = get_work_order(wo["id"])["version"]
        resp = api.approve_estimate(est2["id"], version, SUPERVISOR)
        validate_error(resp, ApiErrorId.ERR_APPROVAL_TIER_REQUIRED, 403)

        version = get_work_order(wo["id"])["version"]
        approved2 = validate_success(
            api.approve_estimate(est2["id"], version, CONTROLLER))
        assert approved2["status"] == "APPROVED"
        assert approved2["routing_tier"] == "CONTROLLER"

        # A 1-cent downtick against 11,000 is below the bound -> SUPERVISOR.
        est3 = create_estimate(wo["id"], 10_999)
        version = get_work_order(wo["id"])["version"]
        approved3 = validate_success(
            api.approve_estimate(est3["id"], version, SUPERVISOR))
        assert approved3["status"] == "APPROVED"
        assert approved3["routing_tier"] == "SUPERVISOR"


class TestEstimateBelowActuals:
    def test_estimate_below_actuals_rejected(self, api):
        """PRD §3.4: "Approval alone carries two further guards — the OCC field `expected_work_order_version` from §2.7, and the fiscal floor that an estimate may not be approved below the order's `actual_direct_cents`, else `ERR_ESTIMATE_BELOW_ACTUALS`."

        Design: Corner/validations/estimate_below_actuals_rejected
        """
        world = setup_charging_world(estimate_cents=10_000)
        wo = world["work_order"]
        post_charge(wo["id"], base_amount_cents=5_000, charge_date="2026-08-05")
        assert get_work_order(wo["id"])["actual_direct_cents"] == 5_000

        # 60% below the current approved 10,000 -> CONTROLLER tier; the
        # Controller passes the tier and the SoD check but hits the floor.
        est2 = create_estimate(wo["id"], 4_000)
        version = get_work_order(wo["id"])["version"]
        resp = api.approve_estimate(est2["id"], version, CONTROLLER)
        validate_error(resp, ApiErrorId.ERR_ESTIMATE_BELOW_ACTUALS, 422)


class TestEstimateOptimisticConcurrency:
    def test_estimate_create_stale_version_rejected(self, api):
        """PRD §3.4: "Creating an estimate legitimately withdraws the order's currently `PROPOSED` estimate — a system transition to `WITHDRAWN` — assigns the newcomer the order's next `estimate_seq`, and increments the work order's `version` by one; precisely because creation mutates the order, a request whose `expected_work_order_version` no longer matches the order's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/estimate_create_stale_version_rejected
        """
        program = create_program(code="CAP-OCC1")
        wo, est1 = create_submitted_work_order(
            program["id"], title="OCC create", initial_estimated_cost_cents=100_000)
        observed_version = wo["version"]

        est2 = validate_success(api.create_estimate(
            create_estimate_payload(
                work_order_id=wo["id"], estimated_cost_cents=105_000,
                expected_work_order_version=observed_version), ENGINEER), 201)
        assert est2["estimate_seq"] == 2, "the newcomer takes the next estimate_seq"

        # The same, now-stale version is rejected on the next create.
        resp = api.create_estimate(
            create_estimate_payload(
                work_order_id=wo["id"], estimated_cost_cents=106_000,
                expected_work_order_version=observed_version), ENGINEER)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)

        withdrawn, meta = validate_paginated(api.list_estimates(
            AUDITOR, params={"work_order_id": wo["id"], "status": "WITHDRAWN"}))
        assert meta["total_count"] == 1
        assert withdrawn[0]["id"] == est1["id"], (
            "the first create withdrew the PROPOSED seed estimate")

    def test_estimate_approve_stale_version_rejected(self, api):
        """PRD §2.7: "Exactly two write operations in the API carry a version field: creating an estimate on a work order, and approving an estimate. Both require a non-optional `expected_work_order_version` input carrying the work-order `version` the client last observed. If that value no longer equals the work order's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/estimate_approve_stale_version_rejected
        """
        program = create_program(code="CAP-OCC2")
        wo, est1 = create_submitted_work_order(
            program["id"], title="OCC approve", initial_estimated_cost_cents=100_000)
        approve_estimate(est1["id"], wo["id"], SUPERVISOR)

        stale_version = get_work_order(wo["id"])["version"]
        est2 = create_estimate(wo["id"], 105_000)  # bumps the work-order version
        assert stale_version != get_work_order(wo["id"])["version"]

        # Approving with the pre-create version is stale.
        resp = api.approve_estimate(est2["id"], stale_version, CONTROLLER)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)

        # Re-reading and approving at the fresh version succeeds.
        fresh_version = get_work_order(wo["id"])["version"]
        approved = validate_success(
            api.approve_estimate(est2["id"], fresh_version, CONTROLLER))
        assert approved["status"] == "APPROVED"


class TestEstimateApprovalCascade:
    def test_estimate_approval_supersedes_and_recommits_budget(self, api):
        """PRD §3.4: "Approval rewires the order's financial picture in one atomic step. The previously `APPROVED` estimate, when one exists, becomes `SUPERSEDED`, and the newly approved estimate's `supersedes_estimate_id` points back at that predecessor; the order's `approved_estimate_cents` takes the new `estimated_cost_cents`; and the estimate records its `routing_tier` (`SUPERVISOR` or `CONTROLLER`) and its `decided_by_user_id`. When the order stands at `AUTHORIZED`, `IN_PROGRESS`, or `SUSPENDED`, the program's `committed_amount_cents` shifts by the difference between the newly approved amount and the previously approved one."

        Design: Difficulty/transitive_cascade/estimate_approval_supersede_budget_posture_cascade
        """
        world = setup_variance_hold_world(estimate_cents=10_000,
                                          charge_bases=(10_000, 1_001))
        program, wo, est1 = world["program"], world["work_order"], world["estimate"]
        assert get_work_order(wo["id"])["variance_posture"] == "RE_ESTIMATE_REQUIRED"
        assert get_program(program["id"])["committed_amount_cents"] == 10_000

        est2 = create_estimate(wo["id"], 12_000, notes="field conditions")
        # +20% delta -> CONTROLLER tier.
        approved2 = approve_estimate(est2["id"], wo["id"], CONTROLLER)
        assert approved2["routing_tier"] == "CONTROLLER"
        assert approved2["supersedes_estimate_id"] == est1["id"]
        assert approved2["decided_by_user_id"] == "ctrl-1"

        est1_view = validate_success(api.get_estimate(est1["id"], AUDITOR))
        assert est1_view["status"] == "SUPERSEDED"

        wo_view = get_work_order(wo["id"])
        assert wo_view["approved_estimate_cents"] == 12_000
        program_view = get_program(program["id"])
        assert program_view["committed_amount_cents"] == 12_000, (
            "committed shifts by the +2,000 delta from 10,000")

    def test_estimate_approval_clears_variance_hold(self, api):
        """PRD §3.4: "The order's `variance_posture` is then recomputed against the new approved amount, so a `RE_ESTIMATE_REQUIRED` hold clears once the actuals scaled by one hundred no longer exceed the approved estimate scaled by one hundred ten."
        PRD §3.5: "While the posture stands at `RE_ESTIMATE_REQUIRED`, any further charge posting is rejected with `ERR_VARIANCE_HOLD` (HTTP 409) — though the charge that itself crosses the threshold is allowed to post, flipping the posture only for the next charge — and the hold clears when an approved re-estimate or a reversal brings the comparison back within bound."

        Design: Difficulty/transitive_cascade/estimate_approval_supersede_budget_posture_cascade
        """
        world = setup_variance_hold_world(estimate_cents=10_000,
                                          charge_bases=(10_000, 1_001))
        wo = world["work_order"]
        assert get_work_order(wo["id"])["variance_posture"] == "RE_ESTIMATE_REQUIRED"

        # The hold blocks charging while it stands.
        blocked = api.create_cost_charge(
            {"work_order_id": wo["id"], "cost_type": "MATERIAL",
             "base_amount_cents": 500, "charge_date": "2026-08-07"}, CLERK)
        validate_error(blocked, ApiErrorId.ERR_VARIANCE_HOLD, 409)

        # 11,001 * 100 <= 12,000 * 110, so approval of the 12,000 re-estimate
        # clears the hold and charging unblocks.
        est2 = create_estimate(wo["id"], 12_000, notes="field conditions")
        approve_estimate(est2["id"], wo["id"], CONTROLLER)
        assert get_work_order(wo["id"])["variance_posture"] == "WITHIN_TOLERANCE"

        charge = post_charge(wo["id"], base_amount_cents=500,
                             charge_date="2026-08-07")
        assert charge["total_cents"] == 500
