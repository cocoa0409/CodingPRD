"""Practice booking gates — referential, temporal, safety (PRD §3.3)."""
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
    iso_z,
    future_window,
    _server_clock_now,
    ADMIN_HEADERS,
    assert_practice,
    make_student_headers,
)


class TestPracticeBookingHappyPath:

    def test_book_practice_success(self, api):
        """PRD §3.3: "When all gates pass, the practice is persisted at BOOKED,
        an AuditLog row is written with action CREATE, and the response carries
        the new appointment."
        """
        scenario = setup_basic_scenario(api)
        practice = book_practice(api,
                                   student=scenario["student"],
                                   instructor=scenario["instructor"],
                                   vehicle=scenario["vehicle"],
                                   training_stage="THEORY")
        assert_practice(practice)
        assert practice["status"] == "BOOKED"
        assert practice["scheduled_minutes"] == 60
        assert practice["vehicle_type"] == scenario["vehicle"]["vehicle_type"]


class TestPracticeBookingRoleState:

    def test_inactive_student_rejected(self, api):
        """PRD §3.3: "The student must be ACTIVE (otherwise ERR_STUDENT_NOT_ACTIVE)."
        """
        scenario = setup_basic_scenario(api)
        # Suspend the student
        get_success_data(api.suspend_student(scenario["student"]["id"], ADMIN_HEADERS))
        start, end, _ = future_window(api, offset_minutes=120, duration_minutes=60)
        resp = api.book_practice(create_practice_payload(
            student_id=scenario["student"]["id"],
            instructor_id=scenario["instructor"]["id"],
            vehicle_id=scenario["vehicle"]["id"],
            training_stage="THEORY",
            scheduled_start_at=start,
            scheduled_end_at=end,
        ), ADMIN_HEADERS)
        validate_error(resp, ApiErrorId.ERR_STUDENT_NOT_ACTIVE.value)

    def test_inactive_instructor_rejected(self, api):
        """PRD §3.3: "The instructor must be ACTIVE (otherwise ERR_INSTRUCTOR_NOT_ACTIVE)."

        # difficulty: cross_entity_state_dependency/practice_booking_requires_instructor_active
        """
        scenario = setup_basic_scenario(api)
        get_success_data(api.suspend_instructor(scenario["instructor"]["id"], ADMIN_HEADERS))
        start, end, _ = future_window(api, offset_minutes=120, duration_minutes=60)
        resp = api.book_practice(create_practice_payload(
            student_id=scenario["student"]["id"],
            instructor_id=scenario["instructor"]["id"],
            vehicle_id=scenario["vehicle"]["id"],
            training_stage="THEORY",
            scheduled_start_at=start,
            scheduled_end_at=end,
        ), ADMIN_HEADERS)
        validate_error(resp, ApiErrorId.ERR_INSTRUCTOR_NOT_ACTIVE.value)

    def test_inactive_vehicle_rejected(self, api):
        """PRD §3.3: "The vehicle must be ACTIVE (otherwise ERR_VEHICLE_NOT_ACTIVE)."
        """
        scenario = setup_basic_scenario(api)
        get_success_data(api.set_vehicle_maintenance(scenario["vehicle"]["id"], ADMIN_HEADERS))
        start, end, _ = future_window(api, offset_minutes=120, duration_minutes=60)
        resp = api.book_practice(create_practice_payload(
            student_id=scenario["student"]["id"],
            instructor_id=scenario["instructor"]["id"],
            vehicle_id=scenario["vehicle"]["id"],
            training_stage="THEORY",
            scheduled_start_at=start,
            scheduled_end_at=end,
        ), ADMIN_HEADERS)
        validate_error(resp, ApiErrorId.ERR_VEHICLE_NOT_ACTIVE.value)


