"""Tests for global authentication, role enforcement, response envelope,
and pagination behaviour of the Legal Case Management API.

Covers PRD §2.1 (RBAC headers), §2.2 (envelope), §2.3 (pagination).
"""
from __future__ import annotations
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    build_user_headers,
    create_lawyer_payload,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_partner_lawyer,
    setup_three_lawyers_and_active_case,
    validate_error,
    validate_paginated,
    validate_success,
)


# ---------------------------------------------------------------------------
# Auth header presence (priority 1)
# ---------------------------------------------------------------------------
def test_missing_both_auth_headers_rejected(api):
    """PRD §2.1: 'Every request must arrive with two headers: X-User-ID,
    identifying the acting principal, and X-User-Role, naming that
    principal's role. Both headers are mandatory; if either is missing,
    the request is rejected with ERR_AUTH_REQUIRED (HTTP 401).'

    Claim: empty headers → ERR_AUTH_REQUIRED.
    """
    res = api.list_cases({})
    validate_error(res, "ERR_AUTH_REQUIRED", expected_status=401)


def test_missing_user_id_header_rejected(api):
    """PRD §2.1: 'Both headers are mandatory; if either is missing, the
    request is rejected with ERR_AUTH_REQUIRED (HTTP 401).'

    Claim: only X-User-Role present → ERR_AUTH_REQUIRED.
    """
    res = api.list_cases({"X-User-Role": "PartnerLawyer"})
    validate_error(res, "ERR_AUTH_REQUIRED", expected_status=401)


def test_missing_user_role_header_rejected(api):
    """PRD §2.1: 'Both headers are mandatory; if either is missing, the
    request is rejected with ERR_AUTH_REQUIRED (HTTP 401).'

    Claim: only X-User-ID present → ERR_AUTH_REQUIRED.
    """
    res = api.list_cases({"X-User-ID": "some-id-123"})
    validate_error(res, "ERR_AUTH_REQUIRED", expected_status=401)


# ---------------------------------------------------------------------------
# RBAC (priority 2)
# ---------------------------------------------------------------------------
def test_intake_clerk_cannot_register_lawyer(api, intake_clerk_headers):
    """PRD §2.1: 'the sole role for partner-signoff, draft locking, bill
    voiding, settlement marking, evidence exclusion, rebuttal upholding,
    case activation, hold, resume, close, lawyer registration'

    Claim: IntakeClerk calling POST /lawyers → ERR_FORBIDDEN.
    """
    res = api.create_lawyer(
        create_lawyer_payload(role="JUNIOR"), intake_clerk_headers
    )
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)


def test_system_integrator_cannot_create_case(api, system_integrator_headers):
    """PRD §4 lists POST /cases authorized roles as PartnerLawyer and
    IntakeClerk only. PRD §2.1: 'When the headers are present but the
    supplied role is not authorized for the requested endpoint per the
    matrix in §4, the request is rejected with ERR_FORBIDDEN (HTTP 403).'
    """
    payload = {
        "case_type": "CIVIL", "title": "Sys Try",
        "claim_amount_cents": 1, "lead_lawyer_id": NON_EXISTENT_UUID,
        "client_identity_hash": "x", "opposing_identity_hash": "y",
        "intake_document_id": "doc-1",
    }
    res = api.create_case(payload, system_integrator_headers)
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)


# ---------------------------------------------------------------------------
# Existence (priority 3)
# ---------------------------------------------------------------------------
def test_get_unknown_case_returns_not_found(api, intake_clerk_headers):
    """PRD §2.6: 'then the existence of every path-segment id, resolved
    left-to-right so that an unknown caseId in /cases/{caseId}/parties
    surfaces before an unknown party context (priority 3, ERR_NOT_FOUND).'
    """
    res = api.get_case(NON_EXISTENT_UUID, intake_clerk_headers)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


