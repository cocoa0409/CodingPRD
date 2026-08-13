"""Repair scheduling, dispatch, crew capacity, and the permit track gate (PRD §3.3, §3.6)."""
from test_helpers import (
    ApiErrorId,
    get_success_data,
    make_crew,
    make_leak,
    set_clock,
    setup_completed_repair,
    setup_dispatched_repair,
    setup_granted_permit,
    setup_open_leak,
    setup_repair_order,
    validate_error,
    validate_success,
)
from test_helpers.factories import create_leak_payload, create_schedule_repair_payload


class TestRepairOrderCreation:
    def test_repair_order_priority_mapped_from_leak_grade(self, api):
        """PRD §3.6: "On success the leak moves `OPEN → REPAIR_SCHEDULED` and a
        `RepairOrder` is created in `PENDING_DISPATCH` with its `priority` mapped
        from the leak's grade: `G1` maps to `P1_EMERGENCY`, `G2` to `P2_URGENT`,
        `G3` to `P3_ROUTINE`. The order's `crew_id` and `dispatched_at` are null
        until dispatch."

        Design: Corner/entities/repair_order_priority_mapped_from_leak_grade
        """
        ctx = setup_repair_order(route_code="R-RO")
        order = ctx["order"]
        assert ctx["leak"]["grade"] == "G2"
        assert order["priority"] == "P2_URGENT"
        assert order["dispatch_status"] == "PENDING_DISPATCH"
        assert order["excavation_permit_status"] == "NOT_REQUIRED"
        assert order["crew_id"] is None
        assert order["dispatched_at"] is None

        leak = get_success_data(api.get_leak(ctx["leak"]["id"], ctx["dc_h"]))
        assert leak["status"] == "REPAIR_SCHEDULED"

    def test_apply_permit_when_not_required_rejected(self, api):
        """PRD §3.6: "The attempt is refused with `ERR_ORDER_NOT_PENDING_DISPATCH`
        if the order has left `PENDING_DISPATCH`, and with
        `ERR_PERMIT_NOT_REQUIRED` if the order's permit status is not
        `PERMIT_REQUIRED`."

        Design: Corner/validations/apply_permit_when_not_required_rejected
        """
        ctx = setup_repair_order(route_code="R-PNR")  # CLAMP -> NOT_REQUIRED
        resp = api.apply_permit(
            ctx["order"]["id"],
            {"permit_number": "PERMIT-NR", "jurisdiction": "CITY-NORTH",
             "expires_at": "2026-12-31T23:59:59Z"},
            ctx["co_h"],
        )
        validate_error(resp, ApiErrorId.ERR_PERMIT_NOT_REQUIRED)


class TestRepairOrderTransitions:
    def test_repair_order_dispatch_twice_rejected(self, api):
        """PRD §3.6: "the order must be `PENDING_DISPATCH`
        (`ERR_ORDER_NOT_PENDING_DISPATCH`)" — a second dispatch on an
        already-dispatched order fails and the crew's count is not incremented
        again ("increments the crew's `open_order_count` by 1" applies to "A
        successful dispatch").

        Design: Corner/state_machines/repair_order_dispatch_twice_rejected
        """
        ctx = setup_dispatched_repair(route_code="R-DT")
        crew = ctx["crew"]
        resp = api.dispatch_repair_order(ctx["order"]["id"], {"crew_id": crew["id"]}, ctx["dc_h"])
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_PENDING_DISPATCH)
        crew_after = get_success_data(api.get_repair_crew(crew["id"], ctx["dc_h"]))
        assert crew_after["open_order_count"] == 1

    def test_repair_order_arrive_from_pending_rejected(self, api):
        """PRD §3.6: "From `DISPATCHED`, the coordinator records arrival on site —
        requiring `DISPATCHED` (`ERR_ORDER_NOT_DISPATCHED`)."

        Design: Corner/state_machines/repair_order_arrive_from_pending_rejected
        """
        ctx = setup_repair_order(route_code="R-AP")
        resp = api.arrive_on_site(ctx["order"]["id"], ctx["dc_h"])
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_DISPATCHED)

    def test_repair_order_complete_from_dispatched_rejected(self, api):
        """PRD §3.6: "From `ON_SITE`, marking work complete — requiring `ON_SITE`
        (`ERR_ORDER_NOT_ON_SITE`)."

        Design: Corner/state_machines/repair_order_complete_from_dispatched_rejected
        """
        ctx = setup_dispatched_repair(route_code="R-MC")
        resp = api.mark_work_complete(ctx["order"]["id"], ctx["dc_h"])
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_ON_SITE)

    def test_repair_order_cancel_from_on_site_rejected(self, api):
        """PRD §3.6: "Cancelling is possible from `PENDING_DISPATCH` or
        `DISPATCHED` (any other dispatch state yields `ERR_ORDER_NOT_CANCELLABLE`)."

        Design: Corner/state_machines/repair_order_cancel_from_on_site_rejected
        """
        ctx = setup_dispatched_repair(route_code="R-CN")
        get_success_data(api.arrive_on_site(ctx["order"]["id"], ctx["dc_h"]))
        resp = api.cancel_repair_order(ctx["order"]["id"], ctx["dc_h"])
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_CANCELLABLE)
        leak = get_success_data(api.get_leak(ctx["leak"]["id"], ctx["dc_h"]))
        assert leak["status"] == "UNDER_REPAIR"


