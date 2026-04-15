"""Tests for Instructor and Student CRUD operations."""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    NON_EXISTENT_UUID,
    api_client, ApiErrorId, TEST_USERS,
    assert_instructor, assert_student,
    create_instructor_payload, create_student_payload,
)
from test_helpers.fixtures import create_semester, create_department, create_instructor, create_student


class TestInstructorCrud:
    """Tests for Instructor registration and retrieval."""

    def test_create_instructor_success(self):
        """Registrar registers an instructor -> 201."""
        semester = create_semester()
        dept = create_department(semester["id"])
        payload = create_instructor_payload(
            dept["id"], employee_number="EMP-001", full_name="Dr. Smith"
        )
        resp = api_client.create_instructor(semester["id"], payload, TEST_USERS["registrar_headers"])
        data = validate_success(resp, expected_status=201)
        assert_instructor(data)
        assert data["employee_number"] == "EMP-001"
        assert data["full_name"] == "Dr. Smith"
        assert data["home_department_id"] == dept["id"]
        assert data["can_approve_cross_dept"] is False, "can_approve_cross_dept defaults to false"

    def test_create_instructor_with_cross_dept_approval(self):
        """Instructor can be created with can_approve_cross_dept=true."""
        semester = create_semester()
        dept = create_department(semester["id"])
        payload = create_instructor_payload(dept["id"], can_approve_cross_dept=True)
        resp = api_client.create_instructor(semester["id"], payload, TEST_USERS["registrar_headers"])
        data = validate_success(resp, expected_status=201)
        assert data["can_approve_cross_dept"] is True

    def test_create_instructor_student_denied(self):
        """Student cannot register instructors -> ENROLLMENT_ROLE_DENIED."""
        semester = create_semester()
        dept = create_department(semester["id"])
        payload = create_instructor_payload(dept["id"])
        resp = api_client.create_instructor(semester["id"], payload, TEST_USERS["student_headers"])
        validate_error(resp, ApiErrorId.ENROLLMENT_ROLE_DENIED)

    def test_create_instructor_professor_denied(self):
        """Professor cannot register instructors -> ENROLLMENT_ROLE_DENIED."""
        semester = create_semester()
        dept = create_department(semester["id"])
        payload = create_instructor_payload(dept["id"])
        resp = api_client.create_instructor(semester["id"], payload, TEST_USERS["professor_headers"])
        validate_error(resp, ApiErrorId.ENROLLMENT_ROLE_DENIED)

    def test_get_instructor_success(self):
        """Get instructor returns correct data."""
        semester = create_semester()
        dept = create_department(semester["id"])
        instructor = create_instructor(semester["id"], dept["id"], full_name="Dr. Jones")
        resp = api_client.get_instructor(semester["id"], instructor["id"], TEST_USERS["registrar_headers"])
        data = validate_success(resp)
        assert data["id"] == instructor["id"]
        assert data["full_name"] == "Dr. Jones"

    def test_get_instructor_not_found(self):
        """Non-existent instructor -> INSTRUCTOR_UNKNOWN."""
        semester = create_semester()
        resp = api_client.get_instructor(semester["id"], NON_EXISTENT_UUID, TEST_USERS["registrar_headers"])
        validate_error(resp, ApiErrorId.INSTRUCTOR_UNKNOWN)

    def test_list_instructors(self):
        """List instructors returns paginated results."""
        semester = create_semester()
        dept = create_department(semester["id"])
        create_instructor(semester["id"], dept["id"])
        resp = api_client.list_instructors(semester["id"], TEST_USERS["registrar_headers"])
        data, meta = validate_paginated(resp)
        assert meta["total_results"] >= 1


