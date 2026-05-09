"""Practice cancel, reschedule, check-in, check-out (PRD §3.4, §3.5)."""
import pytest
from datetime import timedelta

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    create_active_student,
    create_active_instructor,
    create_active_vehicle,
    create_default_package,
    setup_basic_scenario,
    book_practice,
    book_practice_at,
    create_practice_payload,
    reschedule_payload,
    check_out_payload,
    iso_z,
    future_window,
    _server_clock_now,
    ADMIN_HEADERS,
    make_student_headers,
    make_instructor_headers,
    get_practice,
    get_student,
)


# --- Cancellation tier tests ---

class TestLateCancellationFee:
    """PRD §3.4: tiered cancellation fee.

    Tiers (PRD §3.4):
      delta_hours <= 0       → 100%
      0 < delta_hours < 2    → 100%
      2 <= delta_hours < 24  → 50%
      delta_hours >= 24      → 0%
    """

    def test_under_two_hours_charges_100_percent(self, api):
        """PRD §3.4: "when delta_hours is at or below zero the tier is 100
        percent; when delta_hours is strictly greater than zero but strictly
        less than 2, the tier is also 100 percent."

        # difficulty: combinatorial_formula/late_cancellation_fee_tiered_three_inputs
        Claim: 60-min booking at clock_now+60min cancelled at clock_now → 100% tier.
        Fee = 60 * 200 cents/min * 100% = 12000 cents.
        """
        package = create_default_package(api)
        student, _ = create_active_student(api, package_id=package["id"])
        instructor = create_active_instructor(api)
        vehicle = create_active_vehicle(api)
        practice = book_practice(api,
                                   student=student, instructor=instructor, vehicle=vehicle,
                                   training_stage="THEORY",
                                   start_offset_min=60, duration_min=60)
        # Cancel immediately: delta_hours = 1.0 → tier 100%
        resp = api.cancel_practice(practice["id"], ADMIN_HEADERS)
        data = validate_success(resp)
        assert data["status"] == "CANCELLED"
        assert data["late_cancellation_fee_cents"] == 12000

    def test_24_hour_boundary_zero_percent(self, api):
        """PRD §3.4: "when delta_hours is at or above 24, the tier is 0 percent.
        (At exactly 2 hours the tier is 50; at exactly 24 hours the tier is 0.)"

        Claim: 60-min booking at clock_now+24h cancelled at clock_now → 0% tier.
        """
        package = create_default_package(api)
        student, _ = create_active_student(api, package_id=package["id"])
        instructor = create_active_instructor(api)
        vehicle = create_active_vehicle(api)
        practice = book_practice(api,
                                   student=student, instructor=instructor, vehicle=vehicle,
                                   training_stage="THEORY",
                                   start_offset_min=24 * 60, duration_min=60)
        resp = api.cancel_practice(practice["id"], ADMIN_HEADERS)
        data = validate_success(resp)
        assert data["status"] == "CANCELLED"
        assert data["late_cancellation_fee_cents"] == 0

    def test_2_hour_boundary_50_percent(self, api):
        """PRD §3.4: "At exactly 2 hours the tier is 50."

        Claim: 60-min booking starting at clock_now + 120 min cancelled at
        clock_now → tier 50%. Fee = 60 * 200 * 50% = 6000 cents.
        """
        package = create_default_package(api)
        student, _ = create_active_student(api, package_id=package["id"])
        instructor = create_active_instructor(api)
        vehicle = create_active_vehicle(api)
        practice = book_practice(api,
                                   student=student, instructor=instructor, vehicle=vehicle,
                                   training_stage="THEORY",
                                   start_offset_min=120, duration_min=60)
        resp = api.cancel_practice(practice["id"], ADMIN_HEADERS)
        data = validate_success(resp)
        assert data["status"] == "CANCELLED"
        assert data["late_cancellation_fee_cents"] == 6000


