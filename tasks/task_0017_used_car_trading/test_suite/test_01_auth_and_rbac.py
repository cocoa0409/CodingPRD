"""Tests for PRD §2.1 (User and Role-Based Access Control) and §2.7
(Nested Resource Path Validation) — authentication, authorisation, ownership,
and not-found cardinal rules.
"""

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    api_client,
    build_user_headers,
    create_seller_payload,
    create_vehicle_payload,
    make_buyer_headers,
    make_seller_headers,
    register_buyer,
    register_seller,
    register_vehicle,
    setup_active_listing,
    validate_error,
)


# ──────────────────────────────────────────────────────────
# §2.1 ERR_AUTH_MISSING — missing headers
# ──────────────────────────────────────────────────────────


def test_create_seller_without_any_headers_returns_auth_missing(api):
    """PRD §2.1: "Every request must carry two HTTP headers: X-User-ID and
    X-User-Role. Either missing yields ERR_AUTH_MISSING with HTTP 401."
    """
    res = api.create_seller(create_seller_payload(), headers={})
    validate_error(res, "ERR_AUTH_MISSING")


def test_create_seller_without_user_id_returns_auth_missing(api):
    """PRD §2.1: "Every request must carry two HTTP headers: X-User-ID and
    X-User-Role. Either missing yields ERR_AUTH_MISSING with HTTP 401."
    """
    res = api.create_seller(create_seller_payload(), headers={"X-User-Role": "Seller"})
    validate_error(res, "ERR_AUTH_MISSING")


def test_create_seller_without_user_role_returns_auth_missing(api):
    """PRD §2.1: "Every request must carry two HTTP headers: X-User-ID and
    X-User-Role. Either missing yields ERR_AUTH_MISSING with HTTP 401."
    """
    res = api.create_seller(
        create_seller_payload(),
        headers={"X-User-ID": "00000000-0000-4000-8000-00000000fb01"},
    )
    validate_error(res, "ERR_AUTH_MISSING")


# ──────────────────────────────────────────────────────────
# §2.1 ERR_AUTH_INVALID — unrecognised role / malformed user id
# ──────────────────────────────────────────────────────────


def test_unrecognised_role_returns_auth_invalid(api):
    """PRD §2.1: "An unrecognised role string, or an X-User-ID that is empty
    or not a well-formed UUID, yields ERR_AUTH_INVALID with HTTP 401."
    """
    res = api.create_seller(
        create_seller_payload(),
        headers={
            "X-User-ID": "00000000-0000-4000-8000-00000000fb01",
            "X-User-Role": "Wizard",
        },
    )
    validate_error(res, "ERR_AUTH_INVALID")


def test_empty_user_id_returns_auth_invalid(api):
    """PRD §2.1: "an X-User-ID that is empty or not a well-formed UUID,
    yields ERR_AUTH_INVALID with HTTP 401."
    """
    res = api.create_seller(
        create_seller_payload(),
        headers={"X-User-ID": "", "X-User-Role": "Seller"},
    )
    validate_error(res, "ERR_AUTH_INVALID")


def test_malformed_uuid_user_id_returns_auth_invalid(api):
    """PRD §2.1: "an X-User-ID that is empty or not a well-formed UUID,
    yields ERR_AUTH_INVALID with HTTP 401."
    """
    res = api.create_seller(
        create_seller_payload(),
        headers={"X-User-ID": "not-a-uuid", "X-User-Role": "Seller"},
    )
    validate_error(res, "ERR_AUTH_INVALID")


# ──────────────────────────────────────────────────────────
# §2.1 ERR_FORBIDDEN — role lacks permission per RBAC matrix in §4
# ──────────────────────────────────────────────────────────


def test_buyer_cannot_register_vehicle(api):
    """PRD §2.1: "When the headers are present and parseable but the role is
    not authorised to invoke the requested endpoint per the RBAC matrix in §4,
    the server returns ERR_FORBIDDEN with HTTP 403."
    PRD §4: POST /vehicles is authorized to Seller only.
    """
    buyer = register_buyer()
    res = api.create_vehicle(create_vehicle_payload(), make_buyer_headers(buyer["id"]))
    validate_error(res, "ERR_FORBIDDEN")


def test_seller_cannot_run_credit_check(api):
    """PRD §2.1: "When the headers are present and parseable but the role is
    not authorised to invoke the requested endpoint per the RBAC matrix in §4,
    the server returns ERR_FORBIDDEN with HTTP 403."
    PRD §4 RBAC matrix: POST /loans/{id}/run-credit-check is PlatformAdmin only.
    """
    seller = register_seller()
    res = api.run_credit_check(NON_EXISTENT_UUID, make_seller_headers(seller["id"]))
    validate_error(res, "ERR_FORBIDDEN")


