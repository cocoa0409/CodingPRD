"""Churn scoring variants and subscription cyclic lifecycle / skip limits.

Difficulty queue: dual_variant_calc (churn), non_linear_state_machine (subscription cycle),
boundary_precision_check (skip limit), resource_temporal_overlap (renewal not due).
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    create_active_sku_with_lot, create_customer, create_active_subscription,
    setup_churn_customer_with_old_skips, setup_subscription_with_skips,
    setup_customer_with_active_subscription,
    make_customer_headers, TEST_USERS, ApiErrorId,
)

ADMIN = TEST_USERS["platform_admin_headers"]


# ───────────────────────── churn ACUTE vs CHRONIC ─────────────────────────

def test_churn_acute_below_chronic_when_skips_outside_window(api):
    """PRD §3.10: "The default (acute) variant — the one persisted on the customer —
    counts skips and failed payments only within the trailing 90-day window of the logical
    clock. A chronic variant, requested by a variant query parameter on the customer-risk
    endpoint, uses the customer's lifetime skip and failed-payment counts instead, with the
    same recency term; the two diverge whenever a customer has skips or failures older than
    90 days."

    Design: Difficulty/dual_variant_calc/dual_variant_churn_acute_vs_chronic
    """
    customer, sub = setup_churn_customer_with_old_skips(num_skips=2, due_iso="2026-06-30T00:00:00Z")
    cid = customer["id"]

    chronic = validate_success(api.get_customer_risk(cid, ADMIN, params={"variant": "CHRONIC"}), 200)
    acute = validate_success(api.get_customer_risk(cid, ADMIN, params={"variant": "ACUTE"}), 200)

    assert acute["churn_risk_score"] < chronic["churn_risk_score"], (
        "ACUTE window excludes the 2 old skips, so its skip term is 0; CHRONIC counts them")


def test_churn_acute_is_default_variant(api):
    """PRD §3.10: "With no variant supplied, the acute computation is returned."

    Design: Difficulty/dual_variant_calc/dual_variant_churn_acute_vs_chronic
    """
    customer, sub = setup_churn_customer_with_old_skips(num_skips=2, due_iso="2026-06-30T00:00:00Z")
    cid = customer["id"]
    default_risk = validate_success(api.get_customer_risk(cid, ADMIN), 200)
    acute = validate_success(api.get_customer_risk(cid, ADMIN, params={"variant": "ACUTE"}), 200)
    assert default_risk["churn_risk_score"] == acute["churn_risk_score"]


# ───────────────────────── subscription cyclic pause/resume ─────────────────────────

def test_subscription_pause_then_resume_returns_active(api):
    """PRD §3.8: "Resuming a PAUSED subscription (PAUSED → ACTIVE) requires that its selected
    SKU is ACTIVE and has available_units of at least 1; resume resets consecutive_skip_count
    to 0 and sets next_renewal_iso to the current clock plus cadence_days."

    Design: Difficulty/non_linear_state_machine/nonlinear_subscription_cyclic_pause_resume
    """
    customer, sku, lot, sub = setup_customer_with_active_subscription(tier="STARTER", cadence_days=14)
    cid = customer["id"]
    paused = validate_success(api.pause_subscription(sub["id"], make_customer_headers(cid)), 200)
    assert paused["status"] == "PAUSED"
    resumed = validate_success(api.resume_subscription(sub["id"], make_customer_headers(cid)), 200)
    assert resumed["status"] == "ACTIVE", "PAUSED -> ACTIVE resume closes the cycle"
    assert resumed["consecutive_skip_count"] == 0


def test_subscription_explicit_pause_from_active(api):
    """PRD §3.8: "A subscriber may also explicitly pause an ACTIVE subscription (ACTIVE → PAUSED)"

    Design: Difficulty/non_linear_state_machine/nonlinear_subscription_cyclic_pause_resume
    """
    customer, sku, lot, sub = setup_customer_with_active_subscription(tier="STARTER", cadence_days=14)
    cid = customer["id"]
    paused = validate_success(api.pause_subscription(sub["id"], make_customer_headers(cid)), 200)
    assert paused["status"] == "PAUSED"


# ───────────────────────── skip limit boundary ─────────────────────────

def test_third_skip_auto_pauses_and_fourth_skip_rejected(api):
    """PRD §3.8: "if the skip brings consecutive_skip_count to 3, the subscription auto-pauses
    (ACTIVE → PAUSED)."
    PRD §3.8: "A skip attempted on a non-ACTIVE subscription, or once three consecutive skips
    have already accumulated, is rejected with ERR_INVALID_STATE."

    Design: Difficulty/boundary_precision_check/boundary_skip_limit_third_skip_zero_remaining
    """
    customer, sub_after_two = setup_subscription_with_skips(num_skips=2)
    cid = customer["id"]
    third = validate_success(api.skip_subscription(sub_after_two["id"], make_customer_headers(cid)), 200)
    assert third["consecutive_skip_count"] == 3
    assert third["status"] == "PAUSED", "3rd skip auto-pauses"

    res = api.skip_subscription(sub_after_two["id"], make_customer_headers(cid))
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


def test_skip_increments_count_below_limit(api):
    """PRD §3.8: "A skip increments consecutive_skip_count by one, advances next_renewal_iso
    by cadence_days, increments the customer's lifetime_skip_count by one"

    Design: Difficulty/boundary_precision_check/boundary_skip_limit_third_skip_zero_remaining
    """
    customer, sku, lot, sub = setup_customer_with_active_subscription(tier="STARTER", cadence_days=14)
    cid = customer["id"]
    first = validate_success(api.skip_subscription(sub["id"], make_customer_headers(cid)), 200)
    assert first["consecutive_skip_count"] == 1
    assert first["status"] == "ACTIVE"


# ───────────────────────── renewal temporal lower bound ─────────────────────────

def test_renew_before_next_renewal_iso_rejected(api):
    """PRD §3.8: "Renewal is the cyclic heart of the machine and is fired (by a PlatformAdmin
    or the owning Customer) only when the clock has reached or passed next_renewal_iso; a
    premature renewal is rejected with ERR_NOT_DUE."

    Design: Difficulty/resource_temporal_overlap/temporal_renewal_not_due_before_next_renewal
    """
    # 28-day cadence created at clock default 2026-03-01 -> next_renewal 2026-03-29; clock not advanced.
    customer, sku, lot, sub = setup_customer_with_active_subscription(tier="STARTER", cadence_days=28)
    res = api.renew_subscription(sub["id"], ADMIN)
    validate_error(res, ApiErrorId.ERR_NOT_DUE.value)


def test_renew_not_due_returns_409(api):
    """PRD §2.5: "On startup the clock reads exactly 2026-03-01T00:00:00Z, and until it is
    explicitly set it stays at that default and never falls back to wall-clock time."
    PRD §3.8: "a premature renewal is rejected with ERR_NOT_DUE."

    Design: Difficulty/resource_temporal_overlap/temporal_renewal_not_due_before_next_renewal
    """
    customer, sku, lot, sub = setup_customer_with_active_subscription(tier="CLASSIC", cadence_days=56)
    res = api.renew_subscription(sub["id"], make_customer_headers(customer["id"]))
    validate_error(res, ApiErrorId.ERR_NOT_DUE.value, expected_status=409)
