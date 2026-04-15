"""Tests for Department, Course, and Section CRUD operations."""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    is_valid_uuid, NON_EXISTENT_UUID,
    api_client, ApiErrorId, TEST_USERS,
    assert_department, assert_course, assert_section,
    create_department_payload, create_course_payload, create_section_payload,
)
from test_helpers.fixtures import (
    create_semester, create_department, create_instructor, create_course, create_section,
)


class TestDepartmentCrud:
    """Tests for Department CRUD under a semester."""

    def test_create_department_success(self):
        """Registrar creates a department -> 201, returns dept with correct fields."""
        semester = create_semester()
        payload = create_department_payload(dept_code="CS", dept_name="Computer Science")
        resp = api_client.create_department(semester["id"], payload, TEST_USERS["registrar_headers"])
        data = validate_success(resp, expected_status=201)
        assert_department(data)
        assert data["dept_code"] == "CS"
        assert data["dept_name"] == "Computer Science"
        assert data["cross_dept_open"] is False, "cross_dept_open defaults to false"
        assert data["semester_id"] == semester["id"]

    def test_create_department_with_cross_dept_open(self):
        """Department can be created with cross_dept_open=true."""
        semester = create_semester()
        payload = create_department_payload(dept_code="OPEN", dept_name="Open Dept", cross_dept_open=True)
        resp = api_client.create_department(semester["id"], payload, TEST_USERS["registrar_headers"])
        data = validate_success(resp, expected_status=201)
        assert data["cross_dept_open"] is True

    def test_create_department_semester_not_found(self):
        """Department creation with non-existent semester -> SEMESTER_UNKNOWN."""
        payload = create_department_payload()
        resp = api_client.create_department(NON_EXISTENT_UUID, payload, TEST_USERS["registrar_headers"])
        validate_error(resp, ApiErrorId.SEMESTER_UNKNOWN)

    def test_create_department_student_denied(self):
        """Student cannot create departments -> ENROLLMENT_ROLE_DENIED."""
        semester = create_semester()
        payload = create_department_payload()
        resp = api_client.create_department(semester["id"], payload, TEST_USERS["student_headers"])
        validate_error(resp, ApiErrorId.ENROLLMENT_ROLE_DENIED)

    def test_get_department_success(self):
        """Get department by ID returns correct data."""
        semester = create_semester()
        dept = create_department(semester["id"], dept_code="PHYS", dept_name="Physics")
        resp = api_client.get_department(semester["id"], dept["id"], TEST_USERS["registrar_headers"])
        data = validate_success(resp)
        assert data["id"] == dept["id"]
        assert data["dept_code"] == "PHYS"

    def test_get_department_not_found(self):
        """Non-existent department -> DEPARTMENT_UNKNOWN."""
        semester = create_semester()
        resp = api_client.get_department(semester["id"], NON_EXISTENT_UUID, TEST_USERS["registrar_headers"])
        validate_error(resp, ApiErrorId.DEPARTMENT_UNKNOWN)

    def test_list_departments(self):
        """List departments returns paginated results."""
        semester = create_semester()
        create_department(semester["id"], dept_code="A1", dept_name="Dept A")
        create_department(semester["id"], dept_code="B1", dept_name="Dept B")
        resp = api_client.list_departments(semester["id"], TEST_USERS["registrar_headers"])
        data, meta = validate_paginated(resp)
        assert meta["total_results"] >= 2


