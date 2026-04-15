"""Tests for dropping, withdrawal, and waitlist promotion cascade."""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    api_client, ApiErrorId, TEST_USERS,
    create_enrollment_payload,
)
from test_helpers.fixtures import (
    setup_enrollment_ready, create_student, create_course, create_section,
    create_semester_in_open_enrollment, enroll_student, drop_enrollment,
    setup_waitlist_promotion_scenario, setup_approval_required_scenario,
)


class TestDropFromEnrolled:
    """Tests for dropping an ENROLLED enrollment."""

    def test_drop_enrolled_success(self):
        """Student drops ENROLLED enrollment -> DROPPED, 200."""
        ctx = setup_enrollment_ready()
        enrollment = enroll_student(
            ctx["semester_id"], ctx["department_id"], ctx["course_id"],
            ctx["section_id"], ctx["student_id"]
        )
        resp = api_client.drop_enrollment(
            ctx["semester_id"], ctx["department_id"], ctx["course_id"],
            ctx["section_id"], enrollment["id"], TEST_USERS["student_headers"]
        )
        data = validate_success(resp)
        assert data["status"] == "DROPPED"
        assert data["dropped_on"] is not None, "dropped_on should be set"

    def test_drop_frees_seat(self):
        """Dropping from ENROLLED increments seats_available."""
        ctx = setup_enrollment_ready()
        enrollment = enroll_student(
            ctx["semester_id"], ctx["department_id"], ctx["course_id"],
            ctx["section_id"], ctx["student_id"]
        )

        resp = api_client.get_section(
            ctx["semester_id"], ctx["department_id"], ctx["course_id"],
            ctx["section_id"], TEST_USERS["registrar_headers"]
        )
        before = validate_success(resp)

        drop_enrollment(
            ctx["semester_id"], ctx["department_id"], ctx["course_id"],
            ctx["section_id"], enrollment["id"]
        )

        resp = api_client.get_section(
            ctx["semester_id"], ctx["department_id"], ctx["course_id"],
            ctx["section_id"], TEST_USERS["registrar_headers"]
        )
        after = validate_success(resp)
        assert after["seats_enrolled"] == before["seats_enrolled"] - 1
        assert after["seats_available"] == before["seats_available"] + 1

    def test_drop_releases_credits(self):
        """Dropping from ENROLLED releases credits from student's load."""
        ctx = setup_enrollment_ready()
        credit_hours = ctx["course"]["credit_hours"]
        enrollment = enroll_student(
            ctx["semester_id"], ctx["department_id"], ctx["course_id"],
            ctx["section_id"], ctx["student_id"]
        )

        drop_enrollment(
            ctx["semester_id"], ctx["department_id"], ctx["course_id"],
            ctx["section_id"], enrollment["id"]
        )

        resp = api_client.get_student(ctx["semester_id"], ctx["student_id"], TEST_USERS["registrar_headers"])
        student = validate_success(resp)
        assert student["credits_enrolled"] == 0
        assert student["credits_available"] == student["max_credits"]

    def test_drop_registrar_allowed(self):
        """Registrar can drop student's enrollment."""
        ctx = setup_enrollment_ready()
        enrollment = enroll_student(
            ctx["semester_id"], ctx["department_id"], ctx["course_id"],
            ctx["section_id"], ctx["student_id"]
        )
        resp = api_client.drop_enrollment(
            ctx["semester_id"], ctx["department_id"], ctx["course_id"],
            ctx["section_id"], enrollment["id"], TEST_USERS["registrar_headers"]
        )
        data = validate_success(resp)
        assert data["status"] == "DROPPED"


