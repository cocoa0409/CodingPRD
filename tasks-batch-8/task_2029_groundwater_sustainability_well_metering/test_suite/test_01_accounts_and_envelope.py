"""Account onboarding defaults and the fixed response envelope (PRD §2.2, §2.3, §3.1)."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_water_user_account,
    create_account_payload,
    is_iso8601_timestamp,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_account_creation_applies_defaults_and_fixed_clock(api, water_master_headers):
    """PRD §3.1: "The account begins in `ACTIVE` status, its `current_water_year` is stamped from the logical clock's calendar year, and every computed ledger counter — `extracted_af_ytd`, `pending_extraction_af`, `credit_balance_af`, `transfer_out_af_ytd`, `transfer_reserved_af`, and `penalty_balance_cents` — initializes to 0."
    PRD §2.5: "Before any operator sets it, the clock defaults to `2026-08-01T00:00:00Z`; the server never falls back to wall-clock time."
    PRD §2.4: "`version` is an integer that starts at 1 on creation and increments by exactly 1 on every mutation of the resource, including mutations caused by cascading side effects from operations on other resources (for example, when verifying an extraction report advances both the report's `version` and the owning account's `version`)."

    Design: Corner/entities/account_creation_applies_defaults_and_fixed_clock
    """
    resp = api.create_account(
        create_account_payload(
            holder_name="New Pumper", account_type="AGRICULTURAL", base_allocation_af=100.000
        ),
        water_master_headers,
    )
    data = validate_success(resp, 201)
    assert_water_user_account(data)

    assert data["status"] == "ACTIVE", f"new account must start ACTIVE, got {data['status']}"
    assert data["version"] == 1, f"version must start at 1, got {data['version']}"
    assert data["current_water_year"] == 2026, (
        f"current_water_year must be stamped from the default logical clock year 2026, "
        f"got {data['current_water_year']}"
    )
    for field in (
        "extracted_af_ytd",
        "pending_extraction_af",
        "credit_balance_af",
        "transfer_out_af_ytd",
        "transfer_reserved_af",
    ):
        assert data[field] == pytest.approx(0.0, abs=1e-9), (
            f"{field} must initialize to 0, got {data[field]}"
        )
    assert data["penalty_balance_cents"] == 0, (
        f"penalty_balance_cents must initialize to 0, got {data['penalty_balance_cents']}"
    )
    assert data["created_at"] == "2026-08-01T00:00:00.000Z", (
        f"created_at must equal the fixed startup clock instant, got {data['created_at']}"
    )


def test_response_envelope_shape_on_success_and_not_found(api, water_master_headers):
    """PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`."
    PRD §2.2: "The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`."
    PRD §2.3: "The `meta` block of a paginated list response carries `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/endpoints/response_envelope_shape_on_success_and_not_found
    """
    created = validate_success(
        api.create_account(
            create_account_payload(holder_name="Env Pumper", base_allocation_af=100.000),
            water_master_headers,
        ),
        201,
    )
    assert created["id"]

    # Success envelope on a list endpoint: response_type "array" + pagination meta.
    list_resp = api.list_accounts(water_master_headers)
    body = list_resp.json()
    assert list_resp.status_code == 200
    assert body["response_type"] == "array", (
        f"list responses must carry response_type 'array', got {body['response_type']!r}"
    )
    meta = body["meta"]
    assert isinstance(meta["api_request_id"], str) and meta["api_request_id"].startswith("req_")
    assert is_iso8601_timestamp(meta["api_request_timestamp"])
    assert isinstance(body["data"], list) and len(body["data"]) == 1
    assert meta["limit"] == 10, f"default limit must be 10, got {meta['limit']}"
    assert meta["offset"] == 0, f"default offset must be 0, got {meta['offset']}"
    assert meta["total_count"] == 1 and meta["has_more"] is False

    # Error envelope: response_type "error", data.error_id/message, minimal meta.
    err_resp = api.get_account("99999999-9999-4999-8999-999999999999", water_master_headers)
    validate_error(err_resp, ApiErrorId.ERR_ACCOUNT_NOT_FOUND)
    err_body = err_resp.json()
    assert err_body["response_type"] == "error"
    assert set(err_body["meta"].keys()) == {"api_request_id", "api_request_timestamp"}, (
        f"error meta must contain only api_request_id and api_request_timestamp, "
        f"got {sorted(err_body['meta'].keys())}"
    )
