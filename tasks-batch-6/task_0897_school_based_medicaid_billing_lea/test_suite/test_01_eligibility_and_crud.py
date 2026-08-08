"""Creation, required-field, not-found, and unauthenticated corners for the
core eligibility entities (Student, IEPAuthorization).
"""
from test_helpers import (
    api_client, TEST_USERS, ApiErrorId,
    validate_success, validate_error,
    create_student_payload, create_authorization_payload,
    assert_student, set_clock, create_student,
)

MC = TEST_USERS["medicaid_coordinator_headers"]
NON_EXISTENT = "00000000-0000-4000-8000-000000000000"


def test_student_create_returns_201_with_system_fields(api):
    """PRD §3.1: "A newly registered student begins in status ACTIVE, with both
    conservation ledgers — interim_paid_cents and verified_service_units —
    initialized to 0."
    PRD §2.4: "The version starts at 1 when the resource is created and
    increments by one on every mutation that changes the resource".

    Design: Corner/entities/student_create_returns_201_with_system_fields
    """
    set_clock("2026-03-15T00:00:00Z")
    resp = api.create_student(create_student_payload(
        medicaid_id="MA-C1", first_name="Cor", last_name="Ner",
        date_of_birth="2012-02-01", district_student_id="DC-1"), MC)
    data = validate_success(resp, expected_status=201)
    assert_student(data)
    assert data["status"] == "ACTIVE"
    assert data["interim_paid_cents"] == 0
    assert data["verified_service_units"] == 0
    assert data["version"] == 1
    assert resp.json()["meta"].get("api_request_id"), "meta.api_request_id must be present"
    assert resp.json()["response_type"] == "object"


def test_student_create_missing_required_last_name(api):
    """PRD §2.5: "any request whose body is malformed, is missing a required
    field, carries a value of the wrong type, supplies an out-of-domain enum
    value, or supplies invalid pagination parameters is rejected with
    ERR_VALIDATION (HTTP 400)."

    Design: Corner/entities/student_create_missing_required_last_name
    """
    payload = {"medicaid_id": "MA-C2", "first_name": "NoLast",
               "date_of_birth": "2012-02-01", "district_student_id": "DC-2"}
    resp = api.create_student(payload, MC)
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_student_get_not_found_returns_404(api):
    """PRD §2.5: "The resource-specific not-found errors, each HTTP 404, are:
    ERR_STUDENT_NOT_FOUND for a missing student".

    Design: Corner/entities/student_get_not_found_returns_404
    """
    resp = api.get_student(NON_EXISTENT, MC)
    validate_error(resp, ApiErrorId.ERR_STUDENT_NOT_FOUND)


def test_iep_authorization_invalid_enum_service_type(api):
    """PRD §2.5: "any request whose body is malformed, is missing a required
    field, carries a value of the wrong type, supplies an out-of-domain enum
    value, or supplies invalid pagination parameters is rejected with
    ERR_VALIDATION (HTTP 400)."

    Design: Corner/entities/iep_authorization_invalid_enum_service_type
    """
    student = create_student(medicaid_id="MA-C3", district_student_id="DC-3")
    resp = api.create_authorization(create_authorization_payload(
        student_id=student["id"], service_type="NOT_A_REAL_TYPE"), MC)
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_iep_authorization_create_bad_student_returns_not_found(api):
    """PRD §2.5: "every foreign key referenced in the request body exists (for
    example student_id, provider_id, iep_authorization_id, rmts_quarter_id,
    service_log_id), else the corresponding not-found error." and
    "ERR_STUDENT_NOT_FOUND for a missing student".

    Design: Corner/entities/iep_authorization_create_bad_student_returns_not_found
    """
    resp = api.create_authorization(create_authorization_payload(student_id=NON_EXISTENT), MC)
    validate_error(resp, ApiErrorId.ERR_STUDENT_NOT_FOUND)


def test_student_create_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "If either header is absent, or X-User-Role does not name a role
    the system recognizes, the request is rejected with ERR_UNAUTHENTICATED
    (HTTP 401)."

    Design: Corner/rbac/student_create_missing_auth_headers_unauthenticated
    """
    resp = api.create_student(create_student_payload(
        medicaid_id="MA-C16", first_name="Un", last_name="Au",
        date_of_birth="2012-02-01", district_student_id="DC-16"), {})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