class TestCourseCrud:
    """Tests for Course CRUD."""

    def test_create_course_success(self):
        """Registrar creates a course -> 201, correct fields and defaults."""
        semester = create_semester()
        dept = create_department(semester["id"])
        payload = create_course_payload(
            course_code="CS-301", title="Data Structures",
            credit_hours=4, level="ADVANCED",
        )
        resp = api_client.create_course(semester["id"], dept["id"], payload, TEST_USERS["registrar_headers"])
        data = validate_success(resp, expected_status=201)
        assert_course(data)
        assert data["course_code"] == "CS-301"
        assert data["title"] == "Data Structures"
        assert data["credit_hours"] == 4
        assert data["level"] == "ADVANCED"
        assert data["min_gpa"] == 0.0, "min_gpa defaults to 0.0"
        assert data["prerequisite_ids"] == [], "prerequisite_ids defaults to empty"
        assert data["corequisite_ids"] == [], "corequisite_ids defaults to empty"
        assert data["is_active"] is True, "is_active defaults to true"
        assert data["department_id"] == dept["id"]

    def test_create_course_professor_allowed(self):
        """Professor can also create courses (shared operation)."""
        semester = create_semester()
        dept = create_department(semester["id"])
        payload = create_course_payload()
        resp = api_client.create_course(semester["id"], dept["id"], payload, TEST_USERS["professor_headers"])
        data = validate_success(resp, expected_status=201)
        assert_course(data)

    def test_create_course_student_denied(self):
        """Student cannot create courses -> ENROLLMENT_ROLE_DENIED."""
        semester = create_semester()
        dept = create_department(semester["id"])
        payload = create_course_payload()
        resp = api_client.create_course(semester["id"], dept["id"], payload, TEST_USERS["student_headers"])
        validate_error(resp, ApiErrorId.ENROLLMENT_ROLE_DENIED)

    def test_create_course_department_not_found(self):
        """Course creation with non-existent department -> DEPARTMENT_UNKNOWN."""
        semester = create_semester()
        payload = create_course_payload()
        resp = api_client.create_course(semester["id"], NON_EXISTENT_UUID, payload, TEST_USERS["registrar_headers"])
        validate_error(resp, ApiErrorId.DEPARTMENT_UNKNOWN)

    def test_create_course_with_min_gpa(self):
        """Course can specify min_gpa requirement."""
        semester = create_semester()
        dept = create_department(semester["id"])
        payload = create_course_payload(min_gpa=3.0)
        resp = api_client.create_course(semester["id"], dept["id"], payload, TEST_USERS["registrar_headers"])
        data = validate_success(resp, expected_status=201)
        assert data["min_gpa"] == 3.0

    def test_get_course_success(self):
        """Get course returns correct data."""
        semester = create_semester()
        dept = create_department(semester["id"])
        course = create_course(semester["id"], dept["id"], course_code="GET-101", title="Get Course")
        resp = api_client.get_course(semester["id"], dept["id"], course["id"], TEST_USERS["registrar_headers"])
        data = validate_success(resp)
        assert data["id"] == course["id"]
        assert data["course_code"] == "GET-101"

    def test_get_course_not_found(self):
        """Non-existent course -> COURSE_UNKNOWN."""
        semester = create_semester()
        dept = create_department(semester["id"])
        resp = api_client.get_course(semester["id"], dept["id"], NON_EXISTENT_UUID, TEST_USERS["registrar_headers"])
        validate_error(resp, ApiErrorId.COURSE_UNKNOWN)

    def test_update_course_min_gpa(self):
        """Registrar can update a course's min_gpa."""
        semester = create_semester()
        dept = create_department(semester["id"])
        course = create_course(semester["id"], dept["id"])
        resp = api_client.update_course(
            semester["id"], dept["id"], course["id"],
            {"min_gpa": 2.5}, TEST_USERS["registrar_headers"]
        )
        data = validate_success(resp)
        assert data["min_gpa"] == 2.5

    def test_update_course_deactivate(self):
        """Registrar can deactivate a course."""
        semester = create_semester()
        dept = create_department(semester["id"])
        course = create_course(semester["id"], dept["id"])
        resp = api_client.update_course(
            semester["id"], dept["id"], course["id"],
            {"is_active": False}, TEST_USERS["registrar_headers"]
        )
        data = validate_success(resp)
        assert data["is_active"] is False

    def test_list_courses(self):
        """List courses returns paginated results."""
        semester = create_semester()
        dept = create_department(semester["id"])
        create_course(semester["id"], dept["id"])
        resp = api_client.list_courses(semester["id"], dept["id"], TEST_USERS["registrar_headers"])
        data, meta = validate_paginated(resp)
        assert meta["total_results"] >= 1


