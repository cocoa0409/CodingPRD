"""Depth-3 trip-cancellation cascade, the conserved-seats invariant, and the
empty-roster lock boundary.
"""
from test_helpers import (
    get_success_data,
    validate_success,
    validate_error,
    TEST_USERS,
    make_teacher_headers,
    make_guardian_headers,
    create_approved_trip,
    create_guardian,
    create_student,
    create_signed_slip,
    create_vehicle,
    create_confirmed_booking,
    pay_slip,
    get_trip_version,
)


_PRINCIPAL = TEST_USERS["principal_headers"]


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty/transitive_cascade/trip_cancel_depth3_refund_booking_chaperone
# ─────────────────────────────────────────────────────────────────────────────
class TestTripCancelDepth3Cascade:
    def _setup_paid_slip_and_confirmed_booking(self, api):
        """Trip APPROVED, deposit 0, base_fee 1000, transport 0; one slip
        SIGNED+PAID 1000; one CONFIRMED 5-seat booking on a vehicle."""
        teacher_id, trip = create_approved_trip(
            grade_band="ELEMENTARY", capacity=5, base_fee_cents=1000,
            transport_cost_cents=0, deposit_cents=0,
        )
        trip_id = trip["id"]
        g = create_guardian(full_name="G7")
        st = create_student(teacher_id, full_name="S7", grade_level=4)
        slip = create_signed_slip(teacher_id, trip_id, st["id"], g["id"])
        pay_slip(g["id"], trip_id, slip["id"], 1000)
        vehicle = create_vehicle(label="Bus 7", seat_capacity=10)
        booking = create_confirmed_booking(teacher_id, trip_id, vehicle["id"], 5)
        return teacher_id, trip_id, slip["id"], vehicle["id"], booking["id"]

    def test_cancel_refunds_paid_slip_in_full(self, api):
        """PRD §3.10: "every slip that is `PAID` has its `payment_status` set to `REFUNDED` and its `signature_status` set to `REVOKED`, and for each such slip a `FeeTransaction` of `kind` `REFUND` and `reason` `TRIP_CANCELLATION` is appended whose `amount_cents` is the negative of that slip's `net_paid_cents ... Appending those refunds drives each affected slip's `net_paid_cents` to zero and lowers the trip's `collected_fees_cents` correspondingly."

        Design: Difficulty/transitive_cascade/trip_cancel_depth3_refund_booking_chaperone
        """
        teacher_id, trip_id, slip_id, _, _ = self._setup_paid_slip_and_confirmed_booking(api)
        validate_success(api.cancel_trip(trip_id, _PRINCIPAL), 200)
        teacher = make_teacher_headers(teacher_id)
        trip = get_success_data(api.get_field_trip(trip_id, teacher))
        slip = get_success_data(api.get_permission_slip(slip_id, teacher))
        assert trip["status"] == "CANCELLED"
        assert slip["payment_status"] == "REFUNDED"
        assert slip["signature_status"] == "REVOKED"
        assert slip["net_paid_cents"] == 0, f"net_paid should be 0 after full refund, got {slip['net_paid_cents']}"
        assert trip["collected_fees_cents"] == 0, (
            f"collected_fees should drop to 0 after cascade, got {trip['collected_fees_cents']}"
        )

    def test_cancel_releases_booking_seats(self, api):
        """PRD §3.10: "every transport booking that is `CONFIRMED` or `REQUESTED` is moved to `CANCELLED`, and the seats from the confirmed ones are released back to their vehicles' `seats_reserved`."

        The 5-seat CONFIRMED booking becomes CANCELLED and the vehicle's
        seats_reserved returns to 0 — a cascade link caused by the cancel.

        Design: Difficulty/transitive_cascade/trip_cancel_depth3_refund_booking_chaperone
        """
        teacher_id, trip_id, _, vehicle_id, booking_id = self._setup_paid_slip_and_confirmed_booking(api)
        validate_success(api.cancel_trip(trip_id, _PRINCIPAL), 200)
        teacher = make_teacher_headers(teacher_id)
        booking = get_success_data(api.get_transport_booking(booking_id, teacher))
        vehicle = get_success_data(api.get_vehicle(vehicle_id, teacher))
        assert booking["status"] == "CANCELLED"
        assert vehicle["seats_reserved"] == 0, (
            f"seats should be released to 0 after cascade, got {vehicle['seats_reserved']}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty/compensating_invariant/seats_conserved_confirm_then_cancel
# ─────────────────────────────────────────────────────────────────────────────
class TestSeatConservation:
    def _setup_confirmed_5_seat_booking(self, api):
        teacher_id, trip = create_approved_trip(
            grade_band="HIGH", capacity=10, base_fee_cents=0, transport_cost_cents=0,
        )
        trip_id = trip["id"]
        vehicle = create_vehicle(label="Bus 18", seat_capacity=10)
        booking = create_confirmed_booking(teacher_id, trip_id, vehicle["id"], 5)
        return teacher_id, trip_id, vehicle["id"], booking["id"]

    def test_confirm_raises_seats_reserved(self, api):
        """PRD §2.9: "A `Vehicle`'s `seats_reserved` always equals the sum of `seat_count` over that vehicle's `CONFIRMED` transport bookings and may never exceed the vehicle's `seat_capacity`; confirming a booking adds its seats..."

        A confirmed 5-seat booking raises the vehicle's seats_reserved to 5.

        Design: Difficulty/compensating_invariant/seats_conserved_confirm_then_cancel
        """
        teacher_id, trip_id, vehicle_id, _ = self._setup_confirmed_5_seat_booking(api)
        vehicle = get_success_data(api.get_vehicle(vehicle_id, make_teacher_headers(teacher_id)))
        assert vehicle["seats_reserved"] == 5, (
            f"seats_reserved should be 5 after confirm, got {vehicle['seats_reserved']}"
        )

    def test_cancel_restores_seats_reserved(self, api):
        """PRD §2.9: "...and cancelling a confirmed booking returns them, so a confirm followed by a cancel restores `seats_reserved` to its prior value."

        Cancelling the confirmed booking returns seats_reserved 5 → 0 and the
        booking becomes CANCELLED — no seat drift.

        Design: Difficulty/compensating_invariant/seats_conserved_confirm_then_cancel
        """
        teacher_id, trip_id, vehicle_id, booking_id = self._setup_confirmed_5_seat_booking(api)
        teacher = make_teacher_headers(teacher_id)
        booking = validate_success(api.cancel_booking(trip_id, booking_id, teacher), 200)
        vehicle = get_success_data(api.get_vehicle(vehicle_id, teacher))
        assert booking["status"] == "CANCELLED"
        assert vehicle["seats_reserved"] == 0, (
            f"seats_reserved should restore to 0 after cancel, got {vehicle['seats_reserved']}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty/boundary_precision_check/empty_roster_zero_signed_lock_rejected
# ─────────────────────────────────────────────────────────────────────────────
class TestEmptyRosterBoundary:
    def test_lock_with_zero_signed_rejected(self, api):
        """PRD §3.8: "The roster must not be empty — `signed_count` must be at least 1, otherwise `ERR_EMPTY_ROSTER`."

        Locking an APPROVED trip with signed_count == 0 is rejected with
        ERR_EMPTY_ROSTER at exactly the zero boundary.

        Design: Difficulty/boundary_precision_check/empty_roster_zero_signed_lock_rejected
        """
        teacher_id, trip = create_approved_trip(
            grade_band="HIGH", capacity=5, base_fee_cents=0, transport_cost_cents=0,
        )
        trip_id = trip["id"]
        teacher = make_teacher_headers(teacher_id)
        version = get_trip_version(teacher_id, trip_id)
        res = api.lock_roster(trip_id, {"expected_trip_version": version}, teacher)
        validate_error(res, "ERR_EMPTY_ROSTER")

    def test_empty_roster_lock_leaves_trip_approved(self, api):
        """PRD §3.8: "The trip must be in `APPROVED`, otherwise `ERR_TRIP_NOT_APPROVED`.
        ... The roster must not be empty — `signed_count` must be at least 1, otherwise `ERR_EMPTY_ROSTER`."

        A rejected empty-roster lock leaves the trip in APPROVED (the transition
        does not fire).

        Design: Difficulty/boundary_precision_check/empty_roster_zero_signed_lock_rejected
        """
        teacher_id, trip = create_approved_trip(
            grade_band="HIGH", capacity=5, base_fee_cents=0, transport_cost_cents=0,
        )
        trip_id = trip["id"]
        teacher = make_teacher_headers(teacher_id)
        version = get_trip_version(teacher_id, trip_id)
        validate_error(api.lock_roster(trip_id, {"expected_trip_version": version}, teacher),
                       "ERR_EMPTY_ROSTER")
        trip = get_success_data(api.get_field_trip(trip_id, teacher))
        assert trip["status"] == "APPROVED", f"trip should stay APPROVED, got {trip['status']}"
