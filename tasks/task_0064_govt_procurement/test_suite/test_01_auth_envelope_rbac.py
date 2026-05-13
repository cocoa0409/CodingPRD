"""Authentication, RBAC, response envelope, and pagination.

Covers PRD §2.1 (headers + RBAC), §2.2 (envelope), §2.3 (pagination).
"""
from __future__ import annotations
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    api_client,
    build_user_headers,
    create_plan_payload,
    create_supplier_payload,
    register_supplier,
    register_verified_supplier,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# PRD §2.1 — Auth headers
# ===========================================================================
def test_missing_user_id_header_rejected(api):
    """PRD §2.1: "Every request must carry the X-User-ID and X-User-Role
    headers, both non-empty. A request missing either header is rejected
    with ERR_AUTH_MISSING (401)."

    Claim: omitting X-User-ID → ERR_AUTH_MISSING.
    """
    res = api.create_plan(
        create_plan_payload(),
        headers={"X-User-Role": "ProcurementOfficer"},
    )
    validate_error(res, "ERR_AUTH_MISSING")


def test_missing_user_role_header_rejected(api):
    """PRD §2.1: "Every request must carry the X-User-ID and X-User-Role
    headers, both non-empty. A request missing either header is rejected
    with ERR_AUTH_MISSING (401)."
    """
    res = api.create_plan(
        create_plan_payload(),
        headers={"X-User-ID": "officer-001"},
    )
    validate_error(res, "ERR_AUTH_MISSING")


def test_empty_user_id_header_rejected(api):
    """PRD §2.1: "Every request must carry the X-User-ID and X-User-Role
    headers, both non-empty."
    """
    res = api.create_plan(
        create_plan_payload(),
        headers={"X-User-ID": "", "X-User-Role": "ProcurementOfficer"},
    )
    validate_error(res, "ERR_AUTH_MISSING")


def test_empty_user_role_header_rejected(api):
    """PRD §2.1: "Every request must carry the X-User-ID and X-User-Role
    headers, both non-empty."
    """
    res = api.create_plan(
        create_plan_payload(),
        headers={"X-User-ID": "officer-001", "X-User-Role": ""},
    )
    validate_error(res, "ERR_AUTH_MISSING")


def test_unknown_role_rejected_with_invalid_role(api):
    """PRD §2.1: "A request whose X-User-Role is not one of the four
    declared role names is rejected with ERR_AUTH_INVALID_ROLE (401)."

    Claim: a role outside {ProcurementOfficer, Supplier, EvaluationExpert,
    Regulator} → ERR_AUTH_INVALID_ROLE.
    """
    res = api.create_plan(
        create_plan_payload(),
        headers={"X-User-ID": "user-1", "X-User-Role": "Bystander"},
    )
    validate_error(res, "ERR_AUTH_INVALID_ROLE")


# ===========================================================================
# PRD §2.1 — RBAC: role not authorized
# ===========================================================================
def test_supplier_cannot_create_plan(api, supplier_fallback_headers):
    """PRD §2.1: "A request whose role is declared but is not authorised
    for the target endpoint is rejected with ERR_FORBIDDEN (403)."
    PRD §4: POST /procurement/plans is authorised for ProcurementOfficer
    only.
    """
    res = api.create_plan(create_plan_payload(), supplier_fallback_headers)
    validate_error(res, "ERR_FORBIDDEN")


def test_regulator_cannot_submit_bid(api, regulator_headers):
    """PRD §4: POST /procurement/projects/{id}/bids is authorised for
    Supplier only. PRD §2.1: non-authorised role → ERR_FORBIDDEN."""
    # Use a non-existent project id; auth check fires before existence.
    res = api.submit_bid(
        NON_EXISTENT_UUID,
        {
            "supplier_id": NON_EXISTENT_UUID,
            "tender_document_version": 1,
            "bid_price_cents": 1_000_000,
        },
        regulator_headers,
    )
    validate_error(res, "ERR_FORBIDDEN")


def test_supplier_cannot_blacklist(api, supplier_fallback_headers):
    """PRD §4: POST /procurement/suppliers/{id}/blacklist is authorised
    for Regulator only."""
    res = api.blacklist_supplier(
        NON_EXISTENT_UUID,
        {"blacklist_until": "2030-01-01T00:00:00.000Z"},
        supplier_fallback_headers,
    )
    validate_error(res, "ERR_FORBIDDEN")