class TestDropFromWaitlisted:
    """Tests for dropping a WAITLISTED enrollment."""

    def test_drop_waitlisted_success(self):
        """Drop from WAITLISTED -> DROPPED, waitlist_count decreases."""
        scenario = setup_waitlist_promotion_scenario(capacity=1, waitlist_count=2)
        sid = scenario["semester_id"]
        wl = scenario["waitlisted"]
        enrollment_to_drop = wl[0]["enrollment"]

        resp = api_client.drop_enrollment(
            sid, scenario["department_id"], scenario["course_id"],
            scenario["section_id"], enrollment_to_drop["id"], TEST_USERS["student_headers"]
        )
        data = validate_success(resp)
        assert data["status"] == "DROPPED"

    def test_drop_waitlisted_reorders_positions(self):
        """Dropping from waitlist shifts down all higher positions by 1."""
        scenario = setup_waitlist_promotion_scenario(capacity=1, waitlist_count=3)
        sid = scenario["semester_id"]
        wl = scenario["waitlisted"]

        # Drop the first waitlisted student (position 1)
        api_client.drop_enrollment(
            sid, scenario["department_id"], scenario["course_id"],
            scenario["section_id"], wl[0]["enrollment"]["id"], TEST_USERS["student_headers"]
        )

        # The second waitlisted student should now be position 1
        resp = api_client.get_enrollment(
            sid, scenario["department_id"], scenario["course_id"],
            scenario["section_id"], wl[1]["enrollment"]["id"], TEST_USERS["registrar_headers"]
        )
        data = validate_success(resp)
        assert data["waitlist_position"] == 1, \
            f"Expected position 1 after drop, got {data['waitlist_position']}"

        # The third should be position 2
        resp = api_client.get_enrollment(
            sid, scenario["department_id"], scenario["course_id"],
            scenario["section_id"], wl[2]["enrollment"]["id"], TEST_USERS["registrar_headers"]
        )
        data = validate_success(resp)
        assert data["waitlist_position"] == 2, \
            f"Expected position 2 after drop, got {data['waitlist_position']}"


class TestDropFromPendingApproval:
    """Tests for dropping a PENDING_APPROVAL enrollment."""

    def test_drop_pending_approval_success(self):
        """Student can drop a PENDING_APPROVAL enrollment -> DROPPED, credits released."""
        ctx = setup_approval_required_scenario()
        enrollment = enroll_student(
            ctx["semester_id"], ctx["department_id"], ctx["course_id"],
            ctx["section_id"], ctx["student_id"]
        )
        assert enrollment["status"] == "PENDING_APPROVAL"

        resp = api_client.drop_enrollment(
            ctx["semester_id"], ctx["department_id"], ctx["course_id"],
            ctx["section_id"], enrollment["id"], TEST_USERS["student_headers"]
        )
        data = validate_success(resp)
        assert data["status"] == "DROPPED"

        # Credits released
        resp = api_client.get_student(ctx["semester_id"], ctx["student_id"], TEST_USERS["registrar_headers"])
        student = validate_success(resp)
        assert student["credits_enrolled"] == 0


class TestDropInvalidStates:
    """Tests for dropping from invalid states."""

    def test_drop_already_dropped(self):
        """Cannot drop an already-dropped enrollment -> ENROLLMENT_STATE_INVALID."""
        ctx = setup_enrollment_ready()
        enrollment = enroll_student(
            ctx["semester_id"], ctx["department_id"], ctx["course_id"],
            ctx["section_id"], ctx["student_id"]
        )
        drop_enrollment(
            ctx["semester_id"], ctx["department_id"], ctx["course_id"],
            ctx["section_id"], enrollment["id"]
        )
        resp = api_client.drop_enrollment(
            ctx["semester_id"], ctx["department_id"], ctx["course_id"],
            ctx["section_id"], enrollment["id"], TEST_USERS["student_headers"]
        )
        validate_error(resp, ApiErrorId.ENROLLMENT_STATE_INVALID)

    def test_drop_professor_denied(self):
        """Professor cannot drop enrollments -> ENROLLMENT_ROLE_DENIED."""
        ctx = setup_enrollment_ready()
        enrollment = enroll_student(
            ctx["semester_id"], ctx["department_id"], ctx["course_id"],
            ctx["section_id"], ctx["student_id"]
        )
        resp = api_client.drop_enrollment(
            ctx["semester_id"], ctx["department_id"], ctx["course_id"],
            ctx["section_id"], enrollment["id"], TEST_USERS["professor_headers"]
        )
        validate_error(resp, ApiErrorId.ENROLLMENT_ROLE_DENIED)


