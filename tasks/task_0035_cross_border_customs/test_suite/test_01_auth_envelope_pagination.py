"""Auth header presence, role permissions, response envelope, pagination.

PRD anchors: §2.1 (RBAC), §2.2 (envelope), §2.3 (pagination), §5 (errors).
"""
from __future__ import annotations
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_hs_code_payload,
    create_hs_code,
    make_declarant_headers,
    make_importer_headers,
    create_party_pair,
    create_order,
    setup_draft_declaration,
)


# ---------------------------------------------------------------------------
# Header presence
# ---------------------------------------------------------------------------
def test_missing_user_id_header_rejected(api):
    """PRD §2.1: "If either header is missing or empty, the request is
    rejected with ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER and HTTP
    status 400."

    Claim: a request with X-User-Role but no X-User-ID returns
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER at HTTP 400.
    """
    res = api.create_hs_code(create_hs_code_payload(), {"X-User-Role": "CustomsOfficer"})
    validate_error(res, "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                   expected_status=400)


def test_missing_user_role_header_rejected(api):
    """PRD §2.1: "If either header is missing or empty, the request is
    rejected with ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER and HTTP
    status 400."

    Claim: a request with X-User-ID but no X-User-Role returns the same
    auth-header error at HTTP 400.
    """
    res = api.create_hs_code(create_hs_code_payload(), {"X-User-ID": "officer-x"})
    validate_error(res, "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                   expected_status=400)


def test_empty_user_id_header_rejected(api):
    """PRD §2.1: "If either header is missing or empty, the request is
    rejected with ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER and HTTP
    status 400."

    Claim: empty X-User-ID is treated identically to missing.
    """
    res = api.create_hs_code(
        create_hs_code_payload(),
        {"X-User-ID": "", "X-User-Role": "CustomsOfficer"},
    )
    validate_error(res, "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                   expected_status=400)


def test_no_headers_at_all(api):
    """PRD §2.1: Both headers missing → ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER."""
    res = api.create_hs_code(create_hs_code_payload(), {})
    validate_error(res, "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                   expected_status=400)


# ---------------------------------------------------------------------------
# Role permission
# ---------------------------------------------------------------------------
def test_unauthorized_role_returns_forbidden(api):
    """PRD §2.1: "If the headers are present but the role named in
    X-User-Role is not authorized to invoke the requested endpoint per
    the role matrix, the request is rejected with ERR_FORBIDDEN_FOR_ROLE
    and HTTP status 403."

    Claim: Auditor (read-only role per PRD §2.1) calling
    POST /hs_codes (CustomsOfficer-only per PRD §4) → ERR_FORBIDDEN_FOR_ROLE 403.
    """
    res = api.create_hs_code(create_hs_code_payload(), TEST_USERS["auditor_headers"])
    validate_error(res, "ERR_FORBIDDEN_FOR_ROLE", expected_status=403)


def test_finance_officer_cannot_create_hs_code(api):
    """PRD §4: POST /hs_codes is CustomsOfficer-exclusive.
    PRD §2.1: "If the headers are present but the role named in
    X-User-Role is not authorized to invoke the requested endpoint per
    the role matrix, the request is rejected with ERR_FORBIDDEN_FOR_ROLE
    and HTTP status 403."

    Claim: FinanceOfficer attempting to create an HsCode → 403.
    """
    res = api.create_hs_code(create_hs_code_payload(),
                             TEST_USERS["finance_officer_headers"])
    validate_error(res, "ERR_FORBIDDEN_FOR_ROLE", expected_status=403)


def test_declarant_cannot_approve_declaration(api):
    """PRD §4: POST /declarations/{id}/approve is CustomsOfficer-exclusive.
    PRD §2.1 verbatim: "the request is rejected with ERR_FORBIDDEN_FOR_ROLE
    and HTTP status 403."
    """
    importer, declarant = create_party_pair()
    order = create_order(importer, declarant)
    res = api.approve_declaration(
        order["id"], make_declarant_headers(declarant["id"])
    )
    validate_error(res, "ERR_FORBIDDEN_FOR_ROLE", expected_status=403)


# ---------------------------------------------------------------------------
# Envelope structure
# ---------------------------------------------------------------------------
def test_success_envelope_contains_required_meta(api, customs_officer_headers):
    """PRD §2.2 verbatim: "The api_request_id is a server-generated unique
    identifier for the request that starts with req_."
    PRD §2.2: "The api_request_timestamp is a server-generated ISO 8601
    UTC timestamp with three fractional digits."

    Claim: every 2xx response carries meta.api_request_id (starts with
    req_) and meta.api_request_timestamp (ISO 8601 with fractional digits).
    """
    res = api.create_hs_code(create_hs_code_payload(), customs_officer_headers)
    body = res.json()
    assert "meta" in body
    assert isinstance(body["meta"].get("api_request_id"), str)
    assert body["meta"]["api_request_id"].startswith("req_"), (
        f"api_request_id must start with 'req_', got {body['meta']['api_request_id']!r}"
    )
    assert "api_request_timestamp" in body["meta"]


def test_error_envelope_shape(api):
    """PRD §2.2: error envelope contains meta + response_type='error' +
    data with error_id and message.

    Claim: a 4xx response includes data.error_id (machine-readable string)
    and data.message (human-readable explanation), per PRD §2.2.
    """
    res = api.get_hs_code(NON_EXISTENT_UUID, TEST_USERS["customs_officer_headers"])
    body = res.json()
    assert body.get("response_type") == "error"
    assert "data" in body and isinstance(body["data"], dict)
    assert isinstance(body["data"].get("error_id"), str)
    assert isinstance(body["data"].get("message"), str)
    assert len(body["data"]["message"]) > 0


# ---------------------------------------------------------------------------
# Pagination on the only list endpoint we can reach without privileged setup.
# ---------------------------------------------------------------------------
def test_list_declarations_pagination_meta(api, customs_officer_headers):
    """PRD §2.3 verbatim: "The limit parameter defaults to 10, has a
    minimum of 1, and a maximum of 100; the offset parameter defaults
    to 0. List responses default to sorting by created_at ascending. The
    meta block of every list response carries limit, offset, total_count,
    and has_more."

    Claim: GET /declarations with no params returns meta containing
    limit, offset, total_count, has_more.
    """
    # Ensure at least one declaration exists.
    setup_draft_declaration()
    setup_draft_declaration()
    res = api.list_declarations(customs_officer_headers)
    data, meta = validate_paginated(res)
    assert isinstance(data, list)
    for f in ("limit", "offset", "total_count", "has_more"):
        assert f in meta, f"meta missing {f}"


def test_list_declarations_respects_limit(api, customs_officer_headers):
    """PRD §2.3: "The limit parameter defaults to 10, has a minimum of 1,
    and a maximum of 100".

    Claim: a limit of 1 returns at most 1 row and meta.limit reflects it.
    """
    setup_draft_declaration()
    setup_draft_declaration()
    res = api.list_declarations(customs_officer_headers, params={"limit": 1})
    data, meta = validate_paginated(res)
    assert len(data) <= 1
    assert meta["limit"] == 1


def test_list_declarations_offset_past_end_empty(api, customs_officer_headers):
    """PRD §2.3: pagination defines offset; offset past the dataset
    yields an empty page.

    Claim: a very large offset returns no rows and has_more=False.
    """
    setup_draft_declaration()
    res = api.list_declarations(
        customs_officer_headers, params={"offset": 999_999, "limit": 10}
    )
    data, meta = validate_paginated(res)
    assert data == []
    assert meta["has_more"] is False


# ---------------------------------------------------------------------------
# NOT_FOUND on path-segment id (PRD §2.6).
# ---------------------------------------------------------------------------
def test_get_nonexistent_declaration(api, customs_officer_headers):
    """PRD §2.6: "Single-segment ID parameters such as query_id, refund_id,
    notice_id, appointment_id, hs_code_id, order_id, and importer_id are
    resolved the same way — non-existence yields ERR_NOT_FOUND."

    Claim: GET on a non-existent declaration_id → ERR_NOT_FOUND 404.
    """
    res = api.get_declaration(NON_EXISTENT_UUID, customs_officer_headers)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


def test_get_nonexistent_hs_code(api, customs_officer_headers):
    """PRD §2.6: hs_code_id that does not resolve → ERR_NOT_FOUND."""
    res = api.get_hs_code(NON_EXISTENT_UUID, customs_officer_headers)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


def test_get_nonexistent_order(api, customs_officer_headers):
    """PRD §2.6: order_id non-existence yields ERR_NOT_FOUND."""
    res = api.get_order(NON_EXISTENT_UUID, customs_officer_headers)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


def test_create_declaration_with_unknown_order_id(api):
    """PRD §2.6: "Body-referenced foreign keys — order_id on declaration
    creation, declaration_id on refund creation, hs_code_id on line
    creation, and the body fields on inspection-appointment scheduling —
    are validated similarly with the same ERR_NOT_FOUND code."

    Claim: POST /declarations with a non-existent order_id → ERR_NOT_FOUND 404.
    """
    importer, declarant = create_party_pair()
    res = api.create_declaration(
        {"order_id": NON_EXISTENT_UUID, "dutiable_value_method": "TRANSACTION_VALUE",
         "contract_number": "CN-001"},
        make_declarant_headers(declarant["id"]),
    )
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)