def test_expert_cannot_form_committee(api, expert_headers):
    """PRD §4: POST /procurement/projects/{id}/form-committee is
    authorised for ProcurementOfficer only."""
    res = api.form_committee(
        NON_EXISTENT_UUID,
        {"requested_size": 3, "selection_seed": "s"},
        expert_headers,
    )
    validate_error(res, "ERR_FORBIDDEN")


def test_officer_cannot_uphold_complaint(api, officer_headers):
    """PRD §4: POST /procurement/complaints/{id}/uphold is authorised
    for Regulator only."""
    res = api.uphold_complaint(
        NON_EXISTENT_UUID,
        {"corrective_action": "FREEZE_PROJECT"},
        officer_headers,
    )
    validate_error(res, "ERR_FORBIDDEN")


# ===========================================================================
# PRD §2.6 — path-id resolution
# ===========================================================================
def test_get_supplier_unknown_id_returns_not_found(api, officer_headers):
    """PRD §2.6: "A missing path id yields ERR_NOT_FOUND (404)." """
    res = api.get_supplier(NON_EXISTENT_UUID, officer_headers)
    validate_error(res, "ERR_NOT_FOUND")


def test_get_plan_unknown_id_returns_not_found(api, officer_headers):
    """PRD §2.6: "A missing path id yields ERR_NOT_FOUND (404)." """
    res = api.get_plan(NON_EXISTENT_UUID, officer_headers)
    validate_error(res, "ERR_NOT_FOUND")


def test_get_project_unknown_id_returns_not_found(api, officer_headers):
    """PRD §2.6: "A missing path id yields ERR_NOT_FOUND (404)." """
    res = api.get_project(NON_EXISTENT_UUID, officer_headers)
    validate_error(res, "ERR_NOT_FOUND")


# ===========================================================================
# PRD §2.2 — Success envelope
# ===========================================================================
def test_success_envelope_structure(api, officer_headers):
    """PRD §2.2: "All successful API responses (those with 2xx status
    codes) follow this standard envelope format in their JSON body" —
    meta.api_request_id starts with "req_", api_request_timestamp ISO,
    response_type "object", data the resource.
    """
    sup = register_supplier()
    res = api.get_supplier(sup["id"], officer_headers)
    assert res.status_code == 200
    body = res.json()
    assert "meta" in body and "data" in body and "response_type" in body
    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"].startswith("req_"), (
        f"meta.api_request_id must start with req_, got "
        f"{body['meta']['api_request_id']!r}"
    )
    # PRD §2.2: api_request_timestamp is ISO 8601 UTC.
    assert "T" in body["meta"]["api_request_timestamp"]


def test_error_envelope_structure(api, officer_headers):
    """PRD §2.2: "All error API responses (4xx status codes) follow this
    standard envelope format ... data: { error_id, message }." """
    res = api.get_supplier(NON_EXISTENT_UUID, officer_headers)
    assert res.status_code == 404
    body = res.json()
    assert body.get("response_type") == "error"
    assert "error_id" in body["data"] and "message" in body["data"]
    assert body["data"]["error_id"] == "ERR_NOT_FOUND"


# ===========================================================================
# PRD §2.3 — Pagination
# ===========================================================================
def test_list_plans_default_pagination(api, officer_headers):
    """PRD §2.3: "Every list endpoint accepts two optional query
    parameters: limit and offset. limit defaults to 10, with a minimum
    of 1 and a maximum of 100; offset defaults to 0." Confirm the meta
    block carries the four required fields."""
    res = api.list_plans(officer_headers)
    data, meta = validate_paginated(res)
    assert isinstance(data, list)
    assert "total_count" in meta and "has_more" in meta
    assert "limit" in meta and "offset" in meta
    assert meta["limit"] == 10
    assert meta["offset"] == 0


def test_list_plans_respects_limit_offset(api, officer_headers):
    """PRD §2.3: "All list endpoints sort results by created_at
    ascending. The meta object on a list response carries limit, offset,
    total_count, and has_more."""
    res = api.list_plans(officer_headers, params={"limit": 5, "offset": 0})
    _data, meta = validate_paginated(res)
    assert meta["limit"] == 5
    assert meta["offset"] == 0
