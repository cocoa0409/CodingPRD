"""Coach/client master data, envelope shape, and baseline existence checks."""
from test_helpers import (
    NO_AUTH_HEADERS,
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_coach,
    get_success_data,
    make_client_headers,
    reset_clock,
    set_clock,
    TEST_USERS,
    validate_error,
    validate_success,
)

PM = TEST_USERS["practice_manager_headers"]


def test_coach_creation_success_and_defaults(api):
    """PRD §3.1: "A new coach begins `PENDING_VERIFICATION` with ethics
    `ACTIVE`."
    PRD §2.4: "version (integer): a system-managed integer that increments by
    one with every modification to the resource".

    Design: Corner/entities/coach_creation_success_and_defaults
    """
    reset_clock()
    resp = api.create_coach(
        {
            "display_name": "New Coach",
            "email": "new.coach@example.com",
            "credential_level": "ACC",
            "credential_expires_on": "2027-06-01",
            "max_concurrent_clients": 5,
        },
        PM,
    )
    data = validate_success(resp, expected_status=201)
    assert_coach(data)
    assert data["credential_status"] == "PENDING_VERIFICATION"
    assert data["ethics_status"] == "ACTIVE"
    assert data["version"] == 1


def test_coach_creation_invalid_enum_credential_level_rejected(api):
    """PRD §2.11: "Request-shape validation closes the chain and is evaluated
    last, yielding `ERR_INVALID_REQUEST` (HTTP 400): required fields present,
    enum members valid, and numeric ranges honored".
    PRD §3.1: "`credential_level` — one of `ACC`, `PCC`, or `MCC`".

    Design: Corner/entities/coach_creation_invalid_enum_credential_level_rejected
    """
    reset_clock()
    resp = api.create_coach(
        {
            "display_name": "Bad Enum",
            "email": "bad.enum@example.com",
            "credential_level": "PHD",
            "credential_expires_on": "2027-06-01",
            "max_concurrent_clients": 5,
        },
        PM,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_coach_creation_duplicate_email_rejected(api):
    """PRD §3.1: "Coach email addresses are unique across the roster, and a
    duplicate is rejected with `ERR_DUPLICATE_RESOURCE`."

    Design: Corner/entities/coach_creation_duplicate_email_rejected
    """
    reset_clock()
    payload = {
        "display_name": "First",
        "email": "dup@example.com",
        "credential_level": "ACC",
        "credential_expires_on": "2027-06-01",
        "max_concurrent_clients": 5,
    }
    validate_success(api.create_coach(payload, PM), expected_status=201)
    second = dict(payload, display_name="Second", credential_level="PCC")
    resp = api.create_coach(second, PM)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_RESOURCE)


def test_client_get_not_found_returns_404(api):
    """PRD §2.11: "Existence is third: path identifiers are resolved left to
    right, then foreign-key references in the request body in their declared
    order, and the first missing reference yields `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/client_get_not_found_returns_404
    """
    reset_clock()
    resp = api.get_client(NON_EXISTENT_UUID, PM)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_session_booking_with_nonexistent_enrollment_returns_404(api):
    """PRD §2.11: "Existence is third: path identifiers are resolved left to
    right, then foreign-key references in the request body in their declared
    order, and the first missing reference yields `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/session_booking_with_nonexistent_enrollment_returns_404
    """
    reset_clock()
    resp = api.create_client(
        {"full_name": "Client NF", "email": "cnf@example.com", "timezone": "UTC"},
        PM,
    )
    client = validate_success(resp, expected_status=201)
    resp = api.book_session(
        NON_EXISTENT_UUID,
        {"scheduled_start": "2026-08-10T10:00:00Z", "duration_minutes": 60},
        make_client_headers(client["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_error_envelope_shape_on_failure(api):
    """PRD §2.2: "All error API responses (4xx status codes) follow this
    standard envelope format", with `"response_type": "error"` and a `data`
    object keyed by `"error_id"` and `"message"`; "The `meta` object for
    error responses contains only `api_request_id` and
    `api_request_timestamp`."
    PRD §2.11: "Request-shape validation closes the chain and is evaluated
    last, yielding `ERR_INVALID_REQUEST` (HTTP 400): required fields present,
    enum members valid, and numeric ranges honored".

    Design: Corner/errors/error_envelope_shape_on_failure
    """
    reset_clock()
    resp = api.create_coach(
        {
            "display_name": "No Email Coach",
            "credential_level": "ACC",
            "credential_expires_on": "2027-06-01",
            "max_concurrent_clients": 5,
        },
        PM,
    )
    err = validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    assert err["message"].strip(), "error message must be non-empty"
    body = resp.json()
    assert body["meta"].get("api_request_id"), "meta.api_request_id required"
    assert body["meta"].get("api_request_timestamp")
