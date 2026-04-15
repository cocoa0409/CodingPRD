"""End-to-end integration tests covering full enrollment lifecycle workflows."""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    api_client, ApiErrorId, TEST_USERS,
    create_enrollment_payload,
)
from test_helpers.fixtures import (
    create_semester, create_department, create_instructor, create_course, create_section,
    create_student, create_cross_dept_permission, enroll_student,
)
from prd_bench_local_runner.testing import build_user_headers


class TestFullSemesterLifecycle:
    """End-to-end test of a complete semester lifecycle."""

    def test_complete_semester_lifecycle(self):
        """PLANNING -> OPEN_ENROLLMENT -> enrollment -> CLOSED_ENROLLMENT -> FINALIZED."""
        reg = TEST_USERS["registrar_headers"]
        prof = TEST_USERS["professor_headers"]
        stu = TEST_USERS["student_headers"]

        # 1. Create semester in PLANNING
        from test_helpers.factories import create_semester_payload
        semester_payload = create_semester_payload(term_label="E2E Fall 2026", year=2026)
        resp = api_client.create_semester(semester_payload, reg)
        semester = validate_success(resp, expected_status=201)
        sid = semester["id"]
        assert semester["phase"] == "PLANNING"

        # 2. Set up catalog
        from test_helpers.factories import (
            create_department_payload, create_instructor_payload,
            create_course_payload, create_section_payload, create_student_payload,
        )
        dept_payload = create_department_payload(dept_code="CS", dept_name="Computer Science")
        resp = api_client.create_department(sid, dept_payload, reg)
        dept = validate_success(resp, expected_status=201)

        instr_payload = create_instructor_payload(dept["id"], employee_number="EMP-E2E", full_name="Prof E2E")
        resp = api_client.create_instructor(sid, instr_payload, reg)
        instructor = validate_success(resp, expected_status=201)

        course_payload = create_course_payload(course_code="CS-101", title="Intro CS", credit_hours=3)
        resp = api_client.create_course(sid, dept["id"], course_payload, reg)
        course = validate_success(resp, expected_status=201)

        section_payload = create_section_payload(
            instructor["id"], section_number="001", capacity=2, waitlist_cap=2,
            schedule_days="MWF", schedule_start="09:00", schedule_end="10:00", location="Room-E2E",
        )
        resp = api_client.create_section(sid, dept["id"], course["id"], section_payload, reg)
        section = validate_success(resp, expected_status=201)

        student_payload = create_student_payload(dept["id"], student_number="STU-E2E", cumulative_gpa=3.5)
        resp = api_client.create_student(sid, student_payload, reg)
        student = validate_success(resp, expected_status=201)

        # 3. Open enrollment
        resp = api_client.open_enrollment(sid, reg)
        semester = validate_success(resp)
        assert semester["phase"] == "OPEN_ENROLLMENT"

        # 4. Student enrolls
        enrollment_payload = create_enrollment_payload(student["id"])
        resp = api_client.create_enrollment(sid, dept["id"], course["id"], section["id"], enrollment_payload, stu)
        enrollment = validate_success(resp, expected_status=201)
        assert enrollment["status"] == "ENROLLED"

        # 5. Verify section counters
        resp = api_client.get_section(sid, dept["id"], course["id"], section["id"], reg)
        sec_data = validate_success(resp)
        assert sec_data["seats_enrolled"] == 1
        assert sec_data["seats_available"] == 1

        # 6. Verify student credits
        resp = api_client.get_student(sid, student["id"], reg)
        stu_data = validate_success(resp)
        assert stu_data["credits_enrolled"] == 3
        assert stu_data["credits_available"] == stu_data["max_credits"] - 3

        # 7. Close enrollment
        resp = api_client.close_enrollment(sid, reg)
        semester = validate_success(resp)
        assert semester["phase"] == "CLOSED_ENROLLMENT"

        # 8. Finalize
        resp = api_client.finalize_semester(sid, reg)
        semester = validate_success(resp)
        assert semester["phase"] == "FINALIZED"


class TestApprovalWorkflow:
    """End-to-end test of the approval workflow."""

    def test_full_approval_lifecycle(self):
        """Create enrollment requiring approval -> approve -> verify counters."""
        reg = TEST_USERS["registrar_headers"]
        prof = TEST_USERS["professor_headers"]

        semester = create_semester()
        sid = semester["id"]
        dept = create_department(sid)
        instructor = create_instructor(sid, dept["id"])
        course = create_course(sid, dept["id"], credit_hours=4)
        section = create_section(sid, dept["id"], course["id"], instructor["id"],
                                  requires_approval=True, capacity=30)

        # Open enrollment
        api_client.open_enrollment(sid, reg)

        student = create_student(sid, dept["id"], cumulative_gpa=3.5)

        # Enroll (goes to PENDING_APPROVAL)
        enrollment = enroll_student(sid, dept["id"], course["id"], section["id"], student["id"])
        assert enrollment["status"] == "PENDING_APPROVAL"

        # Credits reserved
        resp = api_client.get_student(sid, student["id"], reg)
        stu = validate_success(resp)
        assert stu["credits_enrolled"] == 4

        # Approve
        resp = api_client.approve_enrollment(
            sid, dept["id"], course["id"], section["id"],
            enrollment["id"], prof, payload={"approval_note": "Approved for E2E"}
        )
        approved = validate_success(resp)
        assert approved["status"] == "ENROLLED"
        assert approved["approval_note"] == "Approved for E2E"

        # Section counters updated
        resp = api_client.get_section(sid, dept["id"], course["id"], section["id"], reg)
        sec = validate_success(resp)
        assert sec["seats_enrolled"] == 1
        assert sec["seats_available"] == 29


