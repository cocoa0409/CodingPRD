"""Tests for PRD §3.8 — Warranty activation, coverage scope by package,
expiry via clock advance, claim filing rules and approved-amount cap math.
"""

from datetime import datetime, timedelta, timezone

import pytest

from test_helpers import (
    advance_clock_payload,
    api_client,
    assert_warranty,
    assert_warranty_claim,
    assert_warranty_coverage_matches_package,
    make_buyer_headers,
    server_now_plus,
    setup_paid_purchase_order,
    validate_error,
    validate_success,
    warranty_claim_payload,
    WARRANTY_COVERAGE_SCOPE,
)


# ──────────────────────────────────────────────────────────
# §3.8 Activation & coverage
# ──────────────────────────────────────────────────────────


@pytest.mark.parametrize("package_code", ["BASIC", "STANDARD", "PREMIUM"])
def test_warranty_coverage_scope_matches_package(api, admin_headers, package_code):
    """PRD §3.8: "The package code determines the coverage_scope: BASIC
    covers [POWERTRAIN], STANDARD covers [POWERTRAIN, ELECTRICAL, COOLING],
    and PREMIUM covers [POWERTRAIN, ELECTRICAL, COOLING, INFOTAINMENT,
    SUSPENSION, INTERIOR]."
    """
    state = setup_paid_purchase_order(package_code=package_code, ask_price_cents=2_000_000)
    warranty = state["warranty"]
    assert warranty is not None
    assert warranty["package_code"] == package_code
    assert_warranty_coverage_matches_package(warranty, WARRANTY_COVERAGE_SCOPE[package_code])


def test_warranty_active_after_paid(api):
    """PRD §3.8: "Activation fires as part of the order's PAID cascade: the
    warranty moves from PENDING_ACTIVATION to ACTIVE."
    """
    state = setup_paid_purchase_order(package_code="STANDARD", ask_price_cents=2_000_000)
    warranty = state["warranty"]
    assert warranty["status"] == "ACTIVE"
    assert warranty["effective_at"] is not None


# ──────────────────────────────────────────────────────────
# §3.8 Expiry via clock advance
# ──────────────────────────────────────────────────────────


def test_warranty_expires_after_clock_past_expires_at(api, admin_headers):
    """PRD §3.8: "When the platform clock advances past expires_at, the
    warranty transitions from ACTIVE to EXPIRED."
    """
    state = setup_paid_purchase_order(package_code="BASIC", ask_price_cents=2_000_000)
    warranty = state["warranty"]
    expires = warranty["expires_at"]
    assert expires is not None
    # Advance well past — three years should be safely beyond all packages.
    far_future = server_now_plus(timedelta(days=365 * 3))
    api.advance_clock(
        advance_clock_payload(far_future),
        admin_headers,
    )
    refreshed = validate_success(api.get_warranty(warranty["id"], admin_headers), 200)
    assert refreshed["status"] == "EXPIRED"


def test_claim_on_expired_warranty_rejected(api):
    """PRD §3.8: "The claim is admissible only while the warranty is ACTIVE
    and the current instant is strictly before expires_at; otherwise
    ERR_WARRANTY_NOT_ACTIVE fires."
    """
    state = setup_paid_purchase_order(package_code="BASIC", ask_price_cents=2_000_000)
    warranty = state["warranty"]
    buyer = state["buyer"]
    # Advance clock past warranty expiry.
    far_future = server_now_plus(timedelta(days=365 * 3))
    api.advance_clock(
        advance_clock_payload(far_future),
        {"X-User-ID": "00000000-0000-4000-8000-00000000ad01", "X-User-Role": "PlatformAdmin"},
    )
    res = api.file_warranty_claim(
        warranty["id"],
        warranty_claim_payload(component="POWERTRAIN", claimed_amount_cents=100_000),
        make_buyer_headers(buyer["id"]),
    )
    validate_error(res, "ERR_WARRANTY_NOT_ACTIVE")


# ──────────────────────────────────────────────────────────
# §3.8 Claim filing rules
# ──────────────────────────────────────────────────────────


def test_claim_with_uncovered_component_rejected(api):
    """PRD §3.8: "the component (which must be in coverage_scope — otherwise
    ERR_COMPONENT_NOT_COVERED)".

    BASIC covers [POWERTRAIN] only; INFOTAINMENT must reject.
    """
    state = setup_paid_purchase_order(package_code="BASIC", ask_price_cents=2_000_000)
    warranty = state["warranty"]
    buyer = state["buyer"]
    res = api.file_warranty_claim(
        warranty["id"],
        warranty_claim_payload(component="INFOTAINMENT", claimed_amount_cents=100_000),
        make_buyer_headers(buyer["id"]),
    )
    validate_error(res, "ERR_COMPONENT_NOT_COVERED")


