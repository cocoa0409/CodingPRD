"""Response envelope, pagination, and authentication header sanity tests.

Pinned to PRD §2.1 (auth headers), §2.2 (envelope), §2.3 (pagination).
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    create_campus_payload, TEST_USERS, NON_EXISTENT_UUID, build_user_headers,
)
from test_helpers.fixtures import (
    create_campus, create_department, create_student, setup_basic_world,
)


def test_create_campus_returns_object_envelope(api, registrar_headers):
    """PRD §2.2: "All successful API responses (those with 2xx status codes)
    follow this standard envelope format in their JSON body" with response_type
    "object" for a single resource.

    Claim: POST /campuses returns the standard success envelope with
    response_type=object and a campus payload in data.
    """
    payload = create_campus_payload(code="ENV-TEST-A", name="Envelope Test Campus")
    res = api.create_campus(payload, registrar_headers)
    body = res.json()
    assert res.status_code == 201
    assert body["response_type"] == "object"
    assert "meta" in body and "api_request_id" in body["meta"]
    assert body["meta"]["api_request_id"].startswith("req_")
    assert "api_request_timestamp" in body["meta"]
    assert body["data"]["code"] == "ENV-TEST-A"


def test_missing_user_id_header_rejected(api):
    """PRD §2.1: "Every API call must carry two HTTP headers: X-User-ID,
    identifying the acting user, and X-User-Role, naming their operational
    capacity. Requests missing or malforming either header are rejected with
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER (400)."

    Claim: missing X-User-ID → ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.
    """
    headers = {"X-User-Role": "Registrar"}
    res = api.create_campus(create_campus_payload(code="MISS-1", name="Miss"), headers)
    validate_error(res, "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER")


def test_missing_user_role_header_rejected(api):
    """PRD §2.1: "Every API call must carry two HTTP headers: X-User-ID,
    identifying the acting user, and X-User-Role, naming their operational
    capacity. Requests missing or malforming either header are rejected with
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER (400)."

    Claim: missing X-User-Role → ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.
    """
    headers = {"X-User-ID": "some-user"}
    res = api.create_campus(create_campus_payload(code="MISS-2", name="Miss"), headers)
    validate_error(res, "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER")


def test_role_not_authorized_for_endpoint(api):
    """PRD §2.1: "When the role is present but is not authorized for the
    requested endpoint per the role-to-endpoint matrix described in §4, the
    request is rejected with ERR_INSUFFICIENT_PERMISSIONS (403)."

    Claim: Student role calling POST /campuses (Registrar-only) → ERR_INSUFFICIENT_PERMISSIONS.
    """
    headers = build_user_headers("any-student", "Student")
    res = api.create_campus(create_campus_payload(code="PERM-TEST", name="Perm"), headers)
    validate_error(res, "ERR_INSUFFICIENT_PERMISSIONS")


def test_pagination_default_limit_and_offset(api, registrar_headers):
    """PRD §2.3: "The limit parameter specifies the maximum number of items
    to return; if not provided, it defaults to 10, with a minimum of 1 and
    a maximum of 100. The offset parameter specifies the number of items to
    skip and defaults to 0."

    Claim: list endpoint with no params returns up to 10 items, offset 0.
    """
    # Create a few campuses (assuming clean-ish state; use total_count not exact count)
    for _ in range(3):
        create_campus()
    res = api.list_students(registrar_headers)
    data, meta = validate_paginated(res)
    assert meta["limit"] == 10
    assert meta["offset"] == 0


def test_pagination_invalid_limit_too_high(api, registrar_headers):
    """PRD §2.3: "A request whose limit is below 1, above 100, or whose offset
    is below 0 is rejected with ERR_INVALID_PAGINATION_PARAMETERS (400)."

    Claim: limit=101 → ERR_INVALID_PAGINATION_PARAMETERS.
    """
    res = api.list_students(registrar_headers, params={"limit": 101})
    validate_error(res, "ERR_INVALID_PAGINATION_PARAMETERS")


def test_pagination_invalid_limit_zero(api, registrar_headers):
    """PRD §2.3: "A request whose limit is below 1, above 100, or whose offset
    is below 0 is rejected with ERR_INVALID_PAGINATION_PARAMETERS (400)."

    Claim: limit=0 → ERR_INVALID_PAGINATION_PARAMETERS.
    """
    res = api.list_students(registrar_headers, params={"limit": 0})
    validate_error(res, "ERR_INVALID_PAGINATION_PARAMETERS")


def test_pagination_invalid_offset_negative(api, registrar_headers):
    """PRD §2.3: "A request whose limit is below 1, above 100, or whose offset
    is below 0 is rejected with ERR_INVALID_PAGINATION_PARAMETERS (400)."

    Claim: offset=-1 → ERR_INVALID_PAGINATION_PARAMETERS.
    """
    res = api.list_students(registrar_headers, params={"offset": -1})
    validate_error(res, "ERR_INVALID_PAGINATION_PARAMETERS")


def test_get_student_not_found(api, registrar_headers):
    """PRD §2.8: per the table of resource-specific not-found codes (including
    ERR_STUDENT_NOT_FOUND).

    Claim: GET /students/{nonexistent} → ERR_STUDENT_NOT_FOUND (404).
    """
    res = api.get_student(NON_EXISTENT_UUID, registrar_headers)
    validate_error(res, "ERR_STUDENT_NOT_FOUND")


def test_response_envelope_error_has_error_id(api, registrar_headers):
    """PRD §2.2: error envelope contains data.error_id and data.message.

    Claim: a 404 response carries data.error_id and data.message.
    """
    res = api.get_student(NON_EXISTENT_UUID, registrar_headers)
    body = res.json()
    assert body["response_type"] == "error"
    assert "error_id" in body["data"]
    assert "message" in body["data"]
