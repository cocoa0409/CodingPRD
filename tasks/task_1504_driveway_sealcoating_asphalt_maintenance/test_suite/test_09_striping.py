"""Striping: the commercial-lot parallel dimension, its approval chain, and
its gate on work-order completion."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_crew,
    create_material_lot,
    create_route_sheet,
    get_work_order,
    post_weather_snapshot,
    schedule_work_order,
    set_clock,
    setup_accepted_job,
    setup_in_progress_job,
    validate_error,
    validate_success,
)

ESTIMATOR = TEST_USERS["estimator_headers"]
CREW_LEAD = TEST_USERS["crew_lead_headers"]

STRIPING_SCOPE = {
    "include_crack_fill": False,
    "include_patch": False,
    "include_striping": True,
    "stripe_linear_ft": 1960,
}

COMMERCIAL_2000 = dict(
    lot_kind="COMMERCIAL_LOT",
    address="100 Commerce Way",
    measured_area_sqft=2000,
    crack_linear_ft=0,
    pothole_count=0,
    pothole_area_sqft=0,
    oil_spot_area_sqft=0,
)


class TestStripingFullChain:
    def test_ada_computation_and_completion_gate(self, api):
        """PRD §3.8: "76 through 100 require 4 — and exactly 100 stalls is 4,
        since the overflow formula starts at 101." and "The computed
        `ada_stalls_required` feeds `stripe_linear_ft_computed`: 18 linear
        feet per stall plus 40 linear feet per accessible stall." PRD §3.7:
        "when striping was in scope, requires the striping dimension to have
        reached `VERIFIED` (else `ERR_STRIPING_NOT_VERIFIED`)".

        Design: Corner/state_machines/striping_full_chain_and_complete_gate
        """
        ctx = setup_in_progress_job(
            **COMMERCIAL_2000,
            quote_overrides=STRIPING_SCOPE,
            window_start_hour=7,
            window_end_hour=11,
            drive_minutes_est=20,
            vehicles_to_move=40,
            delivered_gallons=200,
        )
        wo_id = ctx["work_order"]["id"]

        planned = validate_success(
            api.plan_striping(wo_id, {"stall_count": 100}, ESTIMATOR)
        )
        assert planned["striping_status"] == "PLANNED"
        assert planned["ada_stalls_required"] == 4, (
            f"exactly 100 stalls requires 4 accessible stalls, got {planned['ada_stalls_required']}"
        )
        assert planned["stripe_linear_ft_computed"] == 1960, (
            f"100 * 18 + 4 * 40 = 1960, got {planned['stripe_linear_ft_computed']}"
        )
        validate_success(api.approve_striping(wo_id, ESTIMATOR))

        finished = validate_success(
            api.finish_work_order(
                wo_id,
                {
                    "actual_area_sqft": 2000,
                    "actual_crack_ft": 0,
                    "actual_pothole_area_sqft": 0,
                    "actual_stripe_ft": 1960,
                    "gallons_used": 27,
                },
                CREW_LEAD,
            )
        )
        set_clock(finished["cure_until"])

        # Striping only APPROVED at this point: completion is gated.
        resp = api.complete_work_order(wo_id, CREW_LEAD)
        validate_error(resp, ApiErrorId.ERR_STRIPING_NOT_VERIFIED, 409)

        applied = validate_success(api.mark_striping_applied(wo_id, CREW_LEAD))
        assert applied["striping_status"] == "APPLIED"
        verified = validate_success(api.verify_striping(wo_id, ESTIMATOR))
        assert verified["striping_status"] == "VERIFIED"

        completed = validate_success(api.complete_work_order(wo_id, CREW_LEAD))
        assert completed["execution_status"] == "COMPLETED"


class TestMarkAppliedExecutionGate:
    def test_mark_applied_before_curing_rejected(self, api):
        """PRD §3.8: "the crew lead marks it applied (`APPROVED → APPLIED`,
        requiring execution to be in `CURING` or `COMPLETED`, else
        `ERR_WORK_ORDER_NOT_FINISHABLE`)".

        Design: Corner/state_machines/striping_mark_applied_before_curing_rejected
        """
        ctx = setup_accepted_job(
            **COMMERCIAL_2000,
            quote_overrides={**STRIPING_SCOPE, "stripe_linear_ft": 490},
        )
        wo_id = ctx["work_order"]["id"]
        validate_success(api.plan_striping(wo_id, {"stall_count": 25}, ESTIMATOR))
        approved = validate_success(api.approve_striping(wo_id, ESTIMATOR))
        assert approved["striping_status"] == "APPROVED"
        assert approved["execution_status"] == "PENDING"

        lot = create_material_lot(ctx["material"]["id"], delivered_gallons=200)
        crew = create_crew()
        sheet = create_route_sheet(crew["id"], "2026-08-10")
        post_weather_snapshot("2026-08-10")
        schedule_work_order(wo_id, sheet["id"], lot["id"], "2026-08-10")

        resp = api.mark_striping_applied(wo_id, CREW_LEAD)
        validate_error(resp, ApiErrorId.ERR_WORK_ORDER_NOT_FINISHABLE, 409)
        after = get_work_order(wo_id)
        assert after["execution_status"] == "SCHEDULED"
        assert after["striping_status"] == "APPROVED"


class TestStripingRoleDenial:
    def test_crew_lead_cannot_approve_striping(self, api):
        """PRD §2.1: "A request whose role is recognized but not permitted for
        the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)." PRD
        §4: `POST /api/work-orders/{workOrderId}/striping/approve` is
        authorized for Estimator only.

        Design: Corner/rbac/rbac_crewlead_cannot_approve_striping
        """
        ctx = setup_accepted_job(
            **COMMERCIAL_2000,
            quote_overrides={**STRIPING_SCOPE, "stripe_linear_ft": 490},
        )
        wo_id = ctx["work_order"]["id"]
        planned = validate_success(api.plan_striping(wo_id, {"stall_count": 25}, ESTIMATOR))
        assert planned["striping_status"] == "PLANNED"

        resp = api.approve_striping(wo_id, CREW_LEAD)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)
        after = get_work_order(wo_id)
        assert after["striping_status"] == "PLANNED"
