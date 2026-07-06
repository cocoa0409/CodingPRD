"""Cross-entity state preconditions: pack-vs-account and complete-vs-route."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, setup_committed_line_with_account, make_delivery_order,
    make_route, add_stop, get_order, get_stop, TEST_USERS,
)

MANAGER = TEST_USERS["manager_headers"]
DRIVER = TEST_USERS["driver_headers"]


class TestPackRequiresAccountActive:
    def test_pack_blocked_when_account_suspended(self, api):
        """PRD 3.7: "a Manager packs a PENDING order to PACKED, but only if the order's
        account is ACTIVE — a SUSPENDED or CLOSED account blocks packing with
        ERR_ACCOUNT_SUSPENDED."

        Design: Difficulty/cross_entity_state_dependency/pack_requires_account_active
        """
        ctx = setup_committed_line_with_account(api, par_qty=10,
                                                production_date="2026-06-06T00:00:00Z")
        order = make_delivery_order(api, ctx["account"]["id"], ctx["product"]["id"],
                                    ctx["line"]["id"], qty=2,
                                    delivery_date="2026-06-06T10:00:00Z")
        validate_success(api.suspend_account(ctx["account"]["id"], MANAGER))
        validate_error(api.pack_delivery_order(order["id"], MANAGER),
                       ApiErrorId.ERR_ACCOUNT_SUSPENDED.value)
        assert get_order(api, order["id"])["fulfillment_status"] == "PENDING"

    def test_pack_succeeds_when_account_active(self, api):
        """PRD 3.7: "a Manager packs a PENDING order to PACKED, but only if the order's
        account is ACTIVE".

        Design: Difficulty/cross_entity_state_dependency/pack_requires_account_active
        """
        ctx = setup_committed_line_with_account(api, par_qty=10,
                                                production_date="2026-06-06T00:00:00Z")
        order = make_delivery_order(api, ctx["account"]["id"], ctx["product"]["id"],
                                    ctx["line"]["id"], qty=2,
                                    delivery_date="2026-06-06T10:00:00Z")
        packed = validate_success(api.pack_delivery_order(order["id"], MANAGER))
        assert packed["fulfillment_status"] == "PACKED", packed


class TestCompleteStopRequiresRouteDispatched:
    def _packed_order_with_stop(self, api):
        ctx = setup_committed_line_with_account(api, par_qty=10,
                                                production_date="2026-06-12T00:00:00Z")
        order = make_delivery_order(api, ctx["account"]["id"], ctx["product"]["id"],
                                    ctx["line"]["id"], qty=2,
                                    delivery_date="2026-06-12T10:00:00Z")
        validate_success(api.pack_delivery_order(order["id"], MANAGER))
        route = make_route(api, route_date="2026-06-12T00:00:00Z", driver_name="Eve",
                           window_start="2026-06-12T06:00:00Z", window_end="2026-06-12T14:00:00Z")
        stop = add_stop(api, route["id"], order["id"], sequence=1,
                        arrival_window_start="2026-06-12T08:00:00Z",
                        arrival_window_end="2026-06-12T09:00:00Z")
        return route, stop

    def test_complete_blocked_when_route_not_dispatched(self, api):
        """PRD 3.8: "completing a PENDING stop requires its route to be DISPATCHED —
        otherwise ERR_ROUTE_NOT_DISPATCHED".

        Design: Difficulty/cross_entity_state_dependency/complete_stop_requires_route_dispatched
        """
        route, stop = self._packed_order_with_stop(api)
        validate_error(api.complete_route_stop(stop["id"], DRIVER),
                       ApiErrorId.ERR_ROUTE_NOT_DISPATCHED.value)
        assert get_stop(api, stop["id"])["status"] == "PENDING"

    def test_complete_succeeds_after_dispatch(self, api):
        """PRD 3.8: "completing a PENDING stop requires its route to be DISPATCHED ... and
        sets the stop to DELIVERED".

        Design: Difficulty/cross_entity_state_dependency/complete_stop_requires_route_dispatched
        """
        route, stop = self._packed_order_with_stop(api)
        validate_success(api.dispatch_route(route["id"], MANAGER))
        completed = validate_success(api.complete_route_stop(stop["id"], DRIVER))
        assert completed["status"] == "DELIVERED", completed