class TestCancelStateGate:

    def test_cannot_cancel_already_cancelled(self, api):
        """PRD §3.4: "If the practice is not in BOOKED, the cancel is rejected
        with ERR_APPOINTMENT_NOT_CANCELLABLE."
        """
        scenario = setup_basic_scenario(api)
        practice = book_practice(api, student=scenario["student"],
                                   instructor=scenario["instructor"],
                                   vehicle=scenario["vehicle"],
                                   training_stage="THEORY")
        get_success_data(api.cancel_practice(practice["id"], ADMIN_HEADERS))
        resp = api.cancel_practice(practice["id"], ADMIN_HEADERS)
        validate_error(resp, ApiErrorId.ERR_APPOINTMENT_NOT_CANCELLABLE.value)


# --- Reschedule tests ---

class TestReschedule:

    def test_reschedule_creates_new_booked_and_cancels_old_no_fee(self, api):
        """PRD §3.4: "The reschedule capability atomically cancels a BOOKED
        practice and creates a new BOOKED practice in the same operation ...
        The cancellation half of the operation does not charge a
        late-cancellation fee — late_cancellation_fee_cents is set to zero on
        the cancelled row regardless of which tier the timing would otherwise
        place it in."
        """
        scenario = setup_basic_scenario(api)
        practice = book_practice(api, student=scenario["student"],
                                   instructor=scenario["instructor"],
                                   vehicle=scenario["vehicle"],
                                   training_stage="THEORY",
                                   start_offset_min=60, duration_min=60)
        new_start, new_end, _ = future_window(api, offset_minutes=240, duration_minutes=60)
        resp = api.reschedule_practice(practice["id"],
                                         reschedule_payload(new_scheduled_start_at=new_start,
                                                              new_scheduled_end_at=new_end),
                                         ADMIN_HEADERS)
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "BOOKED"
        assert data["reschedule_of_id"] == practice["id"]
        # Original is CANCELLED with zero fee
        original = get_practice(api, practice["id"])
        assert original["status"] == "CANCELLED"
        assert original["late_cancellation_fee_cents"] == 0

    def test_reschedule_increments_count(self, api):
        """PRD §3.4: "increments the student's reschedule_count_this_cycle."
        """
        scenario = setup_basic_scenario(api)
        practice = book_practice(api, student=scenario["student"],
                                   instructor=scenario["instructor"],
                                   vehicle=scenario["vehicle"],
                                   training_stage="THEORY",
                                   start_offset_min=60, duration_min=60)
        new_start, new_end, _ = future_window(api, offset_minutes=240, duration_minutes=60)
        get_success_data(api.reschedule_practice(practice["id"],
                                                    reschedule_payload(new_scheduled_start_at=new_start,
                                                                         new_scheduled_end_at=new_end),
                                                    ADMIN_HEADERS))
        student = get_student(api, scenario["student"]["id"])
        assert student["reschedule_count_this_cycle"] == 1

    def test_reschedule_limit_at_third_reschedule(self, api):
        """PRD §3.4: "If the student's reschedule_count_this_cycle is already at
        the per-cycle cap of 3, the operation is rejected with
        ERR_RESCHEDULE_LIMIT_EXCEEDED."

        # difficulty: boundary_precision_check/reschedule_count_limit_at_third_reschedule
        Claim: at count==3, the next reschedule rejects with the named error_id;
        the targeted appointment's status is unchanged.
        """
        scenario = setup_basic_scenario(api)
        # Initial booking
        practice = book_practice(api, student=scenario["student"],
                                   instructor=scenario["instructor"],
                                   vehicle=scenario["vehicle"],
                                   training_stage="THEORY",
                                   start_offset_min=60, duration_min=60)
        # Reschedule three times
        current_id = practice["id"]
        offsets = [240, 360, 480]
        for offs in offsets:
            new_start, new_end, _ = future_window(api, offset_minutes=offs, duration_minutes=60)
            resp = api.reschedule_practice(current_id,
                                             reschedule_payload(new_scheduled_start_at=new_start,
                                                                  new_scheduled_end_at=new_end),
                                             ADMIN_HEADERS)
            data = get_success_data(resp)
            current_id = data["id"]

        student = get_student(api, scenario["student"]["id"])
        assert student["reschedule_count_this_cycle"] == 3

        # 4th reschedule attempt rejected
        new_start, new_end, _ = future_window(api, offset_minutes=600, duration_minutes=60)
        resp = api.reschedule_practice(current_id,
                                         reschedule_payload(new_scheduled_start_at=new_start,
                                                              new_scheduled_end_at=new_end),
                                         ADMIN_HEADERS)
        validate_error(resp, ApiErrorId.ERR_RESCHEDULE_LIMIT_EXCEEDED.value)
        # Targeted appointment NOT cancelled
        target = get_practice(api, current_id)
        assert target["status"] == "BOOKED"


