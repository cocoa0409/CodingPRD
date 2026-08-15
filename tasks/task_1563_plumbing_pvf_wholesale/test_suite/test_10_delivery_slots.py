"""Truck delivery windows: overlap rule, cube capacity, booking OCC (PRD §2.8, §2.11, §3.9)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    book_order,
    create_delivery_slot_payload,
    create_submitted_order,
    make_account,
    make_branch,
    make_product,
    make_slot,
    make_stock,
    setup_branch_product_account,
    validate_error,
    validate_success,
)

MANAGER = TEST_USERS["manager_headers"]
REP = TEST_USERS["counterrep_headers"]
SALES = TEST_USERS["sales_headers"]


class TestTruckWindowOverlap:
    def test_adjacent_windows_allowed_intersection_rejected(self, api, manager_headers):
        """PRD §2.11: "On the same branch and the same `truck_label`, the
        half-open window intervals of slots — from `window_start` up to but not
        including `window_end` — may not intersect, though two windows that
        merely touch end-to-start are allowed; a colliding definition is
        rejected with `ERR_SLOT_OVERLAP`."

        [08:00,12:00) then [12:00,16:00) on T1 touch end-to-start (allowed);
        [11:00,13:00) intersects both (rejected).

        Design: Difficulty/resource_temporal_overlap/truck_slot_half_open_adjacency
        """
        branch = make_branch()
        make_slot(branch["id"], window_start="2026-08-02T08:00:00Z",
                  window_end="2026-08-02T12:00:00Z", capacity_cubes=100)

        adjacent = api.create_delivery_slot(
            branch["id"],
            create_delivery_slot_payload(window_start="2026-08-02T12:00:00Z",
                                         window_end="2026-08-02T16:00:00Z",
                                         capacity_cubes=100),
            manager_headers,
        )
        validate_success(adjacent, 201)

        colliding = api.create_delivery_slot(
            branch["id"],
            create_delivery_slot_payload(window_start="2026-08-02T11:00:00Z",
                                         window_end="2026-08-02T13:00:00Z",
                                         capacity_cubes=50),
            manager_headers,
        )
        validate_error(colliding, ApiErrorId.ERR_SLOT_OVERLAP)

    def test_same_window_on_different_truck_allowed(self, api, manager_headers):
        """PRD §2.11: "On the same branch and the same `truck_label`, the half-open window intervals of slots — from `window_start` up to but not including `window_end` — may not intersect, though two windows that merely touch end-to-start are allowed; a colliding definition is rejected with `ERR_SLOT_OVERLAP`." The rule is scoped per (branch, truck), so a different truck may hold the identical window.

        Design: Difficulty/resource_temporal_overlap/truck_slot_half_open_adjacency
        """
        branch = make_branch()
        make_slot(branch["id"], truck_label="T1", window_start="2026-08-02T08:00:00Z",
                  window_end="2026-08-02T12:00:00Z", capacity_cubes=100)
        other_truck = api.create_delivery_slot(
            branch["id"],
            create_delivery_slot_payload(truck_label="T2",
                                         window_start="2026-08-02T08:00:00Z",
                                         window_end="2026-08-02T12:00:00Z",
                                         capacity_cubes=100),
            manager_headers,
        )
        validate_success(other_truck, 201)


class TestSlotCapacity:
    def _setup_three_orders(self):
        """Slot capacity 100; orders A (x6 = 60 cubes), B (x4 = 40), C (x1 = 10)."""
        branch, product, account = setup_branch_product_account(
            stock=30, account_overrides={"credit_limit_cents": 100000000}
        )
        slot = make_slot(branch["id"], capacity_cubes=100)
        order_a, _ = create_submitted_order(account["id"], branch["id"], [(product["id"], 6)])
        order_b, _ = create_submitted_order(account["id"], branch["id"], [(product["id"], 4)])
        order_c, _ = create_submitted_order(account["id"], branch["id"], [(product["id"], 1)])
        return branch, account, slot, order_a, order_b, order_c

    def test_booking_at_exact_capacity_accepted_and_flips_full(self, api, sales_headers):
        """PRD §2.11: "A booking is allowed while the slot's `booked_cubes` plus
        the order's `cubes_total` stays less than or equal to `capacity_cubes`;
        a booking that lands exactly on capacity is accepted, and it is equality
        that flips the slot from `OPEN` to `FULL`."

        60 + 40 == 100: order B's booking succeeds at exact equality and the
        slot reads FULL with booked_cubes 100.

        Design: Difficulty/boundary_precision_check/slot_capacity_equality_books_then_full
        """
        _, _, slot, order_a, order_b, _ = self._setup_three_orders()
        book_order(order_a, slot["id"])
        booked_b = book_order(order_b, slot["id"])
        assert booked_b["delivery_slot_id"] == slot["id"]

        slot_after = validate_success(api.get_slot(slot["id"], sales_headers))
        assert slot_after["booked_cubes"] == 100
        assert slot_after["status"] == "FULL", (
            f"equality must flip the slot FULL, got {slot_after['status']}"
        )

    def test_one_cube_over_capacity_rejected(self, api):
        """PRD §2.11: "A booking is allowed while the slot's `booked_cubes` plus
        the order's `cubes_total` stays less than or equal to `capacity_cubes`"
        — a booking that would strictly exceed capacity is rejected
        (`ERR_SLOT_FULL`, PRD §3.9: "And the slot must have room for the order's
        `cubes_total` under the equality-allowed capacity rule of §2.11, else
        `ERR_SLOT_FULL`").

        With the slot FULL at 100, order C's +10 cubes overflow.

        Design: Difficulty/boundary_precision_check/slot_capacity_equality_books_then_full
        """
        _, _, slot, order_a, order_b, order_c = self._setup_three_orders()
        book_order(order_a, slot["id"])
        book_order(order_b, slot["id"])

        res = api.book_delivery(
            order_c["id"],
            {"slot_id": slot["id"], "expected_order_version": order_c["version"]},
            REP,
        )
        validate_error(res, ApiErrorId.ERR_SLOT_FULL)


class TestBookingLifecycle:
    def _setup_two_orders(self):
        """Slot capacity 100; orders A (60 cubes) and B (40 cubes)."""
        branch, product, account = setup_branch_product_account(
            stock=30, account_overrides={"credit_limit_cents": 100000000}
        )
        slot = make_slot(branch["id"], capacity_cubes=100)
        order_a, _ = create_submitted_order(account["id"], branch["id"], [(product["id"], 6)])
        order_b, _ = create_submitted_order(account["id"], branch["id"], [(product["id"], 4)])
        return branch, account, slot, order_a, order_b

    def test_booking_to_full(self, api, sales_headers):
        """PRD §2.11: "its `booked_cubes` is the sum of `cubes_total` over
        orders holding an active booking in that slot — orders whose
        `fulfillment_status` is not `CANCELLED`" and "it is equality that flips
        the slot from `OPEN` to `FULL`".

        Design: Difficulty/compensating_invariant/book_cancel_conserves_slot_capacity
        """
        _, _, slot, order_a, order_b = self._setup_two_orders()
        book_order(order_a, slot["id"])
        book_order(order_b, slot["id"])
        slot_after = validate_success(api.get_slot(slot["id"], sales_headers))
        assert slot_after["booked_cubes"] == 100, "60 + 40 must fill the slot exactly"
        assert slot_after["status"] == "FULL"

    def test_cancel_booking_releases_cubes_and_reverts_full(self, api, sales_headers):
        """PRD §3.9: "Cancelling the booking releases the cube load, recomputes
        a `FULL` slot back to `OPEN`, clears `delivery_slot_id` to null, and
        increments the order's `version`."
        PRD §2.11: "When a booking is later released and the load drops below
        capacity, the slot flips back from `FULL` to `OPEN` automatically."

        Cancelling order A's booking conserves capacity: booked_cubes returns
        to B's 40 and the slot reopens.

        Design: Difficulty/compensating_invariant/book_cancel_conserves_slot_capacity
        """
        _, _, slot, order_a, order_b = self._setup_two_orders()
        book_order(order_a, slot["id"])
        book_order(order_b, slot["id"])

        cancelled = validate_success(api.cancel_booking(order_a["id"], REP))
        assert cancelled["delivery_slot_id"] is None

        slot_after = validate_success(api.get_slot(slot["id"], sales_headers))
        assert slot_after["booked_cubes"] == 40, (
            f"only order B's 40 cubes may remain, got {slot_after['booked_cubes']}"
        )
        assert slot_after["status"] == "OPEN", "dropping below capacity must revert FULL to OPEN"

    def test_occ_stale_booking_rejected(self, api, sales_headers):
        """PRD §2.8: "Booking an order into a delivery slot requires
        `expected_order_version` matching the order's current `version`. A
        mismatch is rejected with `ERR_STALE_ORDER_VERSION` (HTTP 412), because
        intervening mutations — line reservation at submit, allocation cascades,
        a prior booking — change both the order's cube load and its version, and
        a stale expectation must not silently double-book or book the wrong
        load."

        The submit advanced the order's version, so the pre-submit version is
        stale; the rejection books nothing, and the current version succeeds.

        Design: Corner/cross_cutting_layers/occ_stale_booking_rejected
        """
        branch, product, account = setup_branch_product_account(stock=5)
        slot = make_slot(branch["id"], capacity_cubes=100)
        order, _ = create_submitted_order(account["id"], branch["id"], [(product["id"], 1)])

        res = api.book_delivery(
            order["id"],
            {"slot_id": slot["id"], "expected_order_version": order["version"] - 1},
            REP,
        )
        validate_error(res, ApiErrorId.ERR_STALE_ORDER_VERSION)
        slot_mid = validate_success(api.get_slot(slot["id"], sales_headers))
        assert slot_mid["booked_cubes"] == 0, "a stale booking must not load the slot"

        booked = validate_success(api.book_delivery(
            order["id"],
            {"slot_id": slot["id"], "expected_order_version": order["version"]},
            REP,
        ))
        assert booked["delivery_slot_id"] == slot["id"]
        assert booked["version"] == order["version"] + 1


class TestSlotCancellation:
    def test_slot_cancel_booked_rejected_empty_succeeds(self, api, manager_headers, sales_headers):
        """PRD §3.9: "A `BranchManager` may also cancel a slot outright, but only
        when nothing is booked — a cancellation with any active booking is
        rejected with `ERR_INVALID_STATE` — moving it to terminal `CANCELLED`
        and incrementing its `version`."

        Design: Corner/endpoints/slot_cancel_booked_rejected_empty_succeeds
        """
        branch, product, account = setup_branch_product_account(stock=5)
        empty_slot = make_slot(branch["id"], truck_label="T1")
        booked_slot = make_slot(branch["id"], truck_label="T2")
        order, _ = create_submitted_order(account["id"], branch["id"], [(product["id"], 1)])
        book_order(order, booked_slot["id"])

        cancelled = validate_success(api.cancel_slot(empty_slot["id"], manager_headers))
        assert cancelled["status"] == "CANCELLED"

        res = api.cancel_slot(booked_slot["id"], manager_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
        after = validate_success(api.get_slot(booked_slot["id"], sales_headers))
        assert after["status"] == "OPEN"
