"""Student registration claims: defaults, uniqueness, computed fields, required
fields, enum constraints, and existence errors (PRD §2.5, §2.7, §3.1)."""
from test_helpers import (
    ApiErrorId,
    assert_student,
    create_student_payload,
    validate_error,
    validate_success,
)

UNKNOWN_STUDENT_ID = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"


def test_student_create_applies_defaults(api, health_admin_headers):
    """PRD §3.1: "An optional `enrollment_status` may be provided at registration;
    when omitted it defaults to `ENROLLED`" and "At registration both are
    initialized benignly: the posture is `CLEAR` and the hold-type list is empty."
    PRD §2.5: "`version` (integer): a system-managed integer starting at 1 that
    increments on every mutation".

    Design: Corner/entities/student_create_applies_defaults
    """
    created = validate_success(
        api.create_student(
            create_student_payload(external_ref="S1", full_name="Default Dan"),
            health_admin_headers,
        ),
        201,
    )
    student = validate_success(api.get_student(created["id"], health_admin_headers), 200)

    assert_student(student)
    assert student["enrollment_status"] == "ENROLLED", "default ENROLLED not applied"
    assert student["compliance_posture"] == "CLEAR"
    assert student["active_hold_types"] == []
    assert student["version"] == 1


def test_student_get_returns_not_found(api, health_admin_headers):
    """PRD §2.7: "the request is rejected with `ERR_NOT_FOUND` at the first
    identifier that does not correspond to an existing resource".
    PRD §2.2: the error envelope carries "data": {"error_id", "message"}.

    Design: Corner/entities/student_get_returns_not_found
    """
    res = api.get_student(UNKNOWN_STUDENT_ID, health_admin_headers)
    error = validate_error(res, ApiErrorId.ERR_NOT_FOUND, expected_status=404)
    assert error["error_id"] == "ERR_NOT_FOUND"
    assert isinstance(error["message"], str) and error["message"].strip()


def test_student_create_duplicate_ref_rejected(api, health_admin_headers):
    """PRD §3.1: "the campus `external_ref` (the university student number,
    unique across all students — a duplicate registration is rejected with
    `ERR_DUPLICATE_STUDENT_REF`)".

    Design: Corner/entities/student_create_duplicate_ref_rejected
    """
    validate_success(
        api.create_student(
            create_student_payload(external_ref="S2", full_name="First"),
            health_admin_headers,
        ),
        201,
    )
    res = api.create_student(
        create_student_payload(external_ref="S2", full_name="Second"),
        health_admin_headers,
    )
    validate_error(res, ApiErrorId.ERR_DUPLICATE_STUDENT_REF, expected_status=409)


def test_student_create_computed_posture_input_ignored(api, health_admin_headers):
    """PRD §3.1: "Every student carries two derived compliance attributes that no
    client ever writes directly." and "At registration both are initialized
    benignly: the posture is `CLEAR` and the hold-type list is empty."

    Design: Corner/entities/student_create_computed_posture_input_ignored
    """
    payload = create_student_payload(external_ref="S3", full_name="Sneaky")
    payload["compliance_posture"] = "REGISTRATION_HOLD"
    student = validate_success(
        api.create_student(payload, health_admin_headers), 201
    )
    assert student["compliance_posture"] == "CLEAR", (
        "client-supplied compliance_posture must be ignored; the server derives it"
    )
    assert student["active_hold_types"] == []


def test_student_create_missing_required_full_name(api, health_admin_headers):
    """PRD §3.1: "A `HealthAdmin` operator registers each student by supplying
    the campus `external_ref` (the university student number, unique across all
    students — a duplicate registration is rejected with
    `ERR_DUPLICATE_STUDENT_REF`) together with the student's `full_name`." A
    request omitting that required field is a malformed request, rejected with
    `ERR_INVALID_REQUEST` (HTTP 400, PRD §5).

    Design: Corner/entities/student_create_missing_required_full_name
    """
    res = api.create_student({"external_ref": "S4"}, health_admin_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


def test_student_create_invalid_enum_enrollment(api, health_admin_headers):
    """PRD §3.1: enrollment_status "may later take the values `LEAVE` or
    `WITHDRAWN`" — the allowed set is {ENROLLED, LEAVE, WITHDRAWN}; a value
    outside it is a malformed request rejected with `ERR_INVALID_REQUEST` (400,
    PRD §5).

    Design: Corner/entities/student_create_invalid_enum_enrollment
    """
    res = api.create_student(
        create_student_payload(
            external_ref="S5", full_name="Enum Ed", enrollment_status="PHD"
        ),
        health_admin_headers,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)
