"""Envelope shape, pagination, computed reads, and immediate consistency."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    create_employer,
    create_active_plan,
    create_member,
    create_enrollment,
    create_funding_account,
    get_success_data,
    is_valid_uuid,
    standard_world,
    submit_claim,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_error_envelope_shape(api, admin_headers):
    """PRD §2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that
    identifies the specific error."

    Design: Corner/errors/error_envelope_shape
    """
    resp = api.get_claim("7b2e0d1c-4a5f-4c93-8e7d-31a6c5b2d4e9", admin_headers)
    body = resp.json()
    assert resp.status_code == 404, f"expected 404, got {resp.status_code}: {body}"
    assert body["response_type"] == "error"
    assert body["data"]["error_id"] == "ERR_CLAIM_NOT_FOUND"
    assert isinstance(body["data"]["message"], str) and body["data"]["message"]
    assert isinstance(body["meta"]["api_request_id"], str) and body["meta"]["api_request_id"]
    assert "api_request_timestamp" in body["meta"]


def test_get_member_not_found_returns_404(api, admin_headers):
    """PRD §2.9: "The per-entity not-found errors are `ERR_EMPLOYER_NOT_FOUND`,
    `ERR_PLAN_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`, ..."

    Design: Corner/entities/get_member_not_found_returns_404
    """
    resp = api.get_member("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", admin_headers)
    validate_error(resp, ApiErrorId.ERR_MEMBER_NOT_FOUND)


def test_missing_auth_headers_unauthenticated(api, admin_headers):
    """PRD §2.1: "A request with missing or unrecognized headers — or whose
    entity-backed identifier does not resolve to an existing record — is
    rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/missing_auth_headers_unauthenticated
    """
    employer = create_employer()
    resp = api.get_employer(employer["id"], {"Content-Type": "application/json"})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_members_list_pagination_defaults(api, admin_headers):
    """PRD §2.3: "The `limit` parameter sets the maximum number of items
    returned; it defaults to 10, with a minimum of 1 and a maximum of 100.
    The `offset` parameter sets how many items to skip and defaults to 0."
    PRD §2.3: "The `meta` object of a list response carries the pagination
    fields `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/endpoints/members_list_pagination_defaults
    """
    employer = create_employer()
    plan = create_active_plan(employer["id"])
    create_member(employer["id"], plan["id"])

    resp = api.list_members(admin_headers)
    data, meta = validate_paginated(resp)
    assert meta["limit"] == 10, f"default limit must be 10, got {meta['limit']}"
    assert meta["offset"] == 0, f"default offset must be 0, got {meta['offset']}"
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert resp.json()["response_type"] == "array"


def test_members_filtered_by_employer(api, admin_headers):
    """PRD §3.2: "Member lists can be filtered by `employer_id`, `plan_id`,
    and `eligibility_status`."

    Design: Corner/endpoints/members_filtered_by_employer
    """
    emp1 = create_employer(name="ACME")
    plan1 = create_active_plan(emp1["id"], name="P1")
    m1 = create_member(emp1["id"], plan1["id"], external_ref="E1", full_name="Mem One")
    emp2 = create_employer(name="BETA", funding_model="PAY_AS_YOU_GO")
    plan2 = create_active_plan(emp2["id"], name="P2")
    create_member(emp2["id"], plan2["id"], external_ref="E2", full_name="Mem Two")

    resp = api.list_members(admin_headers, params={"employer_id": emp1["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1, f"expected 1 member for employer1, got {meta['total_count']}"
    assert len(data) == 1
    assert data[0]["id"] == m1["id"]


def test_enrollment_allowance_computed_read(api, admin_headers):
    """PRD §3.4: "A computed allowance read is available to `BenefitsAdmin`,
    `Auditor`, and the owning `Member`, returning `enrollment_id`,
    `annual_allowance_cents`, `used_cents`, `reserved_cents`, the derived
    `remaining_cents`, the current `quarter_key`, `quarter_used_cents`, and
    `quarterly_remaining_cents`."
    PRD §3.7: "On successful submission the claim reserves against the
    allowance: the enrollment's `reserved_cents` increases by
    `claimed_amount_cents`."

    Design: Corner/endpoints/enrollment_allowance_computed_read
    """
    world = standard_world()
    submit_claim(world, 2000, "R-AR")

    resp = api.get_enrollment_allowance(world["enrollment"]["id"], admin_headers)
    allowance = validate_success(resp)
    assert allowance["annual_allowance_cents"] == 30000
    assert allowance["used_cents"] == 0
    assert allowance["reserved_cents"] == 2000
    assert allowance["remaining_cents"] == 28000
    assert allowance["quarter_key"] == "2026-Q2", (
        f"default clock 2026-05-01 is Q2, got {allowance['quarter_key']}"
    )


def test_write_read_immediate_consistency(api, admin_headers, auditor_headers):
    """PRD §2.8: "Derived totals — allowance counters such as `used_cents` and
    `reserved_cents`, funding counters such as `available_cents` and
    `disbursed_cents` — are reconciled immediately as each event is applied,
    never lazily at read time."

    Design: Corner/consistency_model/write_read_immediate_consistency
    """
    employer = create_employer(name="READBACK", funding_model="PAY_AS_YOU_GO")
    resp = api.get_employer(employer["id"], auditor_headers)
    data = validate_success(resp)
    assert data["name"] == "READBACK"
    assert data["funding_model"] == "PAY_AS_YOU_GO"
    assert data["version"] == 1
