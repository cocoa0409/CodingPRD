"""Settlement creation and the volume-tier merchant-discount fee.

Queue A (Difficulty) — combinatorial_formula / settlement_fee_circular_volume_tier_evaluation_order.
Queue B (Corner)     — calculations (tier2 boundary), endpoints (settle subresource
                       listing, pay updates net/volume), state_machines (idempotent settle).
"""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    TEST_USERS,
    make_provider_headers,
    set_clock,
    create_authorized_purchase,
    create_enrolled_provider,
    create_active_plan,
    create_provider_promotion,
    create_active_account,
    authorize_purchase,
)

ADMIN = TEST_USERS["admin_headers"]


def _settle(api, purchase):
    fp = validate_success(api.get_financed_purchase(purchase["id"], ADMIN), 200)
    return validate_success(api.settle_financed_purchase(
        fp["id"], {"expected_financed_purchase_version": fp["version"]}, ADMIN), 201)


# ──────────────── Queue A: combinatorial_formula ────────────────
def test_settlement_fee_tier1_after_prior_paid_volume(api):
    """PRD §3.5: "First, a prospective monthly volume is formed by adding this
    settlement's `gross_cents` to the provider's current `monthly_settled_volume_cents`.
    Second, a tier delta is selected from that prospective volume: if the prospective
    volume is at least 5,000,000 cents the delta is 0.02".
    PRD §3.5: "the `discount_rate_applied` is the provider's `base_merchant_discount_rate`
    minus that delta, but never lower than the floor rate of 0.02".

    base 0.085, prior paid volume 4,500,000 + gross 800,000 = prospective 5,300,000 ≥
    TIER1 → rate 0.065, fee 52,000, net 748,000.

    Design: Difficulty/combinatorial_formula/settlement_fee_circular_volume_tier_evaluation_order
    """
    set_clock("2026-03-01T00:00:00Z")
    provider = create_enrolled_provider(base_merchant_discount_rate=0.085, specialty="VISION")
    plan = create_active_plan(promo_apr=0.25, min_payment_factor=0.04)
    promotion = create_provider_promotion(provider["id"], plan["id"])
    # The per-account line is capped at 2,500,000 (PRD §3.2 absolute cap), so the
    # provider's prior paid monthly volume of 4,500,000 is built across two
    # accounts (2,500,000 + 2,000,000), each settled AND paid.
    account_a = create_active_account(income_cents=30_000_000, requested_limit_cents=2_500_000)
    account_b = create_active_account(income_cents=30_000_000, requested_limit_cents=2_000_000)
    account_c = create_active_account(income_cents=30_000_000, requested_limit_cents=2_500_000)

    pa = authorize_purchase(provider, account_a, promotion, 2_500_000)
    sa = _settle(api, pa)
    validate_success(api.pay_settlement(sa["id"], ADMIN), 200)
    pb = authorize_purchase(provider, account_b, promotion, 2_000_000)
    sb = _settle(api, pb)
    validate_success(api.pay_settlement(sb["id"], ADMIN), 200)

    # Next purchase 800,000 on a fresh account: settle → prospective
    # 4,500,000 + 800,000 = 5,300,000 crosses TIER1.
    p2 = authorize_purchase(provider, account_c, promotion, 800_000)
    s2 = _settle(api, p2)
    assert s2["discount_rate_applied"] == pytest.approx(0.065, abs=1e-9)
    assert s2["discount_fee_cents"] == 52_000
    assert s2["net_cents"] == 748_000


def test_settlement_fee_volume_baseline_excludes_unpaid_settlement(api):
    """PRD §3.5: "Crucially, the provider's `monthly_settled_volume_cents` is not mutated
    here at settlement creation — it changes only when a settlement is later paid — so two
    settlements created back to back before either is paid both see the same monthly-volume
    baseline."
    PRD §3.5: "if the prospective volume is at least 5,000,000 cents the delta is 0.02;
    otherwise if it is at least 1,000,000 cents the delta is 0.01; otherwise the delta is
    zero."

    A fresh provider's first settlement of gross 2,000,000 sees baseline 0 (no paid
    settlement yet): prospective 2,000,000 is in TIER2 (≥1,000,000, <5,000,000) → delta
    0.01, rate 0.075, not TIER1. (Per-account principal is capped at 2,500,000 by the
    PRD §3.2 absolute cap, so the gross stays at or below that cap.)

    Design: Difficulty/combinatorial_formula/settlement_fee_circular_volume_tier_evaluation_order
    """
    set_clock("2026-03-01T00:00:00Z")
    provider = create_enrolled_provider(base_merchant_discount_rate=0.085, specialty="VISION")
    plan = create_active_plan(promo_apr=0.25, min_payment_factor=0.04)
    promotion = create_provider_promotion(provider["id"], plan["id"])
    account = create_active_account(income_cents=30_000_000, requested_limit_cents=2_500_000)

    p1 = authorize_purchase(provider, account, promotion, 2_000_000)
    s1 = _settle(api, p1)  # not paid yet, so baseline stays 0
    assert s1["discount_rate_applied"] == pytest.approx(0.075, abs=1e-9)
    # 2,000,000 * 0.075 = 150,000
    assert s1["discount_fee_cents"] == 150_000
    assert s1["net_cents"] == 1_850_000