class TestWaitlistPromotion:
    """Tests for automatic waitlist promotion when a seat opens."""

    def test_drop_triggers_waitlist_promotion(self):
        """Dropping from ENROLLED promotes the top waitlisted student to ENROLLED."""
        scenario = setup_waitlist_promotion_scenario(capacity=1, waitlist_count=2)
        sid = scenario["semester_id"]
        enrolled = scenario["enrolled"][0]
        wl = scenario["waitlisted"]

        # Drop the enrolled student
        api_client.drop_enrollment(
            sid, scenario["department_id"], scenario["course_id"],
            scenario["section_id"], enrolled["enrollment"]["id"], TEST_USERS["student_headers"]
        )

        # First waitlisted student should now be ENROLLED
        resp = api_client.get_enrollment(
            sid, scenario["department_id"], scenario["course_id"],
            scenario["section_id"], wl[0]["enrollment"]["id"], TEST_USERS["registrar_headers"]
        )
        promoted = validate_success(resp)
        assert promoted["status"] == "ENROLLED", \
            "Top waitlisted student should be promoted to ENROLLED after drop"

        # Second waitlisted student remains WAITLISTED with position 1
        resp = api_client.get_enrollment(
            sid, scenario["department_id"], scenario["course_id"],
            scenario["section_id"], wl[1]["enrollment"]["id"], TEST_USERS["registrar_headers"]
        )
        remaining = validate_success(resp)
        assert remaining["status"] == "WAITLISTED"
        assert remaining["waitlist_position"] == 1, \
            "Remaining waitlisted student should shift down to position 1"

    def test_promotion_creates_event(self):
        """Waitlist promotion creates a WaitlistPromotion event record."""
        scenario = setup_waitlist_promotion_scenario(capacity=1, waitlist_count=1)
        sid = scenario["semester_id"]
        enrolled = scenario["enrolled"][0]

        # Drop to trigger promotion
        api_client.drop_enrollment(
            sid, scenario["department_id"], scenario["course_id"],
            scenario["section_id"], enrolled["enrollment"]["id"], TEST_USERS["student_headers"]
        )

        # Check promotion events
        resp = api_client.list_waitlist_promotions(sid, TEST_USERS["registrar_headers"])
        data, meta = validate_paginated(resp)
        assert len(data) >= 1, "At least one WaitlistPromotion event should exist"
        promo = data[0]
        assert promo["enrollment_id"] == scenario["waitlisted"][0]["enrollment"]["id"]
        assert promo["section_id"] == scenario["section_id"]
        assert promo["previous_position"] == 1

    def test_promotion_updates_section_counters(self):
        """After waitlist promotion, section counters are correct."""
        scenario = setup_waitlist_promotion_scenario(capacity=1, waitlist_count=1)
        sid = scenario["semester_id"]
        enrolled = scenario["enrolled"][0]

        api_client.drop_enrollment(
            sid, scenario["department_id"], scenario["course_id"],
            scenario["section_id"], enrolled["enrollment"]["id"], TEST_USERS["student_headers"]
        )

        resp = api_client.get_section(
            sid, scenario["department_id"], scenario["course_id"],
            scenario["section_id"], TEST_USERS["registrar_headers"]
        )
        section = validate_success(resp)
        # Promoted student fills the seat, so seats_enrolled=1, seats_available=0
        assert section["seats_enrolled"] == 1, \
            f"Expected seats_enrolled=1 after promotion, got {section['seats_enrolled']}"
        assert section["seats_available"] == 0
        assert section["waitlist_count"] == 0

    def test_promotion_updates_student_credits(self):
        """Promoted student's credits_enrolled increases."""
        scenario = setup_waitlist_promotion_scenario(capacity=1, waitlist_count=1)
        sid = scenario["semester_id"]
        enrolled = scenario["enrolled"][0]
        wl_student = scenario["waitlisted"][0]["student"]

        # Get credits before promotion
        resp = api_client.get_student(sid, wl_student["id"], TEST_USERS["registrar_headers"])
        before = validate_success(resp)

        api_client.drop_enrollment(
            sid, scenario["department_id"], scenario["course_id"],
            scenario["section_id"], enrolled["enrollment"]["id"], TEST_USERS["student_headers"]
        )

        resp = api_client.get_student(sid, wl_student["id"], TEST_USERS["registrar_headers"])
        after = validate_success(resp)
        # Credits should increase by course credit_hours (3)
        assert after["credits_enrolled"] == before["credits_enrolled"] + scenario["course"]["credit_hours"]

    def test_capacity_increase_triggers_promotion(self):
        """Increasing section capacity triggers waitlist promotion for each new seat."""
        scenario = setup_waitlist_promotion_scenario(capacity=1, waitlist_count=2)
        sid = scenario["semester_id"]

        # Increase capacity by 2 (1 existing seat filled + 2 new = 3 total)
        resp = api_client.update_section(
            sid, scenario["department_id"], scenario["course_id"],
            scenario["section_id"],
            {"capacity": 3}, TEST_USERS["registrar_headers"]
        )
        validate_success(resp)

        # Both waitlisted students should now be ENROLLED
        for wl in scenario["waitlisted"]:
            resp = api_client.get_enrollment(
                sid, scenario["department_id"], scenario["course_id"],
                scenario["section_id"], wl["enrollment"]["id"], TEST_USERS["registrar_headers"]
            )
            data = validate_success(resp)
            assert data["status"] == "ENROLLED", \
                f"Waitlisted student should be promoted after capacity increase, got {data['status']}"


