"""Two distinct overlap rules with deliberately different interval semantics:
closed-interval no-buffer on a Vehicle, half-open buffered on a Guardian-chaperone.
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
    create_vehicle,
    create_confirmed_booking,
    request_booking,
    invite_chaperone,
    confirm_chaperone,
    clear_chaperone,
)


_PRINCIPAL = TEST_USERS["principal_headers"]


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty/resource_temporal_overlap/vehicle_closed_interval_touching_conflict
# ─────────────────────────────────────────────────────────────────────────────
class TestVehicleClosedIntervalOverlap:
    def _setup_two_trips_one_vehicle_touching(self, api):
        """Trip A 09:00-12:00 with a CONFIRMED booking on vehicle V; trip B
        12:00-15:00 with a REQUESTED booking on the same V (endpoints touch)."""
        teacher_id, trip_a = create_approved_trip(
            grade_band="HIGH", capacity=5, base_fee_cents=0, transport_cost_cents=0,
            title="A", depart_at="2026-09-29T09:00:00Z", return_at="2026-09-29T12:00:00Z",
        )
        vehicle = create_vehicle(label="Bus 15", seat_capacity=40)
        create_confirmed_booking(teacher_id, trip_a["id"], vehicle["id"], 3)
        # Second trip on same vehicle, window touches at 12:00.
        _, trip_b = create_approved_trip(
            teacher_id=teacher_id, grade_band="HIGH", capacity=5,
            base_fee_cents=0, transport_cost_cents=0,
            title="B", depart_at="2026-09-29T12:00:00Z", return_at="2026-09-29T15:00:00Z",
        )
        booking_b = request_booking(teacher_id, trip_b["id"], vehicle["id"], 3)
        return teacher_id, trip_b["id"], vehicle["id"], booking_b["id"]

    def test_touching_windows_collide_on_confirm(self, api):
        """PRD §3.5: "test for overlap on a closed interval with no buffer: the two clash when the new trip's departure is at or before the other's return and the other's departure is at or before the new trip's return. Touching endpoints collide — if one trip returns at exactly the instant another departs, that is a conflict. Any clash rejects the confirm with `ERR_VEHICLE_TIME_CONFLICT`."

        Trip A returns 12:00, trip B departs 12:00 on the same vehicle → conflict.

        Design: Difficulty/resource_temporal_overlap/vehicle_closed_interval_touching_conflict
        """
        teacher_id, trip_b_id, _, booking_b_id = self._setup_two_trips_one_vehicle_touching(api)
        res = api.confirm_booking(trip_b_id, booking_b_id, make_teacher_headers(teacher_id))
        validate_error(res, "ERR_VEHICLE_TIME_CONFLICT")

    def test_conflict_leaves_booking_requested_and_seats_unchanged(self, api):
        """PRD §3.5: "Any clash rejects the confirm with `ERR_VEHICLE_TIME_CONFLICT`."
        PRD §3.6: "On a successful confirm the booking becomes `CONFIRMED` and the vehicle's `seats_reserved` increases by the booking's `seat_count`."

        The rejected booking B stays REQUESTED and only booking A's 3 seats remain
        reserved on the vehicle.

        Design: Difficulty/resource_temporal_overlap/vehicle_closed_interval_touching_conflict
        """
        teacher_id, trip_b_id, vehicle_id, booking_b_id = self._setup_two_trips_one_vehicle_touching(api)
        teacher = make_teacher_headers(teacher_id)
        validate_error(api.confirm_booking(trip_b_id, booking_b_id, teacher),
                       "ERR_VEHICLE_TIME_CONFLICT")
        booking = get_success_data(api.get_transport_booking(booking_b_id, teacher))
        vehicle = get_success_data(api.get_vehicle(vehicle_id, teacher))
        assert booking["status"] == "REQUESTED"
        assert vehicle["seats_reserved"] == 3, (
            f"only booking A's 3 seats should be reserved, got {vehicle['seats_reserved']}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty/resource_temporal_overlap/chaperone_buffered_halfopen_overlap_conflict
# ─────────────────────────────────────────────────────────────────────────────
class TestChaperoneBufferedHalfOpenOverlap:
    def _setup_same_guardian_two_trips_within_buffer(self, api):
        """Guardian Gc CLEARED as chaperone on trip P (09:00-12:00); same Gc
        CONFIRMED as chaperone on trip R (12:30-15:00, within the 1h buffer)."""
        teacher_id, trip_p = create_approved_trip(
            grade_band="HIGH", capacity=5, base_fee_cents=0, transport_cost_cents=0,
            title="P", depart_at="2026-09-30T09:00:00Z", return_at="2026-09-30T12:00:00Z",
        )
        g_c = create_guardian(full_name="Gc")
        chap_p = invite_chaperone(teacher_id, trip_p["id"], g_c["id"], background_check_ref="BG-P")
        confirm_chaperone(g_c["id"], trip_p["id"], chap_p["id"])
        clear_chaperone(trip_p["id"], chap_p["id"])
        # Second trip starts 12:30 — within the 1h travel buffer after 12:00.
        _, trip_r = create_approved_trip(
            teacher_id=teacher_id, grade_band="HIGH", capacity=5,
            base_fee_cents=0, transport_cost_cents=0,
            title="R", depart_at="2026-09-30T12:30:00Z", return_at="2026-09-30T15:00:00Z",
        )
        chap_r = invite_chaperone(teacher_id, trip_r["id"], g_c["id"], background_check_ref="BG-R")
        confirm_chaperone(g_c["id"], trip_r["id"], chap_r["id"])
        return teacher_id, trip_r["id"], chap_r["id"]

    def test_buffered_windows_collide_on_clear(self, api):
        """PRD §3.5: "expand it by a travel buffer of one hour — that is, 3600 seconds — on each side. For every other `CLEARED` chaperone sharing the same `guardian_id`, take that chaperone's trip window unbuffered, and test for overlap on a half-open interval: they clash when the buffered start of the new window is strictly before the other window's end and the other window's start is strictly before the buffered end of the new window. ... Any clash rejects the clearance with `ERR_CHAPERONE_TIME_CONFLICT`."

        Trip P ends 12:00; trip R buffered start 11:30 < 12:00, and P's start 09:00
        < R's buffered end 16:00 → conflict.

        Design: Difficulty/resource_temporal_overlap/chaperone_buffered_halfopen_overlap_conflict
        """
        teacher_id, trip_r_id, chap_r_id = self._setup_same_guardian_two_trips_within_buffer(api)
        res = api.clear_chaperone(trip_r_id, chap_r_id, _PRINCIPAL)
        validate_error(res, "ERR_CHAPERONE_TIME_CONFLICT")

    def test_conflict_leaves_chaperone_confirmed(self, api):
        """PRD §3.4: "A `Principal` then clears the confirmed chaperone, moving `CONFIRMED → CLEARED`; only a cleared chaperone counts toward the ratio."
        PRD §3.5: "Any clash rejects the clearance with `ERR_CHAPERONE_TIME_CONFLICT`. A person cannot chaperone two trips at once."

        The rejected clearance leaves the second chaperone in CONFIRMED.

        Design: Difficulty/resource_temporal_overlap/chaperone_buffered_halfopen_overlap_conflict
        """
        teacher_id, trip_r_id, chap_r_id = self._setup_same_guardian_two_trips_within_buffer(api)
        teacher = make_teacher_headers(teacher_id)
        validate_error(api.clear_chaperone(trip_r_id, chap_r_id, _PRINCIPAL),
                       "ERR_CHAPERONE_TIME_CONFLICT")
        chap = get_success_data(api.get_chaperone(chap_r_id, teacher))
        assert chap["status"] == "CONFIRMED", f"chaperone should stay CONFIRMED, got {chap['status']}"