# ──────────────── Queue B: calculations / endpoints ────────────────
def test_settlement_fee_tier2_boundary_rate(api):
    """PRD §3.5: "otherwise if it is at least 1,000,000 cents the delta is 0.01;
    otherwise the delta is zero. Third, the `discount_rate_applied` is the provider's
    `base_merchant_discount_rate` minus that delta ... Fourth, the `discount_fee_cents`
    is the gross times the applied rate, rounded half up to whole cents. Fifth, the
    `net_cents` paid to the provider is the gross minus that fee."

    Fresh provider base 0.085, gross 1,200,000 ≥ TIER2 (1,000,000) → delta 0.01, rate
    0.075, fee 90,000, net 1,110,000.

    Design: Corner/calculations/settlement_fee_tier2_boundary_rate
    """
    provider, plan, promotion, account, purchase = create_authorized_purchase(
        principal_cents=1_200_000, base_merchant_discount_rate=0.085,
        income_cents=30_000_000, requested_limit_cents=2_000_000, specialty="VISION")
    settlement = _settle(api, purchase)
    assert settlement["discount_rate_applied"] == pytest.approx(0.075, abs=1e-9)
    assert settlement["discount_fee_cents"] == 90_000
    assert settlement["net_cents"] == 1_110_000


def test_settle_creates_settlement_via_subresource_listing(api):
    """PRD §3.5: "Once a purchase has been authorized, a `PlatformAdmin` settles it to its
    provider, creating a `Settlement`."
    PRD §3.5: "The settlement is created with its `financed_purchase_id` set to the
    purchase, its `provider_id` copied from the purchase, and its `gross_cents` equal to
    the purchase's `principal_cents`. ... A freshly created settlement starts in `PENDING`
    status."

    Base 0.10, gross 100,000, prospective 100,000 < TIER2 → delta 0, rate 0.10, fee
    10,000, net 90,000.

    Design: Corner/endpoints/settle_creates_settlement_via_subresource_listing
    """
    provider, plan, promotion, account, purchase = create_authorized_purchase(
        principal_cents=100_000, base_merchant_discount_rate=0.10, specialty="VISION")
    _settle(api, purchase)
    data, meta = validate_paginated(
        api.list_provider_settlements(provider["id"], make_provider_headers(provider["id"])))
    assert meta["total_count"] == 1
    s = data[0]
    assert s["financed_purchase_id"] == purchase["id"]
    assert s["status"] == "PENDING"
    assert s["net_cents"] == 90_000


def test_settle_pay_updates_provider_net_and_volume(api):
    """PRD §3.5: "Paying moves the settlement to `PAID`, increments the provider's
    `settled_net_cents` by the settlement's `net_cents`, increments the provider's
    `monthly_settled_volume_cents` by the settlement's `gross_cents` for the current clock
    month, and bumps the settlement's `version`."

    Base 0.10, gross 100,000, net 90,000.

    Design: Corner/endpoints/settle_pay_updates_provider_net_and_volume
    """
    provider, plan, promotion, account, purchase = create_authorized_purchase(
        principal_cents=100_000, base_merchant_discount_rate=0.10, specialty="GENERAL")
    settlement = _settle(api, purchase)
    paid = validate_success(api.pay_settlement(settlement["id"], ADMIN), 200)
    assert paid["status"] == "PAID"
    prov = validate_success(api.get_provider(provider["id"], ADMIN), 200)
    assert prov["settled_net_cents"] == 90_000
    assert prov["monthly_settled_volume_cents"] == 100_000


def test_settle_purchase_already_settled_returns_invalid_state(api):
    """PRD §3.5: "Settling is permitted only from `AUTHORIZED`".
    PRD §2.8: "(6) the target's state admitting the requested transition
    (`ERR_INVALID_STATE`)".

    Design: Corner/state_machines/settle_purchase_already_settled_returns_invalid_state
    """
    provider, plan, promotion, account, purchase = create_authorized_purchase(
        principal_cents=100_000)
    _settle(api, purchase)
    fp = validate_success(api.get_financed_purchase(purchase["id"], ADMIN), 200)
    res = api.settle_financed_purchase(
        fp["id"], {"expected_financed_purchase_version": fp["version"]}, ADMIN)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