class TestCrewDispatchRules:
    def test_dispatch_to_off_duty_crew_rejected(self, api):
        """PRD §3.6: "the target crew must not be `OFF_DUTY` (`ERR_CREW_OFF_DUTY`)."

        Design: Corner/validations/dispatch_to_off_duty_crew_rejected
        """
        ctx = setup_repair_order(route_code="R-OD")
        crew = make_crew(ctx, crew_code="CR-OD")
        get_success_data(api.set_crew_off_duty(crew["id"], ctx["dc_h"]))
        resp = api.dispatch_repair_order(ctx["order"]["id"], {"crew_id": crew["id"]}, ctx["dc_h"])
        validate_error(resp, ApiErrorId.ERR_CREW_OFF_DUTY)

    def test_dispatch_cut_and_replace_to_unqualified_crew(self, api):
        """PRD §3.6: "for the two excavation methods the crew's
        `is_qualified_excavation` must be true (`ERR_CREW_NOT_QUALIFIED_EXCAVATION`)."

        Design: Corner/validations/dispatch_cut_and_replace_to_unqualified_crew
        """
        ctx = setup_granted_permit(route_code="R-UQ")  # valid GRANTED permit, far-future expiry
        crew = make_crew(ctx, crew_code="CR-UQ", is_qualified_excavation=False)
        resp = api.dispatch_repair_order(ctx["order"]["id"], {"crew_id": crew["id"]}, ctx["dc_h"])
        validate_error(resp, ApiErrorId.ERR_CREW_NOT_QUALIFIED_EXCAVATION)

    def test_repair_crew_off_duty_blocked_at_capacity(self, api):
        """PRD §3.3: "`AT_CAPACITY` when `open_order_count` reaches
        `max_concurrent_orders`" and "from `AT_CAPACITY` the move is allowed only
        when the crew has no open repair orders, else `ERR_CREW_HAS_OPEN_ORDERS`."

        Design: Corner/state_machines/repair_crew_off_duty_blocked_at_capacity
        """
        ctx = setup_dispatched_repair(
            route_code="R-OC",
            crew_overrides={"crew_code": "CR-OC", "max_concurrent_orders": 1},
        )
        crew = get_success_data(api.get_repair_crew(ctx["crew"]["id"], ctx["dc_h"]))
        assert crew["status"] == "AT_CAPACITY"
        resp = api.set_crew_off_duty(crew["id"], ctx["dc_h"])
        validate_error(resp, ApiErrorId.ERR_CREW_HAS_OPEN_ORDERS)

    def test_crew_selector_prefers_region_match(self, api):
        """PRD §3.6: "the score is 0.7 times one minus the utilization ratio, plus
        0.3 times one if the crew's `home_region` equals the segment's
        `region_hint`" and "Candidates sort by score descending" — with both crews
        at zero utilization the region match decides.

        Design: Corner/calculations/crew_selector_prefers_region_match
        """
        ctx = setup_repair_order(
            route_code="R-SEL",
            segment_overrides={"segment_code": "SEG-SEL", "region_hint": "NORTH"},
        )
        make_crew(ctx, crew_code="CR-S", home_region="SOUTH", max_concurrent_orders=4)
        north = make_crew(ctx, crew_code="CR-N", home_region="NORTH", max_concurrent_orders=4)
        data = validate_success(api.dispatch_repair_order(ctx["order"]["id"], {}, ctx["dc_h"]))
        assert data["crew_id"] == north["id"]

    def test_crew_at_capacity_boundary_exact_max(self, api):
        """PRD §3.6: "the crew's `open_order_count` must be strictly below its
        `max_concurrent_orders` (`ERR_CREW_AT_CAPACITY`)" — at 0 and 1 of a
        capacity-2 crew dispatch succeeds; at exactly 2 the third fails.

        Design: Difficulty/boundary_precision_check/crew_at_capacity_boundary_exact_max
        """
        ctx = setup_open_leak(route_code="R-BND")
        segment, run = ctx["segments"][0], ctx["run"]
        leak2 = make_leak(ctx, segment["id"], run["id"], concentration_ppm=13000.0)
        leak3 = make_leak(ctx, segment["id"], run["id"], concentration_ppm=14000.0)
        orders = []
        for leak in (ctx["leak"], leak2, leak3):
            orders.append(get_success_data(api.schedule_repair(
                leak["id"],
                create_schedule_repair_payload(leak["version"]),
                ctx["dc_h"],
            )))
        crew = make_crew(ctx, crew_code="CR-BND", max_concurrent_orders=2)

        validate_success(api.dispatch_repair_order(orders[0]["id"], {"crew_id": crew["id"]}, ctx["dc_h"]))
        validate_success(api.dispatch_repair_order(orders[1]["id"], {"crew_id": crew["id"]}, ctx["dc_h"]))
        resp = api.dispatch_repair_order(orders[2]["id"], {"crew_id": crew["id"]}, ctx["dc_h"])
        validate_error(resp, ApiErrorId.ERR_CREW_AT_CAPACITY)

    def test_crew_recovers_to_available_below_max(self, api):
        """PRD §3.3: "back to `AVAILABLE` when it falls below" — after work
        completes on one of two held orders, the capacity-2 crew is eligible
        again and accepts a further dispatch.

        Design: Difficulty/boundary_precision_check/crew_at_capacity_boundary_exact_max
        """
        ctx = setup_open_leak(route_code="R-BND2")
        segment, run = ctx["segments"][0], ctx["run"]
        leak2 = make_leak(ctx, segment["id"], run["id"], concentration_ppm=13000.0)
        leak3 = make_leak(ctx, segment["id"], run["id"], concentration_ppm=14000.0)
        orders = []
        for leak in (ctx["leak"], leak2, leak3):
            orders.append(get_success_data(api.schedule_repair(
                leak["id"],
                create_schedule_repair_payload(leak["version"]),
                ctx["dc_h"],
            )))
        crew = make_crew(ctx, crew_code="CR-BND2", max_concurrent_orders=2)
        validate_success(api.dispatch_repair_order(orders[0]["id"], {"crew_id": crew["id"]}, ctx["dc_h"]))
        validate_success(api.dispatch_repair_order(orders[1]["id"], {"crew_id": crew["id"]}, ctx["dc_h"]))
        crew_full = get_success_data(api.get_repair_crew(crew["id"], ctx["dc_h"]))
        assert crew_full["status"] == "AT_CAPACITY"

        get_success_data(api.arrive_on_site(orders[0]["id"], ctx["dc_h"]))
        get_success_data(api.mark_work_complete(orders[0]["id"], ctx["dc_h"]))
        crew_after = get_success_data(api.get_repair_crew(crew["id"], ctx["dc_h"]))
        assert crew_after["open_order_count"] == 1
        assert crew_after["status"] == "AVAILABLE"
        validate_success(api.dispatch_repair_order(orders[2]["id"], {"crew_id": crew["id"]}, ctx["dc_h"]))


