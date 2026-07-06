"""Scheduling windows and the delivery return loop: half-open station fill-window
overlap, the delivery-return deposit refund cascade, and the cross-entity
dispatch readiness guard.

All Difficulty-queue instances.
"""
from test_helpers import fixtures, factories, validate_success, validate_error, ApiErrorId
from test_helpers.test_users import TEST_USERS

CLERK = TEST_USERS["store_clerk_headers"]


class TestStationWindowOverlap:
    """Station fill-windows are half-open [start, end): adjacency is permitted,
    a strict overlap is rejected."""

    def test_adjacent_station_window_accepted(self, api):
        """PRD §2.8: "Fill-windows are **half-open** intervals `[start, end)`: two
        windows on the same station conflict when they overlap on that half-open
        basis, but exact adjacency (one window's start equal to another's end) is
        permitted."

        Design: Difficulty/resource_temporal_overlap/station_window_halfopen_adjacency_ok_overlap_rejected
        """
        member = fixtures.create_member(api)
        station = fixtures.create_station(api)
        fixtures.create_order(api, member_id=member["id"], station_id=station["id"],
                              fill_window_start_at="2026-03-02T09:00:00Z",
                              fill_window_end_at="2026-03-02T10:00:00Z")
        # Window B starts exactly at A's end -> adjacent, allowed.
        payload = factories.create_order_payload(
            member["id"], station["id"],
            "2026-03-02T10:00:00Z", "2026-03-02T11:00:00Z")
        validate_success(api.create_order(payload, CLERK), 201)

    def test_overlapping_station_window_rejected(self, api):
        """PRD §2.8: "A new order whose window overlaps another non-cancelled
        order's window on the same station is rejected with
        `ERR_STATION_SESSION_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/station_window_halfopen_adjacency_ok_overlap_rejected
        """
        member = fixtures.create_member(api)
        station = fixtures.create_station(api)
        fixtures.create_order(api, member_id=member["id"], station_id=station["id"],
                              fill_window_start_at="2026-03-02T09:00:00Z",
                              fill_window_end_at="2026-03-02T10:00:00Z")
        # Window C strictly overlaps [09:00, 10:00).
        payload = factories.create_order_payload(
            member["id"], station["id"],
            "2026-03-02T09:30:00Z", "2026-03-02T10:30:00Z")
        resp = api.create_order(payload, CLERK)
        validate_error(resp, ApiErrorId.ERR_STATION_SESSION_OVERLAP.value)


class TestDeliveryReturnRefundsDeposit:
    """Receiving the return on a DELIVERED delivery returns the order's IN_USE
    containers and refunds each deposit to the member's wallet."""

    def test_return_received_returns_container_and_delivery(self, api):
        """PRD §3.7: "**Receiving the return** on a `DELIVERED` delivery moves it
        `DELIVERED → RETURNED`, closing the container loop: every `IN_USE`
        container on the delivery's order is moved `IN_USE → RETURNED`".

        Design: Difficulty/transitive_cascade/delivery_return_refunds_deposit_to_wallet
        """
        s = fixtures.setup_delivered_order(api)
        delivery = validate_success(api.return_received_delivery(s["delivery"]["id"], CLERK), 200)
        assert delivery["status"] == "RETURNED"
        container = validate_success(api.get_container(s["container"]["id"], CLERK), 200)
        assert container["status"] == "RETURNED"

    def test_return_received_refunds_deposit_to_wallet(self, api):
        """PRD §3.7: "for each such container a `DEPOSIT_REFUND` ledger entry is
        appended adding the deposit to `wallet_delta_cents` and subtracting it
        from `liability_delta_cents`, which in turn shifts the member's
        `wallet_balance_cents` and `deposit_liability_cents` projections."

        Design: Difficulty/transitive_cascade/delivery_return_refunds_deposit_to_wallet
        """
        s = fixtures.setup_delivered_order(api)  # GLASS_500, deposit 150 committed
        validate_success(api.return_received_delivery(s["delivery"]["id"], CLERK), 200)
        member = validate_success(api.get_member(s["member"]["id"], CLERK), 200)
        assert member["wallet_balance_cents"] == 150
        assert member["deposit_liability_cents"] == 0


class TestDispatchBlockedByOrderNotReady:
    """A delivery may not dispatch until its underlying order is FILLED and
    CAPTURED."""

    @staticmethod
    def _scheduled_delivery_on_cart_order(api):
        member = fixtures.create_member(api)
        station = fixtures.create_station(api)
        order = fixtures.create_order(api, member_id=member["id"], station_id=station["id"],
                                      fulfillment_channel="DELIVERY")
        vehicle = fixtures.create_vehicle(api)
        delivery = fixtures.create_delivery(api, order_id=order["id"], vehicle_id=vehicle["id"])
        return delivery

    def test_dispatch_cart_order_rejected(self, api):
        """PRD §3.7: "**Dispatching** a `SCHEDULED` delivery moves it
        `SCHEDULED → DISPATCHED`, but only when the underlying order is both
        `FILLED` and `CAPTURED`; if the order is not yet fully filled and paid,
        dispatch is refused with `ERR_DELIVERY_ORDER_NOT_READY`."

        Design: Difficulty/cross_entity_state_dependency/dispatch_blocked_by_order_not_ready
        """
        delivery = self._scheduled_delivery_on_cart_order(api)
        resp = api.dispatch_delivery(delivery["id"], CLERK)
        validate_error(resp, ApiErrorId.ERR_DELIVERY_ORDER_NOT_READY.value)

    def test_rejected_dispatch_leaves_delivery_scheduled(self, api):
        """PRD §3.7: "**Dispatching** a `SCHEDULED` delivery moves it
        `SCHEDULED → DISPATCHED`, but only when the underlying order is both
        `FILLED` and `CAPTURED`; if the order is not yet fully filled and paid,
        dispatch is refused with `ERR_DELIVERY_ORDER_NOT_READY`."

        Design: Difficulty/cross_entity_state_dependency/dispatch_blocked_by_order_not_ready
        """
        delivery = self._scheduled_delivery_on_cart_order(api)
        api.dispatch_delivery(delivery["id"], CLERK)  # rejected
        after = validate_success(api.get_delivery(delivery["id"], CLERK), 200)
        assert after["status"] == "SCHEDULED", "a refused dispatch leaves the delivery SCHEDULED"
