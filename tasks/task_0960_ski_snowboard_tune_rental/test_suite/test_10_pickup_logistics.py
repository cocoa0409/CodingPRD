"""Slope-side pickup: half-open window overlap, booking gates (expiry, capacity,
confirmed reservation), and the close/no-show sweep."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    make_customer,
    make_customer_headers,
    make_pickup_booking,
    make_pickup_window,
    make_reservation,
    set_clock,
    setup_confirmed_slope_side_reservation,
    validate_error,
    validate_success,
)

FD = TEST_USERS["front_desk_headers"]
MGR = TEST_USERS["manager_headers"]


class TestWindowOverlap:
    def test_adjacent_windows_allowed_strict_overlap_rejected(self, api):
        """PRD Slope-Side Pickup Logistics: "Windows are half-open intervals: the start
        instant belongs to the window, the end instant does not. Within the same
        location and date, two windows may touch — one ending exactly when another
        begins — but any strict overlap is rejected with `ERR_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/pickup_window_half_open_overlap_rule
        """
        make_pickup_window(service_date="2026-12-20", start_time="10:00",
                           end_time="12:00", location_label="CANYON", van_capacity=4)
        # Adjacency at 12:00 is allowed with zero buffer (half-open semantics).
        w2 = make_pickup_window(service_date="2026-12-20", start_time="12:00",
                                end_time="14:00", location_label="CANYON",
                                van_capacity=4)
        assert w2["id"]

        resp = api.create_pickup_window(
            {"service_date": "2026-12-20", "start_time": "11:30", "end_time": "13:00",
             "location_label": "CANYON", "van_capacity": 4},
            MGR,
        )
        validate_error(resp, ApiErrorId.ERR_WINDOW_OVERLAP)

    def test_overlap_scope_is_per_location(self, api):
        """PRD Slope-Side Pickup Logistics: "Within the same location and date, two
        windows may touch — one ending exactly when another begins — but any strict
        overlap is rejected with `ERR_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/pickup_window_half_open_overlap_rule
        """
        make_pickup_window(service_date="2026-12-20", start_time="10:00",
                           end_time="12:00", location_label="CANYON", van_capacity=4)
        # Identical clock times at a different location_label are unaffected.
        other = make_pickup_window(service_date="2026-12-20", start_time="11:30",
                                   end_time="13:00", location_label="SUMMIT",
                                   van_capacity=4)
        assert other["id"]


class TestBookingGates:
    def test_booking_requires_confirmed_reservation(self, api):
        """PRD Slope-Side Pickup Logistics: "And the reservation named by
        `reservation_id` must be in `CONFIRMED` fulfillment, or the booking is rejected
        with `ERR_RESERVATION_NOT_CONFIRMED`."

        Design: Difficulty/cross_entity_state_dependency/pickup_booking_requires_confirmed_reservation
        """
        window = make_pickup_window(service_date="2026-12-20")
        customer = make_customer()
        reservation = make_reservation(customer, start_date="2026-12-20",
                                       end_date="2026-12-21", pickup_method="SLOPE_SIDE")

        # DRAFT reservation: rejected.
        resp = api.create_pickup_booking(
            {"pickup_window_id": window["id"], "reservation_id": reservation["id"]},
            make_customer_headers(customer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_RESERVATION_NOT_CONFIRMED)

    def test_booking_succeeds_after_confirmation(self, api):
        """PRD Slope-Side Pickup Logistics: "A successful booking enters as `BOOKED`
        and increments the window's `booked_count`, which may itself tip the posture
        from `OPEN` to `FULL`."

        Design: Difficulty/cross_entity_state_dependency/pickup_booking_requires_confirmed_reservation
        """
        window = make_pickup_window(service_date="2026-12-20")
        ctx = setup_confirmed_slope_side_reservation()
        booking = make_pickup_booking(window, ctx["reservation"])
        assert booking["status"] == "BOOKED"
        after = validate_success(api.get_pickup_window(window["id"], FD))
        assert after["booked_count"] == 1

    def test_expired_window_error_beats_unconfirmed_reservation(self, api):
        """PRD Slope-Side Pickup Logistics: "three checks guard it in order. The
        window's end must still be in the future relative to the logical clock —
        booking into an expired window is rejected with `ERR_WINDOW_EXPIRED`." and
        "And the reservation named by `reservation_id` must be in `CONFIRMED`
        fulfillment, or the booking is rejected with `ERR_RESERVATION_NOT_CONFIRMED`."
        PRD Request Validation Precedence: "Where several business rules guard the same
        operation, §3 states their evaluation order explicitly; text order in those
        passages is normative."

        Design: Difficulty/priority_pair_validation_conflict/window_expired_beats_unconfirmed_reservation
        """
        window = make_pickup_window(service_date="2026-12-01", start_time="10:00",
                                    end_time="12:00", location_label="CANYON",
                                    van_capacity=4)
        customer = make_customer()
        reservation = make_reservation(customer, start_date="2026-12-05",
                                       end_date="2026-12-06", pickup_method="SLOPE_SIDE")
        set_clock("2026-12-02T00:00:01Z")  # window end is now in the past

        resp = api.create_pickup_booking(
            {"pickup_window_id": window["id"], "reservation_id": reservation["id"]},
            make_customer_headers(customer["id"]),
        )
        # Both rules are violated (window expired AND reservation DRAFT); the
        # expired-window check is stated first and wins.
        validate_error(resp, ApiErrorId.ERR_WINDOW_EXPIRED)

    def test_expired_window_booking_returns_422(self, api):
        """PRD Slope-Side Pickup Logistics: "The window's end must still be in the
        future relative to the logical clock — booking into an expired window is
        rejected with `ERR_WINDOW_EXPIRED`."

        Design: Difficulty/priority_pair_validation_conflict/window_expired_beats_unconfirmed_reservation
        """
        window = make_pickup_window(service_date="2026-12-01", start_time="10:00",
                                    end_time="12:00", location_label="CANYON",
                                    van_capacity=4)
        customer = make_customer()
        reservation = make_reservation(customer, start_date="2026-12-05",
                                       end_date="2026-12-06", pickup_method="SLOPE_SIDE")
        set_clock("2026-12-02T00:00:01Z")

        resp = api.create_pickup_booking(
            {"pickup_window_id": window["id"], "reservation_id": reservation["id"]},
            make_customer_headers(customer["id"]),
        )
        assert resp.status_code == 422
        assert resp.json()["data"]["error_id"] == ApiErrorId.ERR_WINDOW_EXPIRED


class TestWindowCapacity:
    def test_exact_fit_fills_window_then_full(self, api):
        """PRD Slope-Side Pickup Logistics: "`FULL` when the count of live bookings has
        reached `van_capacity` — an exact fit fills the window — and otherwise `OPEN`"
        and "The window must have room — a `FULL` window rejects further bookings with
        `ERR_WINDOW_FULL`."

        Design: Corner/errors/window_exact_capacity_fills_then_full
        """
        window = make_pickup_window(service_date="2026-12-20", van_capacity=1)
        first = setup_confirmed_slope_side_reservation()
        second = setup_confirmed_slope_side_reservation()

        booking = make_pickup_booking(window, first["reservation"])
        assert booking["status"] == "BOOKED"
        full = validate_success(api.get_pickup_window(window["id"], FD))
        assert full["booked_count"] == 1
        assert full["posture"] == "FULL"  # 1 >= 1: exact fit fills the window

        resp = api.create_pickup_booking(
            {"pickup_window_id": window["id"],
             "reservation_id": second["reservation"]["id"]},
            make_customer_headers(second["customer"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_WINDOW_FULL)


class TestWindowCloseSweep:
    def test_clock_reaching_window_end_no_shows_bookings(self, api):
        """PRD Slope-Side Pickup Logistics: "when the logical clock reaches a window's
        end, the window closes and every booking still `BOOKED` at that moment is swept
        to `NO_SHOW`." and "`CLOSED` once the logical clock reaches the window's end"

        Design: Corner/state_machines/pickup_booking_no_show_when_window_closes
        """
        window = make_pickup_window(service_date="2026-12-20", start_time="10:00",
                                    end_time="12:00", location_label="CANYON",
                                    van_capacity=2)
        ctx = setup_confirmed_slope_side_reservation()
        booking = make_pickup_booking(window, ctx["reservation"])

        set_clock("2026-12-20T12:00:00Z")  # now >= window end
        booking_after = validate_success(api.get_pickup_booking(booking["id"], FD))
        assert booking_after["status"] == "NO_SHOW"
        window_after = validate_success(api.get_pickup_window(window["id"], FD))
        assert window_after["posture"] == "CLOSED"