class TestPermitGatedDispatch:
    def test_temporal_permit_check_beats_capacity_constraint(self, api):
        """PRD §2.5: "then business-temporal checks (scheduled windows, filing
        deadlines, permit validity), then business-constraint checks (crew
        capacity, crew qualification, coverage minimums, regrade limits)" — with
        the permit expired AND the crew at capacity, the temporal violation
        `ERR_NO_VALID_EXCAVATION_PERMIT` is reported.

        Design: Difficulty/priority_pair_validation_conflict/temporal_vs_constraint_on_repair_dispatch
        """
        ctx = setup_granted_permit(expires_at="2026-08-05T00:00:00Z", route_code="R-PR2")
        crew = make_crew(ctx, crew_code="CR-PR2", is_qualified_excavation=True,
                         max_concurrent_orders=1)
        # Fill the crew's single slot with an unrelated CLAMP order.
        leak_b = make_leak(ctx, ctx["segments"][0]["id"], ctx["run"]["id"],
                           concentration_ppm=25000.0)
        order_b = get_success_data(api.schedule_repair(
            leak_b["id"], create_schedule_repair_payload(leak_b["version"]), ctx["dc_h"],
        ))
        get_success_data(api.dispatch_repair_order(order_b["id"], {"crew_id": crew["id"]}, ctx["dc_h"]))

        set_clock(ctx, "2026-08-10T00:00:00Z")  # permit for the excavation order expired
        resp = api.dispatch_repair_order(ctx["order"]["id"], {"crew_id": crew["id"]}, ctx["dc_h"])
        validate_error(resp, ApiErrorId.ERR_NO_VALID_EXCAVATION_PERMIT)

    def test_capacity_constraint_fires_when_permit_valid(self, api):
        """PRD §3.6: "the crew's `open_order_count` must be strictly below its
        `max_concurrent_orders` (`ERR_CREW_AT_CAPACITY`)" — isolated here with a
        valid permit so only the capacity constraint can fire.

        Design: Difficulty/priority_pair_validation_conflict/temporal_vs_constraint_on_repair_dispatch
        """
        ctx = setup_granted_permit(expires_at="2026-12-31T23:59:59Z", route_code="R-PR3")
        crew = make_crew(ctx, crew_code="CR-PR3", is_qualified_excavation=True,
                         max_concurrent_orders=1)
        leak_b = make_leak(ctx, ctx["segments"][0]["id"], ctx["run"]["id"],
                           concentration_ppm=25000.0)
        order_b = get_success_data(api.schedule_repair(
            leak_b["id"], create_schedule_repair_payload(leak_b["version"]), ctx["dc_h"],
        ))
        get_success_data(api.dispatch_repair_order(order_b["id"], {"crew_id": crew["id"]}, ctx["dc_h"]))
        resp = api.dispatch_repair_order(ctx["order"]["id"], {"crew_id": crew["id"]}, ctx["dc_h"])
        validate_error(resp, ApiErrorId.ERR_CREW_AT_CAPACITY)