class TestStudentCrud:
    """Tests for Student registration and retrieval."""

    def test_create_student_success(self):
        """Registrar registers a student -> 201, correct defaults."""
        semester = create_semester()
        dept = create_department(semester["id"])
        payload = create_student_payload(
            dept["id"], student_number="STU-001", full_name="Alice",
            cumulative_gpa=3.8,
        )
        resp = api_client.create_student(semester["id"], payload, TEST_USERS["registrar_headers"])
        data = validate_success(resp, expected_status=201)
        assert_student(data)
        assert data["student_number"] == "STU-001"
        assert data["full_name"] == "Alice"
        assert data["major_department_id"] == dept["id"]
        assert data["academic_standing"] == "GOOD", "academic_standing defaults to GOOD"
        assert data["cumulative_gpa"] == 3.8
        assert data["max_credits"] == 18, "max_credits defaults to 18"
        assert data["credits_enrolled"] == 0, "credits_enrolled initializes to 0"
        assert data["credits_available"] == 18, "credits_available = max_credits - credits_enrolled"
        assert data["completed_course_ids"] == [], "completed_course_ids defaults to empty"

    def test_create_student_with_overrides(self):
        """Student can be created with non-default values."""
        semester = create_semester()
        dept = create_department(semester["id"])
        payload = create_student_payload(
            dept["id"],
            academic_standing="PROBATION",
            max_credits=12,
            completed_course_ids=["some-course-id"],
        )
        resp = api_client.create_student(semester["id"], payload, TEST_USERS["registrar_headers"])
        data = validate_success(resp, expected_status=201)
        assert data["academic_standing"] == "PROBATION"
        assert data["max_credits"] == 12
        assert data["completed_course_ids"] == ["some-course-id"]

    def test_create_student_professor_denied(self):
        """Professor cannot register students -> ENROLLMENT_ROLE_DENIED."""
        semester = create_semester()
        dept = create_department(semester["id"])
        payload = create_student_payload(dept["id"])
        resp = api_client.create_student(semester["id"], payload, TEST_USERS["professor_headers"])
        validate_error(resp, ApiErrorId.ENROLLMENT_ROLE_DENIED)

    def test_get_student_success(self):
        """Get student returns correct data with credit load."""
        semester = create_semester()
        dept = create_department(semester["id"])
        student = create_student(semester["id"], dept["id"], full_name="Bob")
        resp = api_client.get_student(semester["id"], student["id"], TEST_USERS["registrar_headers"])
        data = validate_success(resp)
        assert data["id"] == student["id"]
        assert data["full_name"] == "Bob"
        assert data["credits_enrolled"] == 0
        assert data["credits_available"] == data["max_credits"]

    def test_get_student_not_found(self):
        """Non-existent student -> STUDENT_UNKNOWN."""
        semester = create_semester()
        resp = api_client.get_student(semester["id"], NON_EXISTENT_UUID, TEST_USERS["registrar_headers"])
        validate_error(resp, ApiErrorId.STUDENT_UNKNOWN)

    def test_update_student_max_credits(self):
        """Registrar can override student max_credits (honors override)."""
        semester = create_semester()
        dept = create_department(semester["id"])
        student = create_student(semester["id"], dept["id"])
        resp = api_client.update_student(
            semester["id"], student["id"],
            {"max_credits": 22}, TEST_USERS["registrar_headers"]
        )
        data = validate_success(resp)
        assert data["max_credits"] == 22
        assert data["credits_available"] == 22, "credits_available recomputed after max_credits change"

    def test_update_student_academic_standing(self):
        """Registrar can update academic_standing."""
        semester = create_semester()
        dept = create_department(semester["id"])
        student = create_student(semester["id"], dept["id"])
        resp = api_client.update_student(
            semester["id"], student["id"],
            {"academic_standing": "PROBATION"}, TEST_USERS["registrar_headers"]
        )
        data = validate_success(resp)
        assert data["academic_standing"] == "PROBATION"

    def test_update_student_completed_course_ids(self):
        """Registrar can update completed_course_ids (transcript)."""
        semester = create_semester()
        dept = create_department(semester["id"])
        course = create_student(semester["id"], dept["id"])
        resp = api_client.update_student(
            semester["id"], course["id"],
            {"completed_course_ids": ["course-a", "course-b"]},
            TEST_USERS["registrar_headers"]
        )
        data = validate_success(resp)
        assert "course-a" in data["completed_course_ids"]
        assert "course-b" in data["completed_course_ids"]

    def test_update_student_professor_denied(self):
        """Professor cannot update student records -> ENROLLMENT_ROLE_DENIED."""
        semester = create_semester()
        dept = create_department(semester["id"])
        student = create_student(semester["id"], dept["id"])
        resp = api_client.update_student(
            semester["id"], student["id"],
            {"max_credits": 22}, TEST_USERS["professor_headers"]
        )
        validate_error(resp, ApiErrorId.ENROLLMENT_ROLE_DENIED)

    def test_list_students(self):
        """List students returns paginated results."""
        semester = create_semester()
        dept = create_department(semester["id"])
        create_student(semester["id"], dept["id"])
        resp = api_client.list_students(semester["id"], TEST_USERS["registrar_headers"])
        data, meta = validate_paginated(resp)
        assert meta["total_results"] >= 1