class TestPracticeBookingReferential:

    def test_instructor_not_qualified_rejected(self, api):
        """PRD §3.3: "The vehicle's vehicle_type must be in the instructor's
        vehicle_qualifications set (otherwise ERR_INSTRUCTOR_NOT_QUALIFIED)."
        """
        package = create_default_package(api)
        student, _ = create_active_student(api, package_id=package["id"])
        # Instructor only qualified for AUTO_C2 — but vehicle is MANUAL_C1
        instructor = create_active_instructor(api, vehicle_qualifications=["AUTO_C2"])
        vehicle = create_active_vehicle(api, vehicle_type="MANUAL_C1")
        start, end, _ = future_window(api, offset_minutes=120, duration_minutes=60)
        resp = api.book_practice(create_practice_payload(
            student_id=student["id"], instructor_id=instructor["id"],
            vehicle_id=vehicle["id"], training_stage="THEORY",
            scheduled_start_at=start, scheduled_end_at=end,
        ), ADMIN_HEADERS)
        validate_error(resp, ApiErrorId.ERR_INSTRUCTOR_NOT_QUALIFIED.value)

    def test_theory_stage_cannot_use_motorcycle_e(self, api):
        """PRD §3.3: "a student whose training_stage is THEORY cannot book a
        MOTORCYCLE_E or a TRUCK_B2 vehicle (ERR_VEHICLE_TYPE_MISMATCH)."
        """
        package = create_default_package(api)
        student, _ = create_active_student(api, package_id=package["id"])
        instructor = create_active_instructor(api,
                                               vehicle_qualifications=["MANUAL_C1", "MOTORCYCLE_E"])
        vehicle = create_active_vehicle(api, vehicle_type="MOTORCYCLE_E")
        start, end, _ = future_window(api, offset_minutes=120, duration_minutes=60)
        resp = api.book_practice(create_practice_payload(
            student_id=student["id"], instructor_id=instructor["id"],
            vehicle_id=vehicle["id"], training_stage="THEORY",
            scheduled_start_at=start, scheduled_end_at=end,
        ), ADMIN_HEADERS)
        validate_error(resp, ApiErrorId.ERR_VEHICLE_TYPE_MISMATCH.value)


class TestPracticeBookingTemporal:
    """Calendar conflict checks — instructor closed intervals, vehicle half-open + buffer.
    PRD §3.3.
    """

    def test_instructor_closed_interval_adjacency_conflict(self, api):
        """PRD §3.3: "The instructor calendar is enforced as closed intervals
        [a, b]: a proposed booking [c, d] conflicts with an existing booking
        [a, b] whenever a is at or before d and c is at or before b. Adjacency
        is treated as a conflict — a request whose scheduled_start_at equals an
        existing booking's scheduled_end_at (or vice versa) is rejected with
        ERR_INSTRUCTOR_TIME_CONFLICT."

        # difficulty: resource_temporal_overlap/instructor_calendar_closed_interval_adjacent_conflict
        Claim: closed-interval adjacency at the endpoint counts as overlap.
        """
        package = create_default_package(api)
        s1, _ = create_active_student(api, package_id=package["id"])
        s2, _ = create_active_student(api, package_id=package["id"])
        instructor = create_active_instructor(api)
        v1 = create_active_vehicle(api)
        v2 = create_active_vehicle(api)

        # Practice A at [tomorrow 10:00, tomorrow 11:00]
        now = _server_clock_now(api)
        tomorrow_10 = (now + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)
        tomorrow_11 = tomorrow_10.replace(hour=11)
        tomorrow_12 = tomorrow_10.replace(hour=12)

        a = book_practice_at(api, student=s1, instructor=instructor, vehicle=v1,
                              training_stage="THEORY",
                              start_iso=iso_z(tomorrow_10), end_iso=iso_z(tomorrow_11))
        assert a["status"] == "BOOKED"

        # Practice B at [tomorrow 11:00, tomorrow 12:00] — adjacency on instructor
        resp = api.book_practice(create_practice_payload(
            student_id=s2["id"], instructor_id=instructor["id"], vehicle_id=v2["id"],
            training_stage="THEORY",
            scheduled_start_at=iso_z(tomorrow_11),
            scheduled_end_at=iso_z(tomorrow_12),
        ), ADMIN_HEADERS)
        validate_error(resp, ApiErrorId.ERR_INSTRUCTOR_TIME_CONFLICT.value)

    def test_vehicle_half_open_buffer_conflict(self, api):
        """PRD §3.3: "The vehicle calendar is enforced as half-open intervals
        [a, b) plus a 15-minute cleaning buffer ... vehicle bookings within 15
        minutes of each other are." Vehicle conflicts yield
        ERR_VEHICLE_TIME_CONFLICT.

        # difficulty: resource_temporal_overlap/vehicle_half_open_with_buffer_conflict
        Claim: a 10-minute gap on the same vehicle (below the 15-min buffer)
        is a conflict; instructors are different (so instructor calendar is not
        the gating rule).
        """
        package = create_default_package(api)
        s1, _ = create_active_student(api, package_id=package["id"])
        s2, _ = create_active_student(api, package_id=package["id"])
        i1 = create_active_instructor(api)
        i2 = create_active_instructor(api)
        v = create_active_vehicle(api)

        now = _server_clock_now(api)
        t10 = (now + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)
        t11 = t10.replace(hour=11)
        t11_10 = t10.replace(hour=11, minute=10)  # 10 minutes after t11 → 10-min gap
        t12_10 = t10.replace(hour=12, minute=10)

        a = book_practice_at(api, student=s1, instructor=i1, vehicle=v,
                              training_stage="THEORY",
                              start_iso=iso_z(t10), end_iso=iso_z(t11))
        assert a["status"] == "BOOKED"

        resp = api.book_practice(create_practice_payload(
            student_id=s2["id"], instructor_id=i2["id"], vehicle_id=v["id"],
            training_stage="THEORY",
            scheduled_start_at=iso_z(t11_10),
            scheduled_end_at=iso_z(t12_10),
        ), ADMIN_HEADERS)
        validate_error(resp, ApiErrorId.ERR_VEHICLE_TIME_CONFLICT.value)


