"""Auth headers, RBAC denials, and response envelope shape."""
from test_helpers import (
    validate_error,
    ApiErrorId,
    NON_EXISTENT_UUID,
    COORD_HEADERS,
    LAB_HEADERS,
    make_researcher_headers,
    make_reviewer_headers,
)


def test_missing_auth_header_rejected(api):
    """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`, identifying
    the acting user, and `X-User-Role`, declaring the capacity in which they act. A
    request in which either header is missing or empty is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

    Design: Corner/validations/missing_auth_header_rejected
    """
    resp = api.create_donor({"donor_reference_code": "D-VAL1"}, headers={})
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


def test_researcher_cannot_create_donor(api):
    """PRD §2.1: "A `ConsentCoordinator` is the donor and consent registrar and the kit
    custodian, and also controls de-identification keys and their access grants."
    PRD §2.1: "Attempting an operation outside one's role — or, for the requester-owned
    mutations described in §3.6, acting on a request whose `requester_user_id` differs
    from `X-User-ID` — is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

    Design: Corner/validations/researcher_cannot_create_donor
    """
    resp = api.create_donor({"donor_reference_code": "D-VAL2"},
                            make_researcher_headers("researcher-1"))
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


def test_committee_reviewer_cannot_create_storage_unit(api):
    """PRD §2.1: "A `BiobankAdmin` is the biobank operations administrator: the freezer
    registry, sharing agreements, fulfillment runs, the due-date sweep, and the logical
    clock belong to this role."
    PRD §2.1: "Attempting an operation outside one's role — or, for the requester-owned
    mutations described in §3.6, acting on a request whose `requester_user_id` differs
    from `X-User-ID` — is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

    Design: Corner/rbac/committee_reviewer_cannot_create_storage_unit
    """
    resp = api.create_storage_unit({"unit_code": "FRZ-RBAC", "setpoint_c": -80.0},
                                   make_reviewer_headers("rev-1"))
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


def test_error_response_envelope_shape_not_found(api):
    """PRD §2.2: "The `meta` object for error responses contains only `api_request_id`
    and `api_request_timestamp`."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the
    specific error."
    PRD §2.2: "The `message` provides a human-readable explanation of what went wrong."
    PRD §2.2: "The `response_type` is either "object" for a single resource or "array"
    for a list of resources."

    Design: Corner/endpoints/error_response_envelope_shape_not_found
    """
    # Error envelope on a 404.
    resp = api.get_specimen(NON_EXISTENT_UUID, LAB_HEADERS)
    assert resp.status_code == 404
    body = resp.json()
    assert body["response_type"] == "error"
    assert body["data"]["error_id"] == "ERR_NOT_FOUND"
    assert isinstance(body["data"]["message"], str) and body["data"]["message"]
    assert body["meta"]["api_request_id"]
    # Success envelope on a 201 create.
    resp = api.create_donor({"donor_reference_code": "D-ENV"}, COORD_HEADERS)
    assert resp.status_code == 201
    body = resp.json()
    assert body["response_type"] == "object"
    assert body["data"]["id"]
    assert body["meta"]["api_request_timestamp"]
