"""Student intake, response envelope, and read-after-write claims (PRD §2.2, §2.4, §3.1)."""
from test_helpers import (
    ALT_STUDENT,
    TEST_DEFAULTS,
    ApiErrorId,
    assert_student,
    create_student,
    create_student_payload,
    is_valid_uuid,
    set_clock,
    validate_error,
    validate_success,
)


def test_student_created_with_defaults(api, dso_headers):
    """PRD §3.1: "The student's `compliance_posture` is initialized to `CLEAR`."
    PRD §2.4: "`id` (string): a unique, server-minted UUID with no type prefix."
    PRD §2.4: "`version` (integer): a system-managed integer that increments on
    every mutation and serves as the basis for optimistic concurrency control."

    Design: Corner/entities/student_created_with_defaults
    """
    set_clock("2026-08-01T00:00:00Z")
    resp = api.create_student(create_student_payload(), dso_headers)
    data = validate_success(resp, 201)
    assert_student(data)
    assert is_valid_uuid(data["id"]), "id must be a server-minted UUID"
    assert isinstance(data["version"], int), "version must be an integer"
    assert data["compliance_posture"] == "CLEAR", (
        f"new student posture must be CLEAR, got {data['compliance_posture']}"
    )


def test_student_missing_sevis_id_returns_invalid_request(api, dso_headers):
    """PRD §2.9: "Malformed request bodies — a missing required field, a type
    mismatch, an invalid enum value, or a malformed date — are rejected with
    `ERR_INVALID_REQUEST` (HTTP 400)."
    PRD §3.1: "A DSO begins a student's journey by creating the intake record
    with `sevis_id`, `full_name`, `email`, `date_of_birth`,
    `country_of_citizenship`, and `degree_level`".

    Design: Corner/entities/student_missing_required_sevis_id_returns_invalid_request
    """
    set_clock("2026-08-01T00:00:00Z")
    payload = create_student_payload()
    del payload["sevis_id"]
    resp = api.create_student(payload, dso_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)


def test_student_invalid_sevis_id_format_returns_invalid_request(api, dso_headers):
    """PRD §3.1: "The `sevis_id` must be unique across the system and match the
    SEVIS format — the letter N followed by ten digits; a duplicate is rejected
    with `ERR_DUPLICATE_SEVIS_ID`."
    PRD §2.9: "Malformed request bodies — a missing required field, a type
    mismatch, an invalid enum value, or a malformed date — are rejected with
    `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/student_invalid_sevis_id_format_returns_invalid_request
    """
    set_clock("2026-08-01T00:00:00Z")
    resp = api.create_student(create_student_payload(sevis_id="X123"), dso_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)


def test_student_duplicate_sevis_id_returns_409(api, dso_headers):
    """PRD §3.1: "The `sevis_id` must be unique across the system and match the
    SEVIS format — the letter N followed by ten digits; a duplicate is rejected
    with `ERR_DUPLICATE_SEVIS_ID`."

    Design: Corner/entities/student_duplicate_sevis_id_returns_409
    """
    create_student()
    # A second student reusing the same sevis_id is the duplicate PRD §3.1
    # rejects; ALT_STUDENT varies the identity fields but must re-use the
    # default sevis_id to exercise the uniqueness rule.
    payload = create_student_payload(
        **{**ALT_STUDENT, "sevis_id": TEST_DEFAULTS["SEVIS_ID"]}
    )
    resp = api.create_student(payload, dso_headers)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_SEVIS_ID, 409)


def test_get_student_not_found_returns_404(api, dso_headers):
    """PRD §2.6: "A request naming a nonexistent student is rejected with
    `ERR_STUDENT_NOT_FOUND`; a request naming a nonexistent non-student
    resource is rejected with `ERR_NOT_FOUND`."

    Design: Corner/entities/get_student_not_found_returns_404
    """
    set_clock("2026-08-01T00:00:00Z")
    resp = api.get_student("00000000-0000-0000-0000-000000000000", dso_headers)
    validate_error(resp, ApiErrorId.ERR_STUDENT_NOT_FOUND, 404)


def test_response_envelope_success_and_error_shape(api, dso_headers):
    """PRD §2.2: "The `api_request_id` is a server-generated unique identifier
    for the request that starts with `req_`."
    PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that
    identifies the specific error."

    Design: Corner/endpoints/response_envelope_success_and_error_shape
    """
    set_clock("2026-08-01T00:00:00Z")

    ok = api.create_student(create_student_payload(), dso_headers)
    ok_body = ok.json()
    assert ok.status_code == 201
    assert isinstance(ok_body["meta"]["api_request_id"], str)
    assert ok_body["meta"]["api_request_id"].startswith("req_")
    assert isinstance(ok_body["meta"]["api_request_timestamp"], str)
    assert ok_body["response_type"] == "object"
    assert isinstance(ok_body["data"]["id"], str)

    err = api.get_student("00000000-0000-0000-0000-000000000000", dso_headers)
    err_body = err.json()
    assert err.status_code == 404
    assert err_body["response_type"] == "error"
    assert err_body["data"]["error_id"] == "ERR_STUDENT_NOT_FOUND"
    assert isinstance(err_body["data"]["message"], str)
    assert len(err_body["data"]["message"].strip()) > 0


def test_immediate_consistency_read_after_write(api, dso_headers):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."
    PRD §3.1: "The student's `compliance_posture` is initialized to `CLEAR`."

    Design: Corner/consistency_model/immediate_consistency_read_after_write
    """
    set_clock("2026-08-01T00:00:00Z")
    created = validate_success(api.create_student(create_student_payload(), dso_headers), 201)
    read = validate_success(api.get_student(created["id"], dso_headers), 200)
    assert_student(read)
    assert read["id"] == created["id"]
    assert read["full_name"] == "Asha Rao"
    assert read["sevis_id"] == "N0012345678"
    assert isinstance(read["version"], int)
    assert read["compliance_posture"] == "CLEAR"