class TestPracticeBookingFiscal:

    def test_insufficient_package_balance_rejected(self, api):
        """PRD §3.3: "the student's minutes_remaining_provisional ... must be
        at least zero; otherwise ERR_INSUFFICIENT_PACKAGE_BALANCE."

        Claim: a 60-minute booking from a package with 60 minutes total leaves
        zero remaining; a second 60-minute booking would draw negative.
        """
        package = create_default_package(api,
                                          total_minutes=60,
                                          per_minute_overage_price_cents=200,
                                          included_simulator_sessions=2,
                                          included_exam_attempts=4,
                                          per_simulator_session_overage_price_cents=15000,
                                          total_price_cents=12000)
        student, _ = create_active_student(api, package_id=package["id"])
        instructor = create_active_instructor(api)
        v1 = create_active_vehicle(api)
        v2 = create_active_vehicle(api)

        # First 60-minute booking succeeds
        book_practice(api, student=student, instructor=instructor, vehicle=v1,
                       training_stage="THEORY",
                       start_offset_min=120, duration_min=60)

        # Second booking on a non-overlapping slot would draw the package below 0
        now = _server_clock_now(api)
        t14 = (now + timedelta(days=1)).replace(hour=14, minute=0, second=0, microsecond=0)
        t15 = t14.replace(hour=15)
        resp = api.book_practice(create_practice_payload(
            student_id=student["id"], instructor_id=instructor["id"], vehicle_id=v2["id"],
            training_stage="THEORY",
            scheduled_start_at=iso_z(t14), scheduled_end_at=iso_z(t15),
        ), ADMIN_HEADERS)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PACKAGE_BALANCE.value)


class TestPriorityPairs:
    """PRD §2.8 priority order — when two errors apply, the higher-priority one wins."""

    def test_state_beats_temporal(self, api):
        """PRD §2.8: state (priority 5) beats temporal (priority 7).

        # difficulty: priority_pair_validation_conflict/state_beats_temporal_on_practice_booking
        Setup: book A on instructor I; suspend student; attempt second booking
        that overlaps A on the instructor (would be ERR_INSTRUCTOR_TIME_CONFLICT
        but student is SUSPENDED → ERR_STUDENT_NOT_ACTIVE).
        """
        package = create_default_package(api)
        student, _ = create_active_student(api, package_id=package["id"])
        instructor = create_active_instructor(api)
        v1 = create_active_vehicle(api)
        v2 = create_active_vehicle(api)

        now = _server_clock_now(api)
        t10 = (now + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)
        t11 = t10.replace(hour=11)
        t10_30 = t10.replace(hour=10, minute=30)
        t11_30 = t10.replace(hour=11, minute=30)

        book_practice_at(api, student=student, instructor=instructor, vehicle=v1,
                          training_stage="THEORY",
                          start_iso=iso_z(t10), end_iso=iso_z(t11))

        # Suspend student
        get_success_data(api.suspend_student(student["id"], ADMIN_HEADERS))

        # Attempt overlapping booking — both rules fail; state wins.
        resp = api.book_practice(create_practice_payload(
            student_id=student["id"], instructor_id=instructor["id"], vehicle_id=v2["id"],
            training_stage="THEORY",
            scheduled_start_at=iso_z(t10_30), scheduled_end_at=iso_z(t11_30),
        ), ADMIN_HEADERS)
        validate_error(resp, ApiErrorId.ERR_STUDENT_NOT_ACTIVE.value)

    def test_referential_beats_fiscal(self, api):
        """PRD §2.8: referential (priority 6) beats fiscal (priority 10).

        # difficulty: priority_pair_validation_conflict/referential_beats_fiscal_on_practice_booking
        Setup: small package (60 min); book one practice → 0 minutes left.
        Attempt to book a MOTORCYCLE_E vehicle (THEORY-stage students cannot:
        ERR_VEHICLE_TYPE_MISMATCH) which would also draw negative
        (ERR_INSUFFICIENT_PACKAGE_BALANCE). Referential wins.
        """
        package = create_default_package(api,
                                          total_minutes=60,
                                          per_minute_overage_price_cents=200,
                                          included_simulator_sessions=2,
                                          included_exam_attempts=4,
                                          per_simulator_session_overage_price_cents=15000,
                                          total_price_cents=12000)
        student, _ = create_active_student(api, package_id=package["id"])
        instructor = create_active_instructor(api,
                                               vehicle_qualifications=["MANUAL_C1", "MOTORCYCLE_E"])
        v_manual = create_active_vehicle(api, vehicle_type="MANUAL_C1")
        v_motor = create_active_vehicle(api, vehicle_type="MOTORCYCLE_E")

        # First 60-min booking on manual exhausts package
        book_practice(api, student=student, instructor=instructor, vehicle=v_manual,
                       training_stage="THEORY",
                       start_offset_min=120, duration_min=60)

        # Attempt second booking on MOTORCYCLE_E (THEORY-stage forbidden) AND
        # would also draw package below 0
        now = _server_clock_now(api)
        t14 = (now + timedelta(days=1)).replace(hour=14, minute=0, second=0, microsecond=0)
        t15 = t14.replace(hour=15)
        resp = api.book_practice(create_practice_payload(
            student_id=student["id"], instructor_id=instructor["id"], vehicle_id=v_motor["id"],
            training_stage="THEORY",
            scheduled_start_at=iso_z(t14), scheduled_end_at=iso_z(t15),
        ), ADMIN_HEADERS)
        validate_error(resp, ApiErrorId.ERR_VEHICLE_TYPE_MISMATCH.value)


