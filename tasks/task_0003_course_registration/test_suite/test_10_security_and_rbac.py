"""Security: authorization, ownership, malformed payloads."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, TEST_USERS,
    create_campus_payload, build_user_headers, NON_EXISTENT_UUID,
    make_student_headers,
)
from test_helpers.fixtures import (
    setup_basic_world, setup_open_offering, advance_clock,
    submit_enrollment, submit_enrollment_success, get_enrollment_request,
    create_student, create_offering, create_course,
)


SQL_INJECTION_PAYLOADS = [
    "'; DROP TABLE students; --",
    "' OR '1'='1",
    "' UNION SELECT * FROM users--",
]


@pytest.mark.parametrize("injection", SQL_INJECTION_PAYLOADS)
def test_sql_injection_in_string_field_no_500(api, registrar_headers, injection):
    """Security: SQL injection payloads must not produce 500 errors or leak
    SQL stack traces. Pass: any 2xx (treated as benign string) or 4xx
    rejection is acceptable.
    """
    res = api.create_campus(
        create_campus_payload(code="SQL-TST", name=injection),
        registrar_headers,
    )
    assert res.status_code != 500, (
        f"SQL injection payload produced 500: status={res.status_code} body={res.text[:200]}"
    )


def test_finance_cannot_create_student(api):
    """PRD §4: POST /students is Registrar-only.
    PRD §2.1: "When the role is present but is not authorized for the
    requested endpoint per the role-to-endpoint matrix described in §4, the
    request is rejected with ERR_INSUFFICIENT_PERMISSIONS (403)."

    Claim: Finance role attempting POST /students → ERR_INSUFFICIENT_PERMISSIONS.
    """
    finance = build_user_headers("finance-evil", "Finance")
    res = api.create_student({
        "full_name": "X", "program_id": "P", "program_department_id": NON_EXISTENT_UUID,
        "home_campus_id": NON_EXISTENT_UUID, "year_in_program": 1, "gpa": 3.0,
        "completed_course_ids": [],
    }, finance)
    validate_error(res, "ERR_INSUFFICIENT_PERMISSIONS")


def test_student_cannot_create_course(api):
    """PRD §4: POST /courses is Registrar-only.

    Claim: Student attempting POST /courses → ERR_INSUFFICIENT_PERMISSIONS.
    """
    student_headers = build_user_headers("student-evil", "Student")
    res = api.create_course({
        "code": "X-1", "title": "X", "credits": 3.0,
        "owning_department_id": NON_EXISTENT_UUID,
        "prerequisite_course_ids": [], "equivalent_course_ids": [],
    }, student_headers)
    validate_error(res, "ERR_INSUFFICIENT_PERMISSIONS")


def test_registrar_cannot_settle_tuition(api, registrar_headers):
    """PRD §4: POST /enrollment-requests/{id}/settle-tuition is Finance-only.

    Claim: Registrar attempting settle-tuition → ERR_INSUFFICIENT_PERMISSIONS.
    """
    world = setup_basic_world(student_year=2)
    co = setup_open_offering(world, credits=3.0,
                              scheduled_meetings=[{"day_of_week": 0, "start_minute_of_day": 540, "end_minute_of_day": 600}])
    er = submit_enrollment_success(world["student"], co["offering"]["id"])
    res = api.settle_tuition(er["id"], registrar_headers)
    validate_error(res, "ERR_INSUFFICIENT_PERMISSIONS")


def test_student_reads_other_students_request_rejected(api):
    """PRD §2.1: "Ownership checks on any resource that references a Student
    (for example the student_id on an EnrollmentRequest or
    OverLimitApplication) compare the resource's foreign-key field to
    X-User-ID; a mismatch is rejected with ERR_NOT_OWNER (403)."
    PRD §4: GET /enrollment-requests/{requestId} is "Registrar, Student (own only)".

    Claim: Student GETs another student's enrollment request →
    ERR_NOT_OWNER.
    """
    world = setup_basic_world(student_year=2)
    co = setup_open_offering(world, credits=3.0,
                              scheduled_meetings=[{"day_of_week": 1, "start_minute_of_day": 540, "end_minute_of_day": 600}])
    er = submit_enrollment_success(world["student"], co["offering"]["id"])
    intruder = create_student(world["department"]["id"], world["campus"]["id"], year_in_program=2,
                               full_name="Intruder S")
    res = api.get_enrollment_request(er["id"], make_student_headers(intruder["id"]))
    validate_error(res, "ERR_NOT_OWNER")


def test_student_get_own_degree_plan_succeeds(api):
    """PRD §2.1: ownership check permits a Student to read own resources.
    PRD §4: GET /students/{studentId}/degree-plan is "Registrar, Student (own only)".

    Claim: Student GETs OWN degree-plan → 200 success.
    """
    world = setup_basic_world(student_year=2)
    res = api.get_student_degree_plan(world["student"]["id"],
                                        make_student_headers(world["student"]["id"]))
    body = res.json()
    assert res.status_code == 200, f"Expected 200, got {res.status_code}: {body}"


def test_student_get_other_students_degree_plan_rejected(api):
    """PRD §2.1: ownership check on student-scoped reads.
    PRD §4: GET /students/{studentId}/degree-plan is "Registrar, Student (own only)".

    Claim: Student GETs another student's degree-plan → ERR_NOT_OWNER.
    """
    world = setup_basic_world(student_year=2)
    intruder = create_student(world["department"]["id"], world["campus"]["id"], year_in_program=2,
                               full_name="Plan Intruder")
    res = api.get_student_degree_plan(world["student"]["id"],
                                        make_student_headers(intruder["id"]))
    validate_error(res, "ERR_NOT_OWNER")