# ---------------------------------------------------------------------------
# Envelope (success / error)
# ---------------------------------------------------------------------------
def test_success_envelope_shape(api):
    """PRD §2.2: 'All successful API responses (those with 2xx status
    codes) follow this standard envelope format in their JSON body ...
    The api_request_id is a server-generated unique identifier for the
    request that starts with req_. The api_request_timestamp is a
    server-generated ISO 8601 UTC timestamp with three fractional digits.'
    """
    partner, partner_headers = make_partner_lawyer()
    res = api.get_lawyer(partner["id"], partner_headers)
    body = res.json()
    assert "meta" in body
    assert "response_type" in body
    assert "data" in body
    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"].startswith("req_")
    assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])


def test_error_envelope_shape(api):
    """PRD §2.2: 'All error API responses (4xx status codes) follow this
    standard envelope format ... The error_id is a unique, machine-readable
    string that identifies the specific error. The message provides a
    human-readable explanation of what went wrong.'
    """
    res = api.list_cases({})
    body = res.json()
    assert body["response_type"] == "error"
    assert body["data"]["error_id"] == "ERR_AUTH_REQUIRED"
    assert isinstance(body["data"].get("message"), str)
    assert body["meta"]["api_request_id"].startswith("req_")


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------
def test_default_pagination_returns_meta(api):
    """PRD §2.3: 'The list envelope's meta block carries limit, offset,
    total_count (the total number of matching rows before the limit/offset
    window is applied), and has_more (true when more rows remain past the
    current window).'
    """
    bundle = setup_three_lawyers_and_active_case()
    data, meta = validate_paginated(
        api.list_cases(bundle["partner_headers"])
    )
    assert "limit" in meta
    assert "offset" in meta
    assert "total_count" in meta
    assert "has_more" in meta
    assert meta["limit"] == 10  # PRD §2.3 default


def test_pagination_limit_max_100(api):
    """PRD §2.3: 'The default limit is 10, the minimum is 1, and the
    maximum is 100; values outside that range are rejected as input
    validation errors.'
    """
    bundle = setup_three_lawyers_and_active_case()
    res = api.list_cases(bundle["partner_headers"], params={"limit": 101})
    validate_error(res, "ERR_VALIDATION_FAILED", expected_status=422)


def test_pagination_limit_below_min(api):
    """PRD §2.3: 'The default limit is 10, the minimum is 1, and the
    maximum is 100; values outside that range are rejected as input
    validation errors.'

    Claim: limit=0 → ERR_VALIDATION_FAILED.
    """
    bundle = setup_three_lawyers_and_active_case()
    res = api.list_cases(bundle["partner_headers"], params={"limit": 0})
    validate_error(res, "ERR_VALIDATION_FAILED", expected_status=422)


def test_pagination_offset_past_end(api):
    """PRD §2.3: 'has_more (true when more rows remain past the current
    window).'

    Claim: with offset past total_count, has_more is false and data empty.
    """
    bundle = setup_three_lawyers_and_active_case()
    data, meta = validate_paginated(
        api.list_cases(bundle["partner_headers"], params={"offset": 9999})
    )
    assert data == []
    assert meta["has_more"] is False


# ---------------------------------------------------------------------------
# UUID + version + timestamp shape
# ---------------------------------------------------------------------------
def test_id_is_uuid_and_immutable(api):
    """PRD §2.4: 'Every persisted entity carries an id that is a
    server-minted UUID; identifiers are opaque strings without a type
    prefix and are immutable for the life of the row.'
    """
    partner, partner_headers = make_partner_lawyer()
    assert is_valid_uuid(partner["id"])
    fetched = validate_success(
        api.get_lawyer(partner["id"], partner_headers), 200
    )
    assert fetched["id"] == partner["id"]


def test_version_starts_at_one(api):
    """PRD §2.4: 'version (an integer that starts at 1 on creation and is
    incremented by exactly one on every mutation, including system-driven
    mutations such as posture recomputation or status cascades).'
    """
    partner, partner_headers = make_partner_lawyer()
    assert partner["version"] == 1