# --- Check-in / check-out ---

class TestCheckInCheckOut:

    def test_outside_check_in_window_rejected(self, api):
        """PRD §3.5: "The check-in window is itself a precondition: the logical
        clock must be at or after scheduled_start_at − 15 minutes and strictly
        before scheduled_end_at; otherwise the check-in is rejected with
        ERR_OUTSIDE_CHECK_IN_WINDOW."

        Claim: at clock_now (60 min before start), check-in is outside window.
        """
        scenario = setup_basic_scenario(api)
        practice = book_practice(api, student=scenario["student"],
                                   instructor=scenario["instructor"],
                                   vehicle=scenario["vehicle"],
                                   training_stage="THEORY",
                                   start_offset_min=60, duration_min=60)
        instr_headers = make_instructor_headers(scenario["instructor"]["id"])
        resp = api.check_in_practice(practice["id"], instr_headers)
        validate_error(resp, ApiErrorId.ERR_OUTSIDE_CHECK_IN_WINDOW.value)

    def test_check_in_succeeds_within_window(self, api):
        """PRD §3.5: "On success, the appointment advances to IN_PROGRESS,
        check_in_at is stamped to the logical clock."
        """
        scenario = setup_basic_scenario(api)
        practice = book_practice(api, student=scenario["student"],
                                   instructor=scenario["instructor"],
                                   vehicle=scenario["vehicle"],
                                   training_stage="THEORY",
                                   start_offset_min=60, duration_min=60)
        # advance into window (50 min from now → 10 min before start, within ±15)
        get_success_data(api.advance_clock(50, ADMIN_HEADERS))
        instr_headers = make_instructor_headers(scenario["instructor"]["id"])
        resp = api.check_in_practice(practice["id"], instr_headers)
        data = validate_success(resp)
        assert data["status"] == "IN_PROGRESS"
        assert data["check_in_at"] is not None

    def test_check_in_wrong_instructor_rejected(self, api):
        """PRD §3.5: "The check-in is rejected with
        ERR_FORBIDDEN_NOT_ASSIGNED_INSTRUCTOR if the acting Instructor's
        X-User-ID does not match the appointment's instructor_id."
        """
        scenario = setup_basic_scenario(api)
        # Different instructor — same qualifications, different id
        other_instructor = create_active_instructor(api)
        practice = book_practice(api, student=scenario["student"],
                                   instructor=scenario["instructor"],
                                   vehicle=scenario["vehicle"],
                                   training_stage="THEORY",
                                   start_offset_min=60, duration_min=60)
        get_success_data(api.advance_clock(50, ADMIN_HEADERS))
        wrong_headers = make_instructor_headers(other_instructor["id"])
        resp = api.check_in_practice(practice["id"], wrong_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_NOT_ASSIGNED_INSTRUCTOR.value)


