"""Tests for PRD §3.1 (party onboarding) and §2.3 (pagination), plus
PRD §2.2 envelope assertions on Seller/Buyer creation.
"""

import pytest

from test_helpers import (
    api_client,
    assert_buyer,
    assert_seller,
    create_buyer_payload,
    create_seller_payload,
    make_buyer_headers,
    register_buyer,
    register_seller,
    validate_error,
    validate_paginated,
    validate_success,
)


# ──────────────────────────────────────────────────────────
# Seller registration
# ──────────────────────────────────────────────────────────


def test_seller_registration_returns_pending_kyc_and_zero_listings(api, admin_headers):
    """PRD §3.1: "A new Seller enters with kyc_status PENDING (which over time
    may transition to VERIFIED or REJECTED) and a total_listings counter
    starting at zero."
    """
    payload = create_seller_payload()
    res = api.create_seller(payload, admin_headers)
    seller = validate_success(res, expected_status=201)
    assert_seller(seller)
    assert seller["kyc_status"] == "PENDING"
    assert seller["total_listings"] == 0
    assert seller["legal_name"] == payload["legal_name"]
    assert seller["id_document_number"] == payload["id_document_number"]


def test_duplicate_seller_id_document_rejected(api, admin_headers):
    """PRD §3.1: "an id_document_number (the government-issued identifier or
    business registration number, which is unique across the platform —
    duplicates fail at insertion time)".
    """
    seller_a = register_seller()
    res = api.create_seller(
        create_seller_payload(id_document_number=seller_a["id_document_number"]),
        admin_headers,
    )
    # PRD says "duplicates fail at insertion time" without naming an error_id
    # (silence-pattern: error-precedence). Any 4xx with one of the validation
    # error_ids satisfies the contract.
    assert res.status_code >= 400, (
        "PRD §3.1 says duplicate id_document_number must fail; got "
        f"status {res.status_code}"
    )


# ──────────────────────────────────────────────────────────
# Buyer registration
# ──────────────────────────────────────────────────────────


def test_buyer_registration_starts_with_zero_deposits(api, admin_headers):
    """PRD §3.1: "A new Buyer enters with deposit_held_cents and
    deposit_balance_cents both at zero; the running invariant is that those
    two fields remain equal at all times."
    """
    res = api.create_buyer(create_buyer_payload(), admin_headers)
    buyer = validate_success(res, expected_status=201)
    assert_buyer(buyer)
    assert buyer["deposit_held_cents"] == 0
    assert buyer["deposit_balance_cents"] == 0


def test_get_buyer_reflects_current_holds_invariant(api):
    """PRD §3.1: "the running invariant is that those two fields remain
    equal at all times."
    PRD §3.7: "The two computed fields deposit_held_cents and
    deposit_balance_cents must remain equal at all times."
    """
    buyer = register_buyer()
    res = api.get_buyer(buyer["id"], make_buyer_headers(buyer["id"]))
    fetched = validate_success(res, expected_status=200)
    assert fetched["deposit_held_cents"] == fetched["deposit_balance_cents"]


# ──────────────────────────────────────────────────────────
# Pagination — PRD §2.3
# ──────────────────────────────────────────────────────────


def test_pagination_limit_below_one_rejected(api, admin_headers):
    """PRD §2.3: "The accepted range for limit is from 1 to 100 inclusive on
    both ends; offset must be at least 0. A value outside these ranges is
    rejected with ERR_PAGINATION_INVALID and HTTP 400."
    """
    res = api.list_vehicles(admin_headers, params={"limit": 0})
    validate_error(res, "ERR_PAGINATION_INVALID")


def test_pagination_limit_above_one_hundred_rejected(api, admin_headers):
    """PRD §2.3: "The accepted range for limit is from 1 to 100 inclusive on
    both ends ... A value outside these ranges is rejected with
    ERR_PAGINATION_INVALID and HTTP 400."
    """
    res = api.list_vehicles(admin_headers, params={"limit": 101})
    validate_error(res, "ERR_PAGINATION_INVALID")


def test_pagination_negative_offset_rejected(api, admin_headers):
    """PRD §2.3: "offset must be at least 0. A value outside these ranges is
    rejected with ERR_PAGINATION_INVALID and HTTP 400."
    """
    res = api.list_vehicles(admin_headers, params={"offset": -1})
    validate_error(res, "ERR_PAGINATION_INVALID")


def test_pagination_meta_includes_total_count_and_has_more(api, admin_headers):
    """PRD §2.3: "The meta block on list responses includes limit, offset,
    total_count (the total number of rows matching the filter, ignoring
    limit/offset), and has_more (a boolean that is true exactly when
    offset + limit < total_count)."
    """
    # Seed enough data — register one seller and three vehicles.
    seller = register_seller()
    for _ in range(3):
        from test_helpers import register_vehicle

        register_vehicle(seller)
    data, meta = validate_paginated(
        api.list_vehicles(admin_headers, params={"limit": 2, "offset": 0})
    )
    assert "total_count" in meta
    assert "has_more" in meta
    assert meta["limit"] == 2
    assert meta["offset"] == 0
    if meta["total_count"] > 2:
        assert meta["has_more"] is True
        assert meta["offset"] + meta["limit"] < meta["total_count"]
    assert len(data) <= 2