class TestSectionCrud:
    """Tests for Section CRUD."""

    def test_create_section_success(self):
        """Create section with correct initial computed fields."""
        semester = create_semester()
        dept = create_department(semester["id"])
        instructor = create_instructor(semester["id"], dept["id"])
        course = create_course(semester["id"], dept["id"])
        payload = create_section_payload(
            instructor["id"],
            section_number="001", capacity=30, waitlist_cap=5,
            schedule_days="MWF", schedule_start="09:00", schedule_end="10:00",
            location="Hall-A",
        )
        resp = api_client.create_section(
            semester["id"], dept["id"], course["id"], payload, TEST_USERS["registrar_headers"]
        )
        data = validate_success(resp, expected_status=201)
        assert_section(data)
        assert data["section_number"] == "001"
        assert data["capacity"] == 30
        assert data["waitlist_cap"] == 5
        assert data["seats_enrolled"] == 0, "seats_enrolled initializes to 0"
        assert data["seats_available"] == 30, "seats_available initializes to capacity"
        assert data["waitlist_count"] == 0, "waitlist_count initializes to 0"
        assert data["enrollment_seq"] == 1, "enrollment_seq starts at 1"
        assert data["requires_approval"] is False, "requires_approval defaults to false"
        assert data["course_id"] == course["id"]

    def test_create_section_default_waitlist_cap(self):
        """Waitlist cap defaults to 10 when not specified."""
        semester = create_semester()
        dept = create_department(semester["id"])
        instructor = create_instructor(semester["id"], dept["id"])
        course = create_course(semester["id"], dept["id"])
        payload = create_section_payload(instructor["id"])
        # Remove waitlist_cap so default applies
        payload.pop("waitlist_cap", None)
        resp = api_client.create_section(
            semester["id"], dept["id"], course["id"], payload, TEST_USERS["registrar_headers"]
        )
        data = validate_success(resp, expected_status=201)
        assert data["waitlist_cap"] == 10, "waitlist_cap should default to 10"

    def test_create_section_requires_approval(self):
        """Section can be created with requires_approval=true."""
        semester = create_semester()
        dept = create_department(semester["id"])
        instructor = create_instructor(semester["id"], dept["id"])
        course = create_course(semester["id"], dept["id"])
        payload = create_section_payload(instructor["id"], requires_approval=True)
        resp = api_client.create_section(
            semester["id"], dept["id"], course["id"], payload, TEST_USERS["registrar_headers"]
        )
        data = validate_success(resp, expected_status=201)
        assert data["requires_approval"] is True

    def test_create_section_inactive_course(self):
        """Cannot create section for inactive course -> COURSE_INACTIVE."""
        semester = create_semester()
        dept = create_department(semester["id"])
        instructor = create_instructor(semester["id"], dept["id"])
        course = create_course(semester["id"], dept["id"])
        # Deactivate the course
        api_client.update_course(
            semester["id"], dept["id"], course["id"],
            {"is_active": False}, TEST_USERS["registrar_headers"]
        )
        payload = create_section_payload(instructor["id"])
        resp = api_client.create_section(
            semester["id"], dept["id"], course["id"], payload, TEST_USERS["registrar_headers"]
        )
        validate_error(resp, ApiErrorId.COURSE_INACTIVE)

    def test_create_section_professor_allowed(self):
        """Professor can create sections (shared operation)."""
        semester = create_semester()
        dept = create_department(semester["id"])
        instructor = create_instructor(semester["id"], dept["id"])
        course = create_course(semester["id"], dept["id"])
        payload = create_section_payload(instructor["id"])
        resp = api_client.create_section(
            semester["id"], dept["id"], course["id"], payload, TEST_USERS["professor_headers"]
        )
        data = validate_success(resp, expected_status=201)
        assert_section(data)

    def test_create_section_student_denied(self):
        """Student cannot create sections -> ENROLLMENT_ROLE_DENIED."""
        semester = create_semester()
        dept = create_department(semester["id"])
        instructor = create_instructor(semester["id"], dept["id"])
        course = create_course(semester["id"], dept["id"])
        payload = create_section_payload(instructor["id"])
        resp = api_client.create_section(
            semester["id"], dept["id"], course["id"], payload, TEST_USERS["student_headers"]
        )
        validate_error(resp, ApiErrorId.ENROLLMENT_ROLE_DENIED)

    def test_get_section_success(self):
        """Get section returns correct live capacity counts."""
        semester = create_semester()
        dept = create_department(semester["id"])
        instructor = create_instructor(semester["id"], dept["id"])
        course = create_course(semester["id"], dept["id"])
        section = create_section(semester["id"], dept["id"], course["id"], instructor["id"], capacity=25)
        resp = api_client.get_section(
            semester["id"], dept["id"], course["id"], section["id"], TEST_USERS["registrar_headers"]
        )
        data = validate_success(resp)
        assert data["id"] == section["id"]
        assert data["seats_available"] == 25

    def test_get_section_not_found(self):
        """Non-existent section -> SECTION_UNKNOWN."""
        semester = create_semester()
        dept = create_department(semester["id"])
        course = create_course(semester["id"], dept["id"])
        resp = api_client.get_section(
            semester["id"], dept["id"], course["id"], NON_EXISTENT_UUID, TEST_USERS["registrar_headers"]
        )
        validate_error(resp, ApiErrorId.SECTION_UNKNOWN)

    def test_update_section_capacity(self):
        """Registrar can update section capacity."""
        semester = create_semester()
        dept = create_department(semester["id"])
        instructor = create_instructor(semester["id"], dept["id"])
        course = create_course(semester["id"], dept["id"])
        section = create_section(semester["id"], dept["id"], course["id"], instructor["id"], capacity=20)
        resp = api_client.update_section(
            semester["id"], dept["id"], course["id"], section["id"],
            {"capacity": 35}, TEST_USERS["registrar_headers"]
        )
        data = validate_success(resp)
        assert data["capacity"] == 35
        assert data["seats_available"] == 35, "seats_available should reflect new capacity with 0 enrolled"

    def test_list_sections(self):
        """List sections returns paginated results."""
        semester = create_semester()
        dept = create_department(semester["id"])
        instructor = create_instructor(semester["id"], dept["id"])
        course = create_course(semester["id"], dept["id"])
        create_section(semester["id"], dept["id"], course["id"], instructor["id"])
        resp = api_client.list_sections(
            semester["id"], dept["id"], course["id"], TEST_USERS["registrar_headers"]
        )
        data, meta = validate_paginated(resp)
        assert meta["total_results"] >= 1
