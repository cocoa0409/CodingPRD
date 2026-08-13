"""Group programs: enrollment gates, risk ceilings, waitlists, lifecycle."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_clock,
    api_client,
    create_counselor,
    create_group_program,
    create_intake,
    create_open_program,
    create_student,
    enroll_student,
    make_counselor_headers,
    make_student_headers,
    publish_program,
    validate_error,
    validate_paginated,
    validate_success,
)

FD = TEST_USERS["front_desk_headers"]


class TestEnrollmentGates:

    def test_enroll_into_draft_program_rejected(self):
        """PRD section 3.8: "Enrolling a `student_id` into a program that is
        not `OPEN` is rejected outright with `ERR_PROGRAM_NOT_OPEN`."
        PRD section 3.8: "a student with no intake assessment on file is
        treated as `LOW` — no clinical contraindication exists."

        The student carries no clinical contraindication, so the rejection is
        purely the program-state gate.

        Design: Corner/errors/error_program_not_open_on_draft_enrollment
        """
        counselor = create_counselor(license_id="LIC-R1")
        program = create_group_program(
            counselor["id"], title="Draft Group", meeting_day="FRI",
            starts_at="2026-09-01T17:00:00Z", weeks=4,
            risk_band_ceiling="MODERATE")
        student = create_student("R100", "Draft Enroll")
        resp = api_client.enroll_in_group_program(
            program["id"], {"student_id": student["id"]}, FD)
        validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_OPEN)

    def test_critical_student_into_draft_program_reports_risk_violation(self):
        """PRD section 3.8: "A student whose band exceeds the program's
        `risk_band_ceiling` is rejected with `ERR_RISK_BAND_VIOLATION`, and
        `CRITICAL` students are never group-eligible regardless of the
        ceiling."
        PRD section 2.8: "Domain gates, evaluated in this exact order: the
        clinical-safety gate (`ERR_RISK_BAND_VIOLATION`); the confidentiality
        wall (`ERR_CONFIDENTIALITY_VIOLATION`); uniqueness (`ERR_DUPLICATE`);
        schedule overlap (`ERR_SCHEDULE_CONFLICT`); single-room serialization
        (`ERR_ROOM_OCCUPIED`); the booking-posture gate
        (`ERR_BOOKING_SUSPENDED`); the session-limit gate
        (`ERR_SESSION_LIMIT_REACHED`); counselor capacity
        (`ERR_COUNSELOR_OVER_CAPACITY`); group-program openness
        (`ERR_PROGRAM_NOT_OPEN`); temporal validity (`ERR_TEMPORAL_INVALID`);
        optimistic concurrency (`ERR_STALE_VERSION`); and finally
        policy-lifecycle conflicts (`ERR_POLICY_CONFLICT`)."

        Both gates are breached (CRITICAL band; DRAFT program); the safety
        gate is evaluated first, so ERR_RISK_BAND_VIOLATION surfaces.

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_referential_on_group_enrollment
        """
        counselor = create_counselor(license_id="LIC-10")
        student = create_student("S1000", "Crit Stud")
        intake = create_intake(student["id"], counselor["id"],
                               phq9=15, gad7=5, attempt=True)  # 60 -> CRITICAL
        assert intake["risk_points"] == 60
        assert intake["risk_band"] == "CRITICAL"
        program = create_group_program(
            counselor["id"], title="Stress Mgmt", capacity=6,
            risk_band_ceiling="HIGH")  # stays DRAFT
        resp = api_client.enroll_in_group_program(
            program["id"], {"student_id": student["id"]}, FD)
        validate_error(resp, ApiErrorId.ERR_RISK_BAND_VIOLATION)

    def test_high_student_into_draft_program_reports_program_not_open(self):
        """PRD section 3.8: "Enrolling a `student_id` into a program that is
        not `OPEN` is rejected outright with `ERR_PROGRAM_NOT_OPEN`."

        A HIGH student is within the HIGH ceiling (inclusive), so the safety
        gate passes and the program-state gate is the one that fires — the
        complement arm proving both gates were live in the dual-failure case.

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_referential_on_group_enrollment
        """
        counselor = create_counselor(license_id="LIC-10")
        student = create_student("S1001", "High Stud")
        intake = create_intake(student["id"], counselor["id"],
                               phq9=20, gad7=20)  # 40 -> HIGH
        assert intake["risk_band"] == "HIGH"
        program = create_group_program(
            counselor["id"], title="Stress Mgmt", capacity=6,
            risk_band_ceiling="HIGH")  # stays DRAFT
        resp = api_client.enroll_in_group_program(
            program["id"], {"student_id": student["id"]}, FD)
        validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_OPEN)


class TestWaitlistPromotion:

    def test_waitlist_head_promoted_on_drop(self):
        """PRD section 3.8: "Capacity itself is not an error: when the
        `ENROLLED` count has reached `capacity`, the new enrollment simply
        lands in `WAITLISTED` instead of `ENROLLED`."
        PRD section 3.8: "Either way, a freed seat promotes the waitlist head
        to `ENROLLED`: the waitlisted enrollment with the earliest
        `created_at` wins; a tie on `created_at` is never broken by id —
        instead the enrollment whose student carries the lower current
        `no_show_strike_count` promotes first, and a further tie resolves by
        the student's own `created_at`, earliest first."

        Design: Corner/state_machines/group_enrollment_waitlist_promotion_order
        """
        counselor = create_counselor(license_id="LIC-S2")
        program = create_open_program(
            counselor["id"], title="Tiny Group", capacity=1,
            meeting_day="WED", starts_at="2026-09-01T17:00:00Z", weeks=6,
            risk_band_ceiling="HIGH")
        s_a = create_student("SG101", "Stud A")
        s_b = create_student("SG102", "Stud B")
        enr_a = enroll_student(program["id"], s_a["id"])
        enr_b = enroll_student(program["id"], s_b["id"])
        assert enr_a["status"] == "ENROLLED"
        assert enr_b["status"] == "WAITLISTED", \
            "over-capacity enrollment lands in WAITLISTED, not an error"
        dropped = validate_success(api_client.drop_group_enrollment(
            enr_a["id"], make_student_headers(s_a["id"])))
        assert dropped["status"] == "DROPPED"
        enrollments, _m = validate_paginated(
            api_client.list_group_enrollments(
                FD, params={"program_id": program["id"]}))
        by_id = {e["id"]: e for e in enrollments}
        assert by_id[enr_b["id"]]["status"] == "ENROLLED", \
            "the earliest-created waitlisted enrollment promotes"


class TestProgramClockTransitions:

    def test_program_auto_running_and_completed_by_clock(self):
        """PRD section 3.8: "When the logical clock reaches the program's
        start and at least one enrollment sits in `ENROLLED`, the program
        auto-transitions to `RUNNING`; when the clock passes the full run —
        the start plus `weeks` times seven days — it auto-transitions to
        `COMPLETED`."

        Design: Corner/state_machines/group_program_auto_running_and_completed_by_clock
        """
        counselor = create_counselor(license_id="LIC-S8")
        program = create_open_program(
            counselor["id"], title="Auto Group", capacity=5, meeting_day="MON",
            starts_at="2026-08-02T17:00:00Z", weeks=2,
            risk_band_ceiling="MODERATE")
        student = create_student("SS800", "Grp Stud")
        enroll_student(program["id"], student["id"])
        c_headers = make_counselor_headers(counselor["id"])
        advance_clock("2026-08-03T00:00:00Z")
        mid = validate_success(api_client.get_group_program(
            program["id"], c_headers))
        assert mid["status"] == "RUNNING", \
            f"past start with an enrollee must be RUNNING, got {mid['status']}"
        # Start + 2 weeks * 7 days = 2026-08-16T17:00:00Z.
        advance_clock("2026-08-20T00:00:00Z")
        end = validate_success(api_client.get_group_program(
            program["id"], c_headers))
        assert end["status"] == "COMPLETED", \
            f"past the full run must be COMPLETED, got {end['status']}"