class TestWithdraw:
    """Tests for late withdrawal (registrar only)."""

    def test_withdraw_registrar_only(self):
        """Student cannot withdraw -> ENROLLMENT_ROLE_DENIED."""
        ctx = setup_enrollment_ready()
        enrollment = enroll_student(
            ctx["semester_id"], ctx["department_id"], ctx["course_id"],
            ctx["section_id"], ctx["student_id"]
        )
        resp = api_client.withdraw_enrollment(
            ctx["semester_id"], ctx["department_id"], ctx["course_id"],
            ctx["section_id"], enrollment["id"], TEST_USERS["student_headers"]
        )
        validate_error(resp, ApiErrorId.ENROLLMENT_ROLE_DENIED)

    def test_withdraw_wrong_status(self):
        """Cannot withdraw from WAITLISTED -> ENROLLMENT_STATE_INVALID."""
        scenario = setup_waitlist_promotion_scenario(capacity=1, waitlist_count=1)
        sid = scenario["semester_id"]
        wl = scenario["waitlisted"][0]

        resp = api_client.withdraw_enrollment(
            sid, scenario["department_id"], scenario["course_id"],
            scenario["section_id"], wl["enrollment"]["id"], TEST_USERS["registrar_headers"]
        )
        validate_error(resp, ApiErrorId.ENROLLMENT_STATE_INVALID)

    def test_withdraw_triggers_promotion(self):
        """Withdrawal frees a seat and triggers waitlist promotion."""
        scenario = setup_waitlist_promotion_scenario(capacity=1, waitlist_count=1)
        sid = scenario["semester_id"]
        enrolled = scenario["enrolled"][0]

        # Withdraw the enrolled student (registrar)
        resp = api_client.withdraw_enrollment(
            sid, scenario["department_id"], scenario["course_id"],
            scenario["section_id"], enrolled["enrollment"]["id"], TEST_USERS["registrar_headers"]
        )
        data = validate_success(resp)
        assert data["status"] == "WITHDRAWN"

        # Waitlisted student should be promoted
        resp = api_client.get_enrollment(
            sid, scenario["department_id"], scenario["course_id"],
            scenario["section_id"], scenario["waitlisted"][0]["enrollment"]["id"],
            TEST_USERS["registrar_headers"]
        )
        promoted = validate_success(resp)
        assert promoted["status"] == "ENROLLED"