class TestWaitlistPromotionCascade:
    """End-to-end test of waitlist promotion when a seat opens."""

    def test_full_waitlist_promotion_lifecycle(self):
        """Fill section -> waitlist -> drop -> promotion -> verify all counters."""
        reg = TEST_USERS["registrar_headers"]

        semester = create_semester()
        sid = semester["id"]
        dept = create_department(sid)
        instructor = create_instructor(sid, dept["id"])
        course = create_course(sid, dept["id"], credit_hours=3)
        section = create_section(sid, dept["id"], course["id"], instructor["id"],
                                  capacity=1, waitlist_cap=3)

        api_client.open_enrollment(sid, reg)

        # Fill the single seat
        s1 = create_student(sid, dept["id"], cumulative_gpa=4.0, max_credits=30)
        e1 = enroll_student(sid, dept["id"], course["id"], section["id"], s1["id"])
        assert e1["status"] == "ENROLLED"

        # Add 2 to waitlist
        s2 = create_student(sid, dept["id"], cumulative_gpa=4.0, max_credits=30)
        e2 = enroll_student(sid, dept["id"], course["id"], section["id"], s2["id"])
        assert e2["status"] == "WAITLISTED"
        assert e2["waitlist_position"] == 1

        s3 = create_student(sid, dept["id"], cumulative_gpa=4.0, max_credits=30)
        e3 = enroll_student(sid, dept["id"], course["id"], section["id"], s3["id"])
        assert e3["status"] == "WAITLISTED"
        assert e3["waitlist_position"] == 2

        # Drop the enrolled student
        api_client.drop_enrollment(sid, dept["id"], course["id"], section["id"], e1["id"], reg)

        # s2 should be promoted
        resp = api_client.get_enrollment(sid, dept["id"], course["id"], section["id"], e2["id"], reg)
        e2_after = validate_success(resp)
        assert e2_after["status"] == "ENROLLED", "First waitlisted student should be promoted"

        # s3 should move up to position 1
        resp = api_client.get_enrollment(sid, dept["id"], course["id"], section["id"], e3["id"], reg)
        e3_after = validate_success(resp)
        assert e3_after["status"] == "WAITLISTED"
        assert e3_after["waitlist_position"] == 1

        # Section counters
        resp = api_client.get_section(sid, dept["id"], course["id"], section["id"], reg)
        sec = validate_success(resp)
        assert sec["seats_enrolled"] == 1
        assert sec["seats_available"] == 0
        assert sec["waitlist_count"] == 1

        # Promoted student credits
        resp = api_client.get_student(sid, s2["id"], reg)
        s2_after = validate_success(resp)
        assert s2_after["credits_enrolled"] == 3

        # Check promotion event exists
        resp = api_client.list_waitlist_promotions(sid, reg)
        data, meta = validate_paginated(resp)
        assert any(p["enrollment_id"] == e2["id"] for p in data), \
            "WaitlistPromotion event should exist for promoted enrollment"


class TestCrossDeptIntegration:
    """End-to-end test of cross-department enrollment workflow."""

    def test_cross_dept_enrollment_full_workflow(self):
        """Grant permission -> enroll cross-dept -> track courses_used -> drop -> verify."""
        reg = TEST_USERS["registrar_headers"]

        semester = create_semester()
        sid = semester["id"]

        # Two departments
        dept_cs = create_department(sid, dept_code="CS", dept_name="Computer Science")
        dept_math = create_department(sid, dept_code="MATH", dept_name="Mathematics")

        instructor_cs = create_instructor(sid, dept_cs["id"])
        instructor_math = create_instructor(sid, dept_math["id"])

        course_math = create_course(sid, dept_math["id"], credit_hours=3, course_code="MATH-E2E")
        section_math = create_section(sid, dept_math["id"], course_math["id"], instructor_math["id"],
                                       schedule_days="TR", schedule_start="11:00", schedule_end="12:00",
                                       location="Math-Hall")

        # Need at least one section in semester for open enrollment
        course_cs = create_course(sid, dept_cs["id"], credit_hours=3, course_code="CS-E2E")
        section_cs = create_section(sid, dept_cs["id"], course_cs["id"], instructor_cs["id"],
                                     schedule_days="MWF", schedule_start="09:00", schedule_end="10:00",
                                     location="CS-Hall")

        api_client.open_enrollment(sid, reg)

        # CS student
        student = create_student(sid, dept_cs["id"], cumulative_gpa=3.5, max_credits=30)

        # Grant permission for MATH dept
        perm = create_cross_dept_permission(sid, student["id"], dept_math["id"], max_courses=2)
        assert perm["courses_used"] == 0

        # Enroll in MATH course
        enrollment = enroll_student(sid, dept_math["id"], course_math["id"], section_math["id"], student["id"])
        assert enrollment["status"] == "ENROLLED"
        assert enrollment["is_cross_dept"] is True

        # courses_used should be 1
        resp = api_client.get_cross_dept_permission(sid, perm["id"], reg)
        perm_after = validate_success(resp)
        assert perm_after["courses_used"] == 1

        # Drop the enrollment
        api_client.drop_enrollment(
            sid, dept_math["id"], course_math["id"], section_math["id"],
            enrollment["id"], reg
        )

        # courses_used should be 0
        resp = api_client.get_cross_dept_permission(sid, perm["id"], reg)
        perm_final = validate_success(resp)
        assert perm_final["courses_used"] == 0
