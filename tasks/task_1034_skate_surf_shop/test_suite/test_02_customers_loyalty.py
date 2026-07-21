"""Customers, loyalty accrual, tier reconciliation, and redemption.

Difficulty instances: loyalty_accrual_tiered_event_multiplier_mode_a,
loyalty_tier_gold_threshold_inclusive. Corner instances: missing-required,
insufficient-points, computed-read.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    make_customer_headers,
)
import test_helpers as th

SM = TEST_USERS["shop_manager_headers"]
SA = TEST_USERS["sales_associate_headers"]


# --------------------------------------------------------------------------- #
# Difficulty: combinatorial loyalty accrual (tier + event multiplier)
# --------------------------------------------------------------------------- #
def test_silver_earn_accrues_with_tier_multiplier(api):
    """PRD §2.7: "That base-point figure is then multiplied by the customer's tier multiplier and, for event registrations only, an event bonus multiplier; a single floor is applied to the product at the very end, never to any intermediate factor, and the floored result is added to `loyalty_points`."
    PRD §2.7: "The tier multiplier is 1.0 for `BRONZE`, 1.25 for `SILVER`, and 1.5 for `GOLD`."

    Design: Difficulty/combinatorial_formula/loyalty_accrual_tiered_event_multiplier_mode_a
    """
    customer = th.create_customer(api, email="loy@x.com", full_name="Loyal Sam")
    # Promote to SILVER first: EARN 60000 -> 600 base points at BRONZE, lifetime 60000 -> SILVER.
    validate_success(api.loyalty_adjustment(customer["id"], {"kind": "EARN", "spend_cents": 60000}, SA))
    # Now a SILVER earn of 12345: floor(floor(12345/100) * 1.25) = floor(123*1.25) = 153 added.
    resp = api.loyalty_adjustment(customer["id"], {"kind": "EARN", "spend_cents": 12345}, SA)
    data = validate_success(resp, expected_status=200)
    assert data["loyalty_points"] == 753
    assert data["tier"] == "SILVER"
    assert data["lifetime_spend_cents"] == 72345


def test_tier_multiplier_is_snapshot_before_spend(api):
    """PRD §2.7: "Critically, the tier multiplier is read from the customer's tier as it stands *before* the current transaction's spend is applied — the tier snapshot precedes the spend, not follows it."

    Design: Difficulty/combinatorial_formula/loyalty_accrual_tiered_event_multiplier_mode_a
    """
    customer = th.create_customer(api, email="snap@x.com", full_name="Snap Shot")
    # A single EARN of 60000 that crosses into SILVER must accrue at the BRONZE
    # snapshot (1.0), i.e. 600 points — not 600*1.25.
    resp = api.loyalty_adjustment(customer["id"], {"kind": "EARN", "spend_cents": 60000}, SA)
    data = validate_success(resp, expected_status=200)
    assert data["loyalty_points"] == 600
    assert data["tier"] == "SILVER"
    assert data["lifetime_spend_cents"] == 60000


# --------------------------------------------------------------------------- #
# Difficulty: GOLD tier threshold boundary (inclusive >=)
# --------------------------------------------------------------------------- #
def test_earn_exactly_gold_threshold_lands_gold(api):
    """PRD §2.7: "A customer whose lifetime spend is at least 100000 cents is `GOLD`; a customer at least 50000 cents but below that is `SILVER`; anyone below 50000 cents is `BRONZE`. Both thresholds are inclusive lower bounds."

    Design: Difficulty/boundary_precision_check/loyalty_tier_gold_threshold_inclusive
    """
    customer = th.create_customer(api, email="gold@x.com", full_name="Goldie")
    resp = api.loyalty_adjustment(customer["id"], {"kind": "EARN", "spend_cents": 100000}, SA)
    data = validate_success(resp, expected_status=200)
    assert data["lifetime_spend_cents"] == 100000
    assert data["tier"] == "GOLD"
    assert data["loyalty_points"] == 1000  # floor(100000/100) * 1.0 (BRONZE snapshot)


def test_earn_one_below_gold_threshold_stays_silver(api):
    """PRD §2.7: "A customer whose lifetime spend is at least 100000 cents is `GOLD`; a customer at least 50000 cents but below that is `SILVER`; anyone below 50000 cents is `BRONZE`. Both thresholds are inclusive lower bounds."

    Design: Difficulty/boundary_precision_check/loyalty_tier_gold_threshold_inclusive
    """
    customer = th.create_customer(api, email="silv@x.com", full_name="Silvia")
    resp = api.loyalty_adjustment(customer["id"], {"kind": "EARN", "spend_cents": 99999}, SA)
    data = validate_success(resp, expected_status=200)
    assert data["lifetime_spend_cents"] == 99999
    assert data["tier"] == "SILVER"
    assert data["loyalty_points"] == 999  # floor(99999/100) * 1.0 (BRONZE snapshot)


# --------------------------------------------------------------------------- #
# Corner instances
# --------------------------------------------------------------------------- #
def test_create_customer_missing_full_name_returns_validation(api):
    """PRD §3.2: "who supplies the customer's `email` (unique across customers) and `full_name`."
    PRD §2.10: "A well-formedness failure — a missing required field ... — is always reported as `ERR_VALIDATION` (HTTP 400)."

    Design: Corner/entities/customer_create_missing_required_returns_invalid_request
    """
    resp = api.create_customer({"email": "x@x.com"}, SA)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_redeem_more_points_than_available_returns_402(api):
    """PRD §3.2: "A `REDEEM` adjustment supplies `points`: that many points are subtracted from `loyalty_points`, which may not be driven below zero — a redemption exceeding the member's available `loyalty_points` is refused with `ERR_INSUFFICIENT_POINTS`."

    Design: Corner/validations/loyalty_redeem_insufficient_points_returns_402
    """
    customer = th.create_customer(api, email="ip@x.com", full_name="In Sufficient")
    resp = api.loyalty_adjustment(customer["id"], {"kind": "REDEEM", "points": 50}, SA)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_POINTS.value)
    reread = validate_success(api.get_customer(customer["id"], SA))
    assert reread["loyalty_points"] == 0


def test_customer_get_reflects_earn_computed_fields(api):
    """PRD §2.7: "A customer whose lifetime spend is at least 100000 cents is `GOLD`; a customer at least 50000 cents but below that is `SILVER`; anyone below 50000 cents is `BRONZE`. Both thresholds are inclusive lower bounds."

    Design: Corner/endpoints/customer_get_reflects_earn_computed_read
    """
    customer = th.create_customer(api, email="cr@x.com", full_name="Comp Read")
    validate_success(api.loyalty_adjustment(customer["id"], {"kind": "EARN", "spend_cents": 50000}, SA))
    resp = api.get_customer(customer["id"], make_customer_headers(customer["id"]))
    data = validate_success(resp, expected_status=200)
    assert data["loyalty_points"] == 500
    assert data["tier"] == "SILVER"