def test_inspector_cannot_create_listing(api):
    """PRD §2.1: "When the headers are present and parseable but the role is
    not authorised to invoke the requested endpoint per the RBAC matrix in §4,
    the server returns ERR_FORBIDDEN with HTTP 403."
    PRD §4 RBAC matrix: POST /listings is authorized to Seller only.
    """
    res = api.create_listing(
        {
            "vehicle_id": NON_EXISTENT_UUID,
            "assessment_report_id": NON_EXISTENT_UUID,
            "sale_mode": "FIXED_PRICE",
            "ask_price_cents": 1_000_000,
            "photo_urls": [],
            "documents_authentic_flag": False,
        },
        build_user_headers("00000000-0000-4000-8000-0000000a1501", "Inspector"),
    )
    validate_error(res, "ERR_FORBIDDEN")


def test_buyer_cannot_approve_listing(api):
    """PRD §2.1: "When the headers are present and parseable but the role is
    not authorised to invoke the requested endpoint per the RBAC matrix in §4,
    the server returns ERR_FORBIDDEN with HTTP 403."
    PRD §4 RBAC matrix: POST /listings/{id}/approve is PlatformAdmin only.
    """
    seller, vehicle, _, listing = setup_active_listing()
    buyer = register_buyer()
    res = api.approve_listing(listing["id"], make_buyer_headers(buyer["id"]))
    validate_error(res, "ERR_FORBIDDEN")


# ──────────────────────────────────────────────────────────
# §2.1 ERR_NOT_OWNER — caller does not own the targeted resource
# ──────────────────────────────────────────────────────────


def test_seller_cannot_delist_anothers_listing(api):
    """PRD §2.1: "A request that satisfies authentication and authorisation
    but targets a resource the caller does not own is rejected with
    ERR_NOT_OWNER and HTTP 403. This applies to all mutating operations
    (POST, PATCH, DELETE) on Vehicle, Listing, Bid, Reservation,
    PurchaseOrder, Loan, WarrantyClaim, and DisputeCase resources whose
    owner is the acting role."
    """
    seller_a, vehicle, _, listing = setup_active_listing()
    seller_b = register_seller()
    res = api.delist_listing(listing["id"], make_seller_headers(seller_b["id"]))
    validate_error(res, "ERR_NOT_OWNER")


def test_buyer_cannot_cancel_anothers_bid(api):
    """PRD §2.1: "A request that satisfies authentication and authorisation
    but targets a resource the caller does not own is rejected with
    ERR_NOT_OWNER and HTTP 403. This applies to all mutating operations
    (POST, PATCH, DELETE) on Vehicle, Listing, Bid, Reservation,
    PurchaseOrder, Loan, WarrantyClaim, and DisputeCase resources whose
    owner is the acting role."
    """
    from test_helpers import place_bid, register_buyer as _rb, setup_auction_with_two_bidders

    _, listing, _, buyer_a, buyer_b = setup_auction_with_two_bidders(
        ask_price_cents=1_000_000, reserve_price_cents=1_000_000
    )
    bid_a = place_bid(buyer_a, listing, 1_050_000)
    res = api.cancel_bid(bid_a["id"], make_buyer_headers(buyer_b["id"]))
    validate_error(res, "ERR_NOT_OWNER")


# ──────────────────────────────────────────────────────────
# §2.7 ERR_NOT_FOUND — left-to-right path validation
# ──────────────────────────────────────────────────────────


def test_get_vehicle_with_nonexistent_id_returns_not_found(api, admin_headers):
    """PRD §2.7: "URL paths are validated left to right. A request to
    /vehicles/{vehicle_id}/assessments whose vehicle_id does not resolve fails
    with ERR_NOT_FOUND and HTTP 404 before any attempt is made to interpret
    the body."
    """
    res = api.get_vehicle(NON_EXISTENT_UUID, admin_headers)
    validate_error(res, "ERR_NOT_FOUND")


def test_create_assessment_on_nonexistent_vehicle_returns_not_found(api, inspector_headers):
    """PRD §2.7: "A request to /vehicles/{vehicle_id}/assessments whose
    vehicle_id does not resolve fails with ERR_NOT_FOUND and HTTP 404 before
    any attempt is made to interpret the body."
    """
    from test_helpers import create_assessment_payload

    res = api.create_assessment(
        NON_EXISTENT_UUID, create_assessment_payload(), inspector_headers
    )
    validate_error(res, "ERR_NOT_FOUND")


def test_listing_creation_with_nonexistent_assessment_returns_not_found(api):
    """PRD §2.7: "Body-referenced foreign keys (vehicle_id, listing_id,
    purchase_order_id, assessment_report_id, and so on) are likewise rejected
    with ERR_NOT_FOUND if the referenced row does not exist."
    """
    seller = register_seller()
    vehicle = register_vehicle(seller)
    res = api.create_listing(
        {
            "vehicle_id": vehicle["id"],
            "assessment_report_id": NON_EXISTENT_UUID,
            "sale_mode": "FIXED_PRICE",
            "ask_price_cents": 1_000_000,
            "photo_urls": [],
            "documents_authentic_flag": False,
        },
        make_seller_headers(seller["id"]),
    )
    validate_error(res, "ERR_NOT_FOUND")
