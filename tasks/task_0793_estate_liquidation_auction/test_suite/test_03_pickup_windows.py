"""Pickup windows: parallel order dimensions, capacity boundary, half-open vs
closed overlap semantics, booked_count conservation, estate mismatch, and the
existence-vs-state precedence on scheduling.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, NON_EXISTENT_UUID,
    operator_headers, make_buyer_headers, create_pickup_window_payload,
    new_estate, new_pickup_window, get_order,
    setup_scheduled_pickup, setup_capacity_one_window,
    setup_estate_with_abutting_windows, setup_buyer_holds_abutting_window,
    setup_closed_with_order, setup_paid_order,
)

OP = operator_headers()


# ==========================================================================
# Order carries two independent dimensions: payment_status x pickup_status
# ==========================================================================
class TestParallelOrderDimensions:
    def test_cancel_pickup_leaves_payment_paid(self, api):
        """PRD §3.6: "A buyer may release a booked slot, moving the order
        SCHEDULED → PENDING; this owner-only action requires the order's
        pickup_status to be SCHEDULED, decrements the window's booked_count by
        one, and clears the order's pickup_window_id back to null."

        Design: Difficulty/non_linear_state_machine/order_parallel_payment_and_pickup_dimensions
        """
        s = setup_scheduled_pickup(api, capacity=5)
        validate_success(api.cancel_pickup(s["order"]["id"],
                                          make_buyer_headers(s["buyer"]["id"])))
        order = get_order(api, s["order"]["id"])
        assert order["payment_status"] == "PAID"  # untouched by the pickup move

    def test_cancel_pickup_returns_to_pending(self, api):
        """PRD §3.6: "A buyer may release a booked slot, moving the order
        SCHEDULED → PENDING; this owner-only action requires the order's
        pickup_status to be SCHEDULED, decrements the window's booked_count by
        one, and clears the order's pickup_window_id back to null."

        Design: Difficulty/non_linear_state_machine/order_parallel_payment_and_pickup_dimensions
        """
        s = setup_scheduled_pickup(api, capacity=5)
        validate_success(api.cancel_pickup(s["order"]["id"],
                                          make_buyer_headers(s["buyer"]["id"])))
        order = get_order(api, s["order"]["id"])
        assert order["pickup_status"] == "PENDING"
        assert order["pickup_window_id"] is None


# ==========================================================================
# booked_count conserved: schedule (+1) then cancel (-1)
# ==========================================================================
class TestBookedCountConserved:
    def test_schedule_increments_booked_count(self, api):
        """PRD §3.6: "On success the order's pickup_window_id is set and the
        window's booked_count rises by one."

        Design: Difficulty/compensating_invariant/window_booked_count_conserved_across_cancel
        """
        s = setup_scheduled_pickup(api, capacity=5)
        window = validate_success(api.list_estate_pickup_windows(s["estate"]["id"], OP))[0]
        assert window["booked_count"] == 1

    def test_cancel_decrements_booked_count(self, api):
        """PRD §3.6: "this owner-only action requires the order's pickup_status
        to be SCHEDULED, decrements the window's booked_count by one, and clears
        the order's pickup_window_id back to null."

        Design: Difficulty/compensating_invariant/window_booked_count_conserved_across_cancel
        """
        s = setup_scheduled_pickup(api, capacity=5)
        validate_success(api.cancel_pickup(s["order"]["id"],
                                          make_buyer_headers(s["buyer"]["id"])))
        window = validate_success(api.list_estate_pickup_windows(s["estate"]["id"], OP))[0]
        assert window["booked_count"] == 0
        order = get_order(api, s["order"]["id"])
        assert order["pickup_window_id"] is None


# ==========================================================================
# Capacity boundary: booked_count < capacity (1 not < 1 -> full)
# ==========================================================================
class TestWindowCapacityBoundary:
    def test_booking_full_window_rejected(self, api):
        """PRD §3.6: "Finally the window must have room, meaning its booked_count
        is below its capacity, or the booking is rejected with ERR_WINDOW_FULL
        (409)."

        Design: Difficulty/boundary_precision_check/pickup_window_capacity_boundary
        """
        s = setup_capacity_one_window(api)  # capacity 1, o1 already booked
        resp = api.schedule_pickup(s["o2"]["id"], {"pickup_window_id": s["window"]["id"]},
                                   make_buyer_headers(s["b2"]["id"]))
        validate_error(resp, ApiErrorId.ERR_WINDOW_FULL.value)

    def test_full_window_booking_leaves_state_unchanged(self, api):
        """PRD §3.6: "Finally the window must have room, meaning its booked_count
        is below its capacity, or the booking is rejected with ERR_WINDOW_FULL
        (409)."

        Design: Difficulty/boundary_precision_check/pickup_window_capacity_boundary
        """
        s = setup_capacity_one_window(api)
        api.schedule_pickup(s["o2"]["id"], {"pickup_window_id": s["window"]["id"]},
                            make_buyer_headers(s["b2"]["id"]))
        window = validate_success(api.list_estate_pickup_windows(s["estate"]["id"], OP))[0]
        assert window["booked_count"] == 1
        order = get_order(api, s["o2"]["id"])
        assert order["pickup_status"] == "PENDING"


# ==========================================================================
# Window creation overlap: HALF-OPEN (abutting allowed)
# ==========================================================================
class TestWindowCreateHalfOpenOverlap:
    def test_overlapping_window_rejected(self, api):
        """PRD §3.6: "the new window collides with an existing window of that
        estate when the new window's start is strictly before the existing
        window's end and the existing window's start is strictly before the new
        window's end."
        PRD §3.6: "An overlap is rejected with ERR_WINDOW_OVERLAP (409)."

        Design: Difficulty/resource_temporal_overlap/pickup_window_halfopen_overlap_on_estate
        """
        s = setup_estate_with_abutting_windows(api)  # W1 [09,12), W2 [12,15)
        # New [11,13) overlaps W1 [09,12): 11 < 12 and 09 < 13.
        resp = api.create_pickup_window(
            create_pickup_window_payload(s["estate"]["id"], "2026-03-25T11:00:00Z",
                                         "2026-03-25T13:00:00Z", 3), OP)
        validate_error(resp, ApiErrorId.ERR_WINDOW_OVERLAP.value)

    def test_abutting_window_allowed(self, api):
        """PRD §3.6: "Windows that merely abut — where one's start equals the
        other's end — do not overlap and are allowed."

        Design: Difficulty/resource_temporal_overlap/pickup_window_halfopen_overlap_on_estate
        """
        s = setup_estate_with_abutting_windows(api)  # W2 ends at 15:00
        # New [15,18) abuts W2 [12,15): start 15 == W2 end 15 -> allowed.
        resp = api.create_pickup_window(
            create_pickup_window_payload(s["estate"]["id"], "2026-03-25T15:00:00Z",
                                         "2026-03-25T18:00:00Z", 3), OP)
        data = validate_success(resp, 201)
        assert data["booked_count"] == 0


# ==========================================================================
# Buyer scheduling overlap: CLOSED interval (abutting collides)
# ==========================================================================
class TestBuyerScheduleClosedOverlap:
    def test_abutting_window_collides_for_buyer(self, api):
        """PRD §3.6: "a collision exists when the chosen window's start is less
        than or equal to the other window's end and the other window's start is
        less than or equal to the chosen window's end. Unlike window creation,
        abutting windows — where the chosen window's start equals another's end —
        do collide here, because a buyer cannot be in two places back-to-back;
        such a collision is rejected with ERR_PICKUP_OVERLAP (409)."

        Design: Difficulty/resource_temporal_overlap/buyer_closed_interval_pickup_overlap
        """
        s = setup_buyer_holds_abutting_window(api)  # holds Wa [09,12]; books Wb [12,15]
        resp = api.schedule_pickup(s["ob"]["id"], {"pickup_window_id": s["wb"]["id"]},
                                   make_buyer_headers(s["buyer"]["id"]))
        validate_error(resp, ApiErrorId.ERR_PICKUP_OVERLAP.value)

    def test_rejected_overlap_leaves_order_pending(self, api):
        """PRD §3.6: "such a collision is rejected with ERR_PICKUP_OVERLAP (409)."
        PRD §3.6: "On success the order's pickup_window_id is set and the window's
        booked_count rises by one."

        Design: Difficulty/resource_temporal_overlap/buyer_closed_interval_pickup_overlap
        """
        s = setup_buyer_holds_abutting_window(api)
        api.schedule_pickup(s["ob"]["id"], {"pickup_window_id": s["wb"]["id"]},
                            make_buyer_headers(s["buyer"]["id"]))
        order = get_order(api, s["ob"]["id"])
        assert order["pickup_status"] == "PENDING"
        window = validate_success(api.list_estate_pickup_windows(s["eb"]["id"], OP))[0]
        assert window["booked_count"] == 0


# ==========================================================================
# Precedence: existence (4, ERR_NOT_FOUND) outranks state (7, ERR_ORDER_NOT_PAID)
# ==========================================================================
class TestSchedulePickupExistenceOutranksState:
    def test_missing_window_returns_not_found(self, api):
        """PRD §2.9: "the first identifier that does not resolve to an existing
        resource causes the request to be rejected with ERR_NOT_FOUND (HTTP 404)
        before any later reference or business rule is evaluated."

        Design: Difficulty/priority_pair_validation_conflict/schedule_pickup_existence_outranks_state
        """
        s = setup_closed_with_order(api, amount=10000)  # order UNPAID
        resp = api.schedule_pickup(s["order"]["id"],
                                   {"pickup_window_id": NON_EXISTENT_UUID},
                                   make_buyer_headers(s["buyer"]["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)

    def test_rejected_schedule_leaves_order_pending(self, api):
        """PRD §2.9: "the first identifier that does not resolve to an existing
        resource causes the request to be rejected with ERR_NOT_FOUND (HTTP 404)
        before any later reference or business rule is evaluated."

        Design: Difficulty/priority_pair_validation_conflict/schedule_pickup_existence_outranks_state
        """
        s = setup_closed_with_order(api, amount=10000)
        api.schedule_pickup(s["order"]["id"], {"pickup_window_id": NON_EXISTENT_UUID},
                            make_buyer_headers(s["buyer"]["id"]))
        order = get_order(api, s["order"]["id"])
        assert order["pickup_status"] == "PENDING"


# ==========================================================================
# Window must belong to the order's estate (corner)
# ==========================================================================
def test_schedule_pickup_window_estate_mismatch(api):
    """PRD §3.6: "The chosen window must belong to the same estate as the order
    — its estate_id must equal the order's estate_id — or the booking is
    rejected with ERR_WINDOW_ESTATE_MISMATCH (409)."

    Design: Corner/errors/schedule_pickup_window_estate_mismatch
    """
    s = setup_paid_order(api)  # order Oa in estate Ea, PAID/PENDING
    other_estate = new_estate(api, seller_name="Eb", seller_email="eb@e.com")
    wb = new_pickup_window(api, other_estate["id"], "2026-03-25T09:00:00Z",
                          "2026-03-25T12:00:00Z", 5)
    resp = api.schedule_pickup(s["order"]["id"], {"pickup_window_id": wb["id"]},
                               make_buyer_headers(s["buyer"]["id"]))
    validate_error(resp, ApiErrorId.ERR_WINDOW_ESTATE_MISMATCH.value)
