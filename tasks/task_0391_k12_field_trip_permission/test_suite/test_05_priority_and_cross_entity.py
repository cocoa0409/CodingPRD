"""Lock-precondition ordering (safety before transport-constraint) and
cross-entity state gates (slip → trip, booking → vehicle).
"""
from test_helpers import (
    get_success_data,
    validate_success,
    validate_error,
    TEST_USERS,
    make_teacher_headers,
    make_guardian_headers,
    create_approved_trip,
    create_pending_principal_trip,
    create_guardian,
    create_student,
    create_slip,
    add_emergency_contact,
    create_signed_slip,
    create_vehicle,
    request_booking,
    get_trip_version,
)


_PRINCIPAL = TEST_USERS["principal_headers"]
_DISTRICT = TEST_USERS["district_admin_headers"]


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty/priority_pair_validation_conflict/ratio_safety_beats_transport_constraint_at_lock
# ─────────────────────────────────────────────────────────────────────────────
class TestLockSafetyBeatsTransport:
    def _approved_trip_one_signed_no_chaperone_no_transport(self, api):
        teacher_id, trip = create_approved_trip(
            grade_band="MIDDLE", capacity=5, base_fee_cents=0, transport_cost_cents=0,
        )
        trip_id = trip["id"]
        g = create_guardian(full_name="G10")
        st = create_student(teacher_id, full_name="S10", grade_level=7)
        create_signed_slip(teacher_id, trip_id, st["id"], g["id"])
        return teacher_id, trip_id

    def test_lock_missing_ratio_and_transport_reports_ratio(self, api):
        """PRD §3.8: "it runs a gauntlet of preconditions in order. ... The chaperone ratio must be met — the count of `CLEARED` chaperones must be at least the trip's `required_chaperones`, otherwise `ERR_CHAPERONE_RATIO_UNMET`. And transport must be booked — the trip must have at least one `CONFIRMED` transport booking whose summed `seat_count` is at least `signed_count`, otherwise `ERR_TRANSPORT_NOT_BOOKED`."

        With neither a CLEARED chaperone nor transport, the ratio check (named
        first in the ordered gauntlet) fires: ERR_CHAPERONE_RATIO_UNMET.

        Design: Difficulty/priority_pair_validation_conflict/ratio_safety_beats_transport_constraint_at_lock
        """
        teacher_id, trip_id = self._approved_trip_one_signed_no_chaperone_no_transport(api)
        teacher = make_teacher_headers(teacher_id)
        version = get_trip_version(teacher_id, trip_id)
        res = api.lock_roster(trip_id, {"expected_trip_version": version}, teacher)
        validate_error(res, "ERR_CHAPERONE_RATIO_UNMET")

    def test_lock_ratio_failure_leaves_trip_approved(self, api):
        """PRD §3.8: "When the roster is ready, the `Teacher` locks it, advancing the trip `APPROVED → ROSTER_LOCKED`."
        PRD §3.8: "The chaperone ratio must be met — the count of `CLEARED` chaperones must be at least the trip's `required_chaperones`, otherwise `ERR_CHAPERONE_RATIO_UNMET`."

        A lock rejected on the ratio precondition does not advance the trip; it
        stays APPROVED.

        Design: Difficulty/priority_pair_validation_conflict/ratio_safety_beats_transport_constraint_at_lock
        """
        teacher_id, trip_id = self._approved_trip_one_signed_no_chaperone_no_transport(api)
        teacher = make_teacher_headers(teacher_id)
        version = get_trip_version(teacher_id, trip_id)
        validate_error(api.lock_roster(trip_id, {"expected_trip_version": version}, teacher),
                       "ERR_CHAPERONE_RATIO_UNMET")
        trip = get_success_data(api.get_field_trip(trip_id, teacher))
        assert trip["status"] == "APPROVED", f"trip should stay APPROVED, got {trip['status']}"


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty/cross_entity_state_dependency/slip_sign_requires_trip_approved
# ─────────────────────────────────────────────────────────────────────────────
class TestSignRequiresTripApproved:
    def test_sign_on_pending_principal_trip_rejected(self, api):
        """PRD §3.3: "The parent trip must be in `APPROVED` for signing to be open; signing against a trip in any other state is rejected with `ERR_TRIP_NOT_OPEN_FOR_SIGNING`."

        A slip on a PENDING_PRINCIPAL (not-yet-approved) trip cannot be signed.

        Design: Difficulty/cross_entity_state_dependency/slip_sign_requires_trip_approved
        """
        teacher_id, pp_trip = create_pending_principal_trip(grade_band="MIDDLE", capacity=5)
        trip_id = pp_trip["id"]
        # The trip is PENDING_PRINCIPAL; create a slip with an emergency contact
        # (slip creation is allowed on the trip), then attempt to sign it.
        g = create_guardian(full_name="G13")
        st = create_student(teacher_id, full_name="S13", grade_level=7)
        slip = create_slip(teacher_id, trip_id, st["id"], g["id"])
        add_emergency_contact(teacher_id, trip_id, slip["id"])
        res = api.sign_slip(trip_id, slip["id"], make_guardian_headers(g["id"]))
        validate_error(res, "ERR_TRIP_NOT_OPEN_FOR_SIGNING")

    def test_sign_rejected_leaves_slip_unsigned(self, api):
        """PRD §3.3: "On a successful sign the server moves the slip to `SIGNED ...
        increments the trip's `signed_count` by 1..."
        PRD §3.3: "signing against a trip in any other state is rejected with `ERR_TRIP_NOT_OPEN_FOR_SIGNING`."

        After a rejected sign the slip's signature_status stays UNSIGNED and the
        trip's signed_count stays 0.

        Design: Difficulty/cross_entity_state_dependency/slip_sign_requires_trip_approved
        """
        teacher_id, pp_trip = create_pending_principal_trip(grade_band="MIDDLE", capacity=5)
        trip_id = pp_trip["id"]
        teacher = make_teacher_headers(teacher_id)
        g = create_guardian(full_name="G13b")
        st = create_student(teacher_id, full_name="S13b", grade_level=7)
        slip = create_slip(teacher_id, trip_id, st["id"], g["id"])
        add_emergency_contact(teacher_id, trip_id, slip["id"])
        validate_error(api.sign_slip(trip_id, slip["id"], make_guardian_headers(g["id"])),
                       "ERR_TRIP_NOT_OPEN_FOR_SIGNING")
        slip = get_success_data(api.get_permission_slip(slip["id"], teacher))
        trip = get_success_data(api.get_field_trip(trip_id, teacher))
        assert slip["signature_status"] == "UNSIGNED"
        assert trip["signed_count"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty/cross_entity_state_dependency/booking_confirm_requires_vehicle_active
# ─────────────────────────────────────────────────────────────────────────────
class TestBookingConfirmRequiresVehicleActive:
    def _approved_trip_requested_booking_retired_vehicle(self, api):
        teacher_id, trip = create_approved_trip(
            grade_band="HIGH", capacity=5, base_fee_cents=0, transport_cost_cents=0,
        )
        trip_id = trip["id"]
        vehicle = create_vehicle(label="Bus 14", seat_capacity=10)
        booking = request_booking(teacher_id, trip_id, vehicle["id"], 3)
        validate_success(api.retire_vehicle(vehicle["id"], _DISTRICT), 200)
        return teacher_id, trip_id, vehicle["id"], booking["id"]

    def test_confirm_booking_on_retired_vehicle_rejected(self, api):
        """PRD §3.6: "requires the vehicle's `status` to be `ACTIVE`, otherwise
        `ERR_VEHICLE_RETIRED`."

        Confirming a REQUESTED booking whose vehicle has been RETIRED is rejected
        with ERR_VEHICLE_RETIRED.

        Design: Difficulty/cross_entity_state_dependency/booking_confirm_requires_vehicle_active
        """
        teacher_id, trip_id, _, booking_id = self._approved_trip_requested_booking_retired_vehicle(api)
        res = api.confirm_booking(trip_id, booking_id, make_teacher_headers(teacher_id))
        validate_error(res, "ERR_VEHICLE_RETIRED")

    def test_confirm_rejected_leaves_booking_requested_and_no_seats(self, api):
        """PRD §3.6: "On a successful confirm the booking becomes `CONFIRMED` and the vehicle's `seats_reserved` increases by the booking's `seat_count`."
        PRD §3.6: "requires the vehicle's `status` to be `ACTIVE`, otherwise
        `ERR_VEHICLE_RETIRED`."

        A rejected confirm leaves the booking REQUESTED and reserves no seats.

        Design: Difficulty/cross_entity_state_dependency/booking_confirm_requires_vehicle_active
        """
        teacher_id, trip_id, vehicle_id, booking_id = self._approved_trip_requested_booking_retired_vehicle(api)
        teacher = make_teacher_headers(teacher_id)
        validate_error(api.confirm_booking(trip_id, booking_id, teacher), "ERR_VEHICLE_RETIRED")
        booking = get_success_data(api.get_transport_booking(booking_id, teacher))
        vehicle = get_success_data(api.get_vehicle(vehicle_id, teacher))
        assert booking["status"] == "REQUESTED"
        assert vehicle["seats_reserved"] == 0