class TestCancelCompensation:
    def test_dispatch_then_cancel_restores_crew_count(self, api):
        """PRD §3.6: "A successful dispatch sets the order's `crew_id` and
        `dispatched_at`, increments the crew's `open_order_count` by 1" and "if
        the order had been dispatched, the crew's `open_order_count` decrements
        and crew status recomputes, and in both cases the leak reverts from
        `REPAIR_SCHEDULED` to `OPEN` as a compensating action."

        Design: Difficulty/compensating_invariant/crew_open_order_count_invariant_on_cancel
        """
        ctx = setup_repair_order(route_code="R-INV")
        crew = make_crew(ctx, crew_code="CR-INV")
        before = get_success_data(api.get_repair_crew(crew["id"], ctx["dc_h"]))
        assert before["open_order_count"] == 0

        get_success_data(api.dispatch_repair_order(ctx["order"]["id"], {"crew_id": crew["id"]}, ctx["dc_h"]))
        after_dispatch = get_success_data(api.get_repair_crew(crew["id"], ctx["dc_h"]))
        assert after_dispatch["open_order_count"] == 1

        get_success_data(api.cancel_repair_order(ctx["order"]["id"], ctx["dc_h"]))
        after_cancel = get_success_data(api.get_repair_crew(crew["id"], ctx["dc_h"]))
        assert after_cancel["open_order_count"] == 0
        leak = get_success_data(api.get_leak(ctx["leak"]["id"], ctx["dc_h"]))
        assert leak["status"] == "OPEN"

    def test_cancel_from_pending_dispatch_leaves_count_untouched(self, api):
        """PRD §3.6: "if the order had been dispatched, the crew's
        `open_order_count` decrements" — a `PENDING_DISPATCH` order was never
        dispatched, so no decrement applies, while "in both cases the leak reverts
        from `REPAIR_SCHEDULED` to `OPEN`."

        Design: Difficulty/compensating_invariant/crew_open_order_count_invariant_on_cancel
        """
        ctx = setup_repair_order(route_code="R-INV2")
        crew = make_crew(ctx, crew_code="CR-INV2")
        data = validate_success(api.cancel_repair_order(ctx["order"]["id"], ctx["dc_h"]))
        assert data["dispatch_status"] == "CANCELLED"
        crew_after = get_success_data(api.get_repair_crew(crew["id"], ctx["dc_h"]))
        assert crew_after["open_order_count"] == 0
        leak = get_success_data(api.get_leak(ctx["leak"]["id"], ctx["dc_h"]))
        assert leak["status"] == "OPEN"