class TestGpsValidation:
    """PRD §2.6, §3.5 — GPS threshold inclusive at 5.00 km."""

    def test_gps_at_5km_validates(self, api):
        """PRD §2.6: "the GPS validation threshold is inclusive at exactly 5.00
        — a distance of 5.00 km validates, a distance of 4.99 km does not."
        PRD §3.5: "gps_validated becomes true exactly when gps_track_distance_km
        is at or above the 5.00 km threshold ... and recorded_minutes becomes
        scheduled_minutes if gps_validated is true and 0 otherwise."

        # difficulty: boundary_precision_check/gps_distance_inclusive_minimum_at_check_out
        Claim: gps_track_distance_km = 5.00 → gps_validated=true,
        recorded_minutes = scheduled_minutes (60).
        """
        scenario = setup_basic_scenario(api)
        practice = book_practice(api, student=scenario["student"],
                                   instructor=scenario["instructor"],
                                   vehicle=scenario["vehicle"],
                                   training_stage="THEORY",
                                   start_offset_min=60, duration_min=60)
        # advance into window
        get_success_data(api.advance_clock(60, ADMIN_HEADERS))
        instr_headers = make_instructor_headers(scenario["instructor"]["id"])
        get_success_data(api.check_in_practice(practice["id"], instr_headers))
        # advance to scheduled_end_at
        get_success_data(api.advance_clock(60, ADMIN_HEADERS))
        resp = api.check_out_practice(practice["id"], check_out_payload(5.00), instr_headers)
        data = validate_success(resp)
        assert data["status"] == "COMPLETED"
        assert data["gps_validated"] is True
        assert data["recorded_minutes"] == 60

    def test_gps_at_499km_invalidates(self, api):
        """PRD §2.6: "a distance of 4.99 km does not [validate]."
        PRD §3.5: "recorded_minutes becomes ... 0 otherwise."
        """
        scenario = setup_basic_scenario(api)
        practice = book_practice(api, student=scenario["student"],
                                   instructor=scenario["instructor"],
                                   vehicle=scenario["vehicle"],
                                   training_stage="THEORY",
                                   start_offset_min=60, duration_min=60)
        get_success_data(api.advance_clock(60, ADMIN_HEADERS))
        instr_headers = make_instructor_headers(scenario["instructor"]["id"])
        get_success_data(api.check_in_practice(practice["id"], instr_headers))
        get_success_data(api.advance_clock(60, ADMIN_HEADERS))
        resp = api.check_out_practice(practice["id"], check_out_payload(4.99), instr_headers)
        data = validate_success(resp)
        assert data["status"] == "COMPLETED"
        assert data["gps_validated"] is False
        assert data["recorded_minutes"] == 0

    def test_provisional_vs_final_diverge_on_invalid_gps(self, api):
        """PRD §3.3 / §3.5: provisional uses scheduled_minutes for
        BOOKED+IN_PROGRESS+COMPLETED; final uses recorded_minutes for
        COMPLETED+gps_validated=true. A COMPLETED-with-gps_validated=false
        practice contributes scheduled_minutes to provisional but 0 to final.

        # difficulty: dual_variant_calc/student_minutes_remaining_provisional_vs_final
        Claim: after a 60-min COMPLETED practice with gps_validated=false,
        Student.minutes_remaining_provisional == total - 60,
        Student.minutes_remaining_final == total.
        """
        package = create_default_package(api)  # total_minutes=2000
        student, _ = create_active_student(api, package_id=package["id"])
        instructor = create_active_instructor(api)
        vehicle = create_active_vehicle(api)
        practice = book_practice(api, student=student, instructor=instructor, vehicle=vehicle,
                                   training_stage="THEORY",
                                   start_offset_min=60, duration_min=60)
        get_success_data(api.advance_clock(70, ADMIN_HEADERS))
        instr_headers = make_instructor_headers(instructor["id"])
        get_success_data(api.check_in_practice(practice["id"], instr_headers))
        get_success_data(api.advance_clock(55, ADMIN_HEADERS))
        # GPS invalid
        get_success_data(api.check_out_practice(practice["id"],
                                                  check_out_payload(4.99),
                                                  instr_headers))
        s = get_student(api, student["id"])
        assert s["minutes_remaining_provisional"] == 2000 - 60
        assert s["minutes_remaining_final"] == 2000
