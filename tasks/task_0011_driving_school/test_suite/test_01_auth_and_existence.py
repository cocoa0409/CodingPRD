"""Auth headers, role permissions, and resource existence checks (PRD §2.1, §2.7, §2.8)."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    validate_error,
    ApiErrorId,
    create_student_payload,
    create_default_package,
    create_active_student,
    create_active_instructor,
    create_active_vehicle,
    setup_basic_scenario,
    TEST_USERS,
    make_student_headers,
    ADMIN_HEADERS,
)


# ---------- Missing/empty auth headers ----------

class TestMissingAuthHeaders:
    """PRD §2.1: "If either is missing or empty, the request is rejected with
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER and HTTP 400."
    """

    def test_create_student_no_headers_rejected(self, api):
        """PRD §2.1: ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER when X-User-ID or X-User-Role missing."""
        resp = api.create_student(create_student_payload(), headers={"Content-Type": "application/json"})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value)

    def test_create_student_empty_user_id_rejected(self, api):
        """PRD §2.1: empty X-User-ID is treated as missing."""
        resp = api.create_student(create_student_payload(),
                                    headers={"X-User-ID": "", "X-User-Role": "Admin",
                                             "Content-Type": "application/json"})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value)

    def test_create_student_empty_role_rejected(self, api):
        """PRD §2.1: empty X-User-Role is treated as missing."""
        resp = api.create_student(create_student_payload(),
                                    headers={"X-User-ID": "admin-001", "X-User-Role": "",
                                             "Content-Type": "application/json"})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value)


# ---------- Insufficient permissions ----------

class TestInsufficientPermissions:
    """PRD §2.1: "If the role is present but lacks permission for the requested
    operation per the role-to-endpoint matrix described throughout §3 and
    summarised in §4, the request is rejected with ERR_INSUFFICIENT_PERMISSIONS
    and HTTP 403."
    """

    def test_student_cannot_create_student(self, api):
        """PRD §4: POST /students authorised role: Admin only."""
        resp = api.create_student(create_student_payload(),
                                    TEST_USERS["student_headers"])
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)

    def test_instructor_cannot_create_instructor(self, api):
        """PRD §4: POST /instructors authorised role: Admin only."""
        resp = api.create_instructor({"full_name": "X", "license_number": "L",
                                        "vehicle_qualifications": ["MANUAL_C1"]},
                                       TEST_USERS["instructor_headers"])
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)

    def test_student_cannot_book_exam(self, api):
        """PRD §4: POST /exam-appointments authorised role: Admin only."""
        scenario = setup_basic_scenario(api)
        student = scenario["student"]
        # Student attempts to book their own exam — but role is admin-only.
        student_headers = make_student_headers(student["id"])
        resp = api.book_exam({"student_id": student["id"], "exam_type": "THEORY_TEST",
                                "scheduled_at": "2099-01-01T10:00:00.000Z",
                                "examiner_id": "ex_01"},
                               student_headers)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)

    def test_complaint_handler_cannot_assign_handler(self, api):
        """PRD §4: POST /complaints/{id}/assign-handler authorised role: Admin only."""
        scenario = setup_basic_scenario(api)
        from test_helpers import file_complaint
        complaint = file_complaint(api, student=scenario["student"])
        resp = api.assign_handler(complaint["id"],
                                    {"handler_id": "h1", "handler_role": "ComplaintHandler"},
                                    TEST_USERS["complaint_handler_headers"])
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)


# ---------- Path-resource existence ----------

class TestPathResourceExistence:
    """PRD §2.7: "A request to act on a complaint whose path id does not resolve
    receives ERR_COMPLAINT_NOT_FOUND and HTTP 404 before any body validation runs.
    The same pattern applies to ERR_STUDENT_NOT_FOUND, ERR_INSTRUCTOR_NOT_FOUND,
    ERR_VEHICLE_NOT_FOUND, ERR_PACKAGE_NOT_FOUND, ERR_PRACTICE_NOT_FOUND,
    ERR_EXAM_NOT_FOUND, and ERR_SIMULATOR_NOT_FOUND."
    """

    def test_get_student_not_found(self, api):
        resp = api.get_student(NON_EXISTENT_UUID, ADMIN_HEADERS)
        validate_error(resp, ApiErrorId.ERR_STUDENT_NOT_FOUND.value)

    def test_get_instructor_not_found(self, api):
        resp = api.get_instructor(NON_EXISTENT_UUID, ADMIN_HEADERS)
        validate_error(resp, ApiErrorId.ERR_INSTRUCTOR_NOT_FOUND.value)

    def test_get_vehicle_not_found(self, api):
        resp = api.get_vehicle(NON_EXISTENT_UUID, ADMIN_HEADERS)
        validate_error(resp, ApiErrorId.ERR_VEHICLE_NOT_FOUND.value)

    def test_get_package_not_found(self, api):
        resp = api.get_course_package(NON_EXISTENT_UUID, ADMIN_HEADERS)
        validate_error(resp, ApiErrorId.ERR_PACKAGE_NOT_FOUND.value)

    def test_cancel_practice_not_found(self, api):
        resp = api.cancel_practice(NON_EXISTENT_UUID, ADMIN_HEADERS)
        validate_error(resp, ApiErrorId.ERR_PRACTICE_NOT_FOUND.value)

    def test_get_exam_not_found(self, api):
        resp = api.get_exam(NON_EXISTENT_UUID, ADMIN_HEADERS)
        validate_error(resp, ApiErrorId.ERR_EXAM_NOT_FOUND.value)

    def test_cancel_simulator_not_found(self, api):
        resp = api.cancel_simulator(NON_EXISTENT_UUID, ADMIN_HEADERS)
        validate_error(resp, ApiErrorId.ERR_SIMULATOR_NOT_FOUND.value)

    def test_get_complaint_not_found(self, api):
        resp = api.get_complaint(NON_EXISTENT_UUID, ADMIN_HEADERS)
        validate_error(resp, ApiErrorId.ERR_COMPLAINT_NOT_FOUND.value)


# ---------- Ownership: entity-backed roles ----------

class TestOwnershipEntityBacked:
    """PRD §2.1: "When X-User-Role is Student, X-User-ID is the id of the acting
    Student row; ownership checks on any resource that references a Student
    (such as a PracticeAppointment ...) compare the resource's student_id to
    X-User-ID."
    PRD §2.8 priority 4: ERR_FORBIDDEN_NOT_OWNER.
    """

    def test_student_cannot_get_other_students_profile(self, api):
        """PRD §3.9: "a Student may read only their own profile" (ownership)."""
        package = create_default_package(api)
        student_a, _ = create_active_student(api, package_id=package["id"])
        student_b, _ = create_active_student(api, package_id=package["id"])
        # Student A reads with their own id → success would hold; here B reads A.
        # The endpoint is shared (Admin, Student), so Student B has role permission;
        # ownership is the gate.
        b_headers = make_student_headers(student_b["id"])
        resp = api.get_student(student_a["id"], b_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_NOT_OWNER.value)

    def test_student_cannot_cancel_other_students_practice(self, api):
        """PRD §3.4: "A Student attempting to cancel another student's appointment
        is rejected with ERR_FORBIDDEN_NOT_OWNER before the state check fires."
        """
        package = create_default_package(api)
        student_a, _ = create_active_student(api, package_id=package["id"])
        student_b, _ = create_active_student(api, package_id=package["id"])
        instructor = create_active_instructor(api)
        vehicle = create_active_vehicle(api)
        from test_helpers import book_practice
        practice = book_practice(api,
                                   student=student_a, instructor=instructor, vehicle=vehicle,
                                   training_stage="THEORY")
        b_headers = make_student_headers(student_b["id"])
        resp = api.cancel_practice(practice["id"], b_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_NOT_OWNER.value)