class TestInstructorDailyLimit:
    """PRD §3.3 instructor safety: daily 480-min cap on provisional sum."""

    def test_instructor_daily_cap_blocks_9th_booking(self, api):
        """PRD §3.3: "The provisional sum of (scheduled_end_at - scheduled_start_at)
        in minutes for this instructor's practices in BOOKED, IN_PROGRESS, or
        COMPLETED falling on the logical clock's calendar date in UTC, plus the
        proposed booking's minutes, must not exceed an 8-hour daily ceiling
        (480 minutes); otherwise ERR_INSTRUCTOR_DAILY_LIMIT_EXCEEDED."

        # difficulty: dual_variant_calc/instructor_working_minutes_provisional_vs_actual
        Claim: provisional accounting sums BOOKED minutes; once at 480, the
        9th 60-min booking is rejected.
        """
        from test_helpers import book_consecutive_practices_today
        package = create_default_package(api,
                                          total_minutes=10000,
                                          per_minute_overage_price_cents=200,
                                          included_simulator_sessions=10,
                                          included_exam_attempts=6,
                                          per_simulator_session_overage_price_cents=15000,
                                          total_price_cents=1000000)
        instructor = create_active_instructor(api)

        # Book 8 × 60-min practices today (480 minutes BOOKED, ZERO checked-in)
        practices, students, vehicles = book_consecutive_practices_today(
            api, instructor=instructor, package=package,
            num_slots=8, slot_minutes=60, gap_minutes=30,
        )
        assert all(p["status"] == "BOOKED" for p in practices)

        # Read instructor — working_minutes_today reflects provisional accounting
        instr = get_success_data(api.get_instructor(instructor["id"], ADMIN_HEADERS))
        assert instr["working_minutes_today"] == 480

        # Try a 9th 60-min booking
        s9, _ = create_active_student(api, package_id=package["id"])
        v9 = create_active_vehicle(api)
        # Place it later today (the same UTC calendar date as the prior 8)
        now = _server_clock_now(api)
        # Last booking ends at base_offset + 8*(60+30) - 30 from now = 60 + 720 - 30 = 750 min from now
        # Pick a slot well after that, but still on the same UTC calendar date.
        # 9th slot starts at offset = 60 + 8*90 - 30 + 30 = 60 + 720 = 780 minutes from now
        last_end_offset = 60 + 8 * (60 + 30) - 30  # 750 min
        next_start_offset = last_end_offset + 30  # 780 min from now
        from test_helpers import iso_z
        from datetime import timedelta
        t_start = now + timedelta(minutes=next_start_offset)
        t_end = t_start + timedelta(minutes=60)

        # Confirm same UTC calendar date (test will skip if timing doesn't permit)
        if t_start.date() != now.date():
            pytest.skip("clock_now near end of day prevents 9-slot single-day fit")

        resp = api.book_practice(create_practice_payload(
            student_id=s9["id"], instructor_id=instructor["id"], vehicle_id=v9["id"],
            training_stage="THEORY",
            scheduled_start_at=iso_z(t_start), scheduled_end_at=iso_z(t_end),
        ), ADMIN_HEADERS)
        validate_error(resp, ApiErrorId.ERR_INSTRUCTOR_DAILY_LIMIT_EXCEEDED.value)