def test_claim_under_active_warranty_pending_state(api):
    """PRD §3.8: "A new claim enters in status PENDING. A platform admin
    approves the claim, advancing it from PENDING to APPROVED with the
    approved_amount_cents computed as the smallest of (a) the buyer's
    claimed_amount_cents, (b) the per-claim cap of two hundred thousand
    cents for BASIC, five hundred thousand cents for STANDARD, or one
    million five hundred thousand cents for PREMIUM ..."
    """
    state = setup_paid_purchase_order(package_code="STANDARD", ask_price_cents=2_000_000)
    warranty = state["warranty"]
    buyer = state["buyer"]
    res = api.file_warranty_claim(
        warranty["id"],
        warranty_claim_payload(component="ELECTRICAL", claimed_amount_cents=100_000),
        make_buyer_headers(buyer["id"]),
    )
    claim = validate_success(res, 201)
    assert_warranty_claim(claim)
    assert claim["status"] == "PENDING"
    assert claim["component"] == "ELECTRICAL"
    assert claim["claimed_amount_cents"] == 100_000


# ──────────────────────────────────────────────────────────
# §3.8 Approve cap math — three-way min
# ──────────────────────────────────────────────────────────


def test_claim_approval_uses_min_of_claimed_per_claim_cap_total_headroom(api, admin_headers):
    """PRD §3.8: "the approved_amount_cents computed as the smallest of (a)
    the buyer's claimed_amount_cents, (b) the per-claim cap of two hundred
    thousand cents for BASIC, five hundred thousand cents for STANDARD, or
    one million five hundred thousand cents for PREMIUM, and (c) the
    remaining headroom under the package's total cap, where the total cap
    is five hundred thousand cents for BASIC, two million cents for
    STANDARD, and six million cents for PREMIUM, and the headroom is the
    larger of zero and the total cap minus the warranty's running
    total_claim_payout_cents."

    BASIC: per-claim cap = 200_000. Claimed 300_000 → approved = 200_000.
    """
    state = setup_paid_purchase_order(package_code="BASIC", ask_price_cents=2_000_000)
    warranty = state["warranty"]
    buyer = state["buyer"]
    claim = validate_success(
        api.file_warranty_claim(
            warranty["id"],
            warranty_claim_payload(component="POWERTRAIN", claimed_amount_cents=300_000),
            make_buyer_headers(buyer["id"]),
        ),
        201,
    )
    approved = validate_success(api.approve_warranty_claim(claim["id"], admin_headers), 200)
    assert approved["status"] == "APPROVED"
    assert approved["approved_amount_cents"] == 200_000


def test_claim_approval_under_per_claim_cap_returns_claimed_amount(api, admin_headers):
    """PRD §3.8: "the approved_amount_cents computed as the smallest of (a)
    the buyer's claimed_amount_cents, (b) the per-claim cap of two hundred
    thousand cents for BASIC, five hundred thousand cents for STANDARD, or
    one million five hundred thousand cents for PREMIUM, and (c) the
    remaining headroom under the package's total cap".

    With claimed (50_000) below the per-claim cap and below total-cap
    headroom, the smallest of the three is the claimed amount itself.
    """
    state = setup_paid_purchase_order(package_code="STANDARD", ask_price_cents=2_000_000)
    warranty = state["warranty"]
    buyer = state["buyer"]
    claim = validate_success(
        api.file_warranty_claim(
            warranty["id"],
            warranty_claim_payload(component="POWERTRAIN", claimed_amount_cents=50_000),
            make_buyer_headers(buyer["id"]),
        ),
        201,
    )
    approved = validate_success(api.approve_warranty_claim(claim["id"], admin_headers), 200)
    assert approved["approved_amount_cents"] == 50_000


def test_claim_reject_advances_to_rejected(api, admin_headers):
    """PRD §3.8: "A platform admin may instead reject the claim, advancing
    it from PENDING to REJECTED."
    """
    state = setup_paid_purchase_order(package_code="STANDARD", ask_price_cents=2_000_000)
    warranty = state["warranty"]
    buyer = state["buyer"]
    claim = validate_success(
        api.file_warranty_claim(
            warranty["id"],
            warranty_claim_payload(component="POWERTRAIN", claimed_amount_cents=50_000),
            make_buyer_headers(buyer["id"]),
        ),
        201,
    )
    rejected = validate_success(api.reject_warranty_claim(claim["id"], admin_headers), 200)
    assert rejected["status"] == "REJECTED"
