"""Tiered package pricing and dual-variant credit valuation.

Covers the combinatorial pricing formula (§3.12) and the per-credit vs blended cash-value
report (§3.13), plus the corner-design pricing/computed-field claims.
"""
import pytest

from test_helpers import (
    api_client, validate_success, get_success_data,
    create_owner_payload, create_package_payload,
    TEST_USERS, make_owner_headers,
    setup_enroll_ready_group, enroll, create_package, create_owner, set_clock,
    assert_package,
)


def _make_owner():
    res = api_client.create_owner(create_owner_payload(email="pricing-owner@example.com"),
                                  TEST_USERS["front_desk_headers"])
    return get_success_data(res)


def test_value_tier_bulk_discount_and_bonus_credit(api):
    """PRD §3.12: "Next, a bulk discount applies only when the base credit count is at
    least 8: in that case 10 percent is taken off the base price, otherwise no discount
    applies." PRD §3.12: "Concretely: `STARTER` yields 20000 cents and 4 credits; `VALUE`
    yields 32400 cents and 9 credits; `PRO` yields 57600 cents and 17 credits."

    Design: Difficulty/combinatorial_formula/tiered_package_pricing_bulk_discount_and_bonus_credit
    """
    owner = _make_owner()
    res = api.create_package(create_package_payload(owner["id"], "VALUE"),
                             make_owner_headers(owner["id"]))
    pkg = validate_success(res, 201)
    assert pkg["credits_total"] == 9, "VALUE: 8 base + 1 bonus credit (base >= 8)"
    assert pkg["price_paid_cents"] == 32400, "VALUE: round_half_up(36000 * 0.90)"


def test_value_tier_credits_total_includes_bonus(api):
    """PRD §3.12: "Finally, the package's `credits_total` is the base credit count plus a
    bonus of 1 credit when (and only when) the base credit count is at least 8, otherwise
    just the base credit count." PRD §3.12: "Concretely: `STARTER` yields 20000 cents and 4
    credits; `VALUE` yields 32400 cents and 9 credits; `PRO` yields 57600 cents and 17
    credits."

    Design: Difficulty/combinatorial_formula/tiered_package_pricing_bulk_discount_and_bonus_credit
    """
    owner = _make_owner()
    res = api.create_package(create_package_payload(owner["id"], "VALUE"),
                             make_owner_headers(owner["id"]))
    pkg = validate_success(res, 201)
    # 8 base credits crosses BULK_THRESHOLD so the +1 bonus fires: 8 + 1 = 9.
    assert pkg["credits_total"] == 9
    assert pkg["credits_remaining"] == 9, "no credits consumed at purchase"
    assert pkg["credits_consumed"] == 0


def test_pro_tier_valuation_per_credit_vs_blended_divergence(api):
    """PRD §3.13: "The per-credit valuation, `per_credit_valuation_cents`, values each
    remaining credit independently: it rounds the per-credit value half up to a whole cent
    first and then multiplies by `credits_remaining`." PRD §3.13: "The blended valuation,
    `blended_valuation_cents`, pools the credits: it multiplies `price_paid_cents` by
    `credits_remaining`, divides by `credits_total`, and rounds the single result half up to
    a whole cent."

    Design: Difficulty/combinatorial_formula/package_valuation_round_per_credit_then_sum_vs_sum_then_round
    """
    bundle = setup_enroll_ready_group(session_count=1, list_price_cents=8000, credit_cost=7)
    owner = bundle["owner"]
    pkg = create_package(owner, tier="PRO")  # credits_total=17, price_paid_cents=57600
    # Consume 7 credits via a PACKAGE enrollment, leaving 10 remaining.
    enroll(owner, bundle["dog"], bundle["series"], payment_method="PACKAGE",
           package_id=pkg["id"], series_version=bundle["series"]["version"])

    res = api.get_package_valuation(pkg["id"], make_owner_headers(owner["id"]))
    val = validate_success(res, 200)
    assert val["per_credit_valuation_cents"] == 33880, "round(57600/17)=3388, *10"
    assert val["blended_valuation_cents"] == 33882, "round(57600*10/17)"
    assert val["blended_valuation_cents"] - val["per_credit_valuation_cents"] == 2


def test_pro_tier_valuation_per_credit_rounds_each_credit_first(api):
    """PRD §3.13: "The per-credit valuation, `per_credit_valuation_cents`, values each
    remaining credit independently: it rounds the per-credit value half up to a whole cent
    first and then multiplies by `credits_remaining`."

    Design: Difficulty/combinatorial_formula/package_valuation_round_per_credit_then_sum_vs_sum_then_round
    """
    bundle = setup_enroll_ready_group(session_count=1, list_price_cents=8000, credit_cost=7)
    owner = bundle["owner"]
    pkg = create_package(owner, tier="PRO")  # 57600c / 17 credits
    enroll(owner, bundle["dog"], bundle["series"], payment_method="PACKAGE",
           package_id=pkg["id"], series_version=bundle["series"]["version"])

    res = api.get_package_valuation(pkg["id"], make_owner_headers(owner["id"]))
    val = validate_success(res, 200)
    # round_half_up(57600/17) = 3388 per credit; 3388 * 10 remaining = 33880.
    assert val["per_credit_valuation_cents"] == 33880


def test_pro_tier_valuation_credits_remaining_reported(api):
    """PRD §3.13: "The report returns the package's id as `package_id`, the package's
    `credits_remaining`, and two valuations."

    Design: Difficulty/dual_variant_calc/package_credit_valuation_per_credit_vs_blended_on_package
    """
    bundle = setup_enroll_ready_group(session_count=1, list_price_cents=8000, credit_cost=7)
    owner = bundle["owner"]
    pkg = create_package(owner, tier="PRO")
    enroll(owner, bundle["dog"], bundle["series"], payment_method="PACKAGE",
           package_id=pkg["id"], series_version=bundle["series"]["version"])

    res = api.get_package_valuation(pkg["id"], make_owner_headers(owner["id"]))
    val = validate_success(res, 200)
    assert val["credits_remaining"] == 10, "17 total - 7 debited"
    assert val["per_credit_valuation_cents"] == 33880
    assert val["blended_valuation_cents"] == 33882


def test_pro_tier_valuation_blended_value(api):
    """PRD §3.13: "The blended valuation, `blended_valuation_cents`, pools the credits: it
    multiplies `price_paid_cents` by `credits_remaining`, divides by `credits_total`, and
    rounds the single result half up to a whole cent."

    Design: Difficulty/dual_variant_calc/package_credit_valuation_per_credit_vs_blended_on_package
    """
    bundle = setup_enroll_ready_group(session_count=1, list_price_cents=8000, credit_cost=7)
    owner = bundle["owner"]
    pkg = create_package(owner, tier="PRO")
    enroll(owner, bundle["dog"], bundle["series"], payment_method="PACKAGE",
           package_id=pkg["id"], series_version=bundle["series"]["version"])

    res = api.get_package_valuation(pkg["id"], make_owner_headers(owner["id"]))
    val = validate_success(res, 200)
    assert val["blended_valuation_cents"] == 33882, "round_half_up(57600 * 10 / 17)"


# ─── Corner: calculations section ───────────────────────────────────────────────
def test_starter_package_no_discount_no_bonus(api):
    """PRD §3.12: "Concretely: `STARTER` yields 20000 cents and 4 credits; `VALUE` yields
    32400 cents and 9 credits; `PRO` yields 57600 cents and 17 credits."

    Design: Corner/calculations/starter_package_pricing_no_discount
    """
    owner = _make_owner()
    res = api.create_package(create_package_payload(owner["id"], "STARTER"),
                             make_owner_headers(owner["id"]))
    pkg = validate_success(res, 201)
    assert pkg["credits_total"] == 4
    assert pkg["price_paid_cents"] == 20000
    assert_package(pkg)


def test_pro_package_discount_and_bonus(api):
    """PRD §3.12: "Concretely: `STARTER` yields 20000 cents and 4 credits; `VALUE` yields
    32400 cents and 9 credits; `PRO` yields 57600 cents and 17 credits."

    Design: Corner/calculations/pro_package_pricing_with_discount_and_bonus
    """
    owner = _make_owner()
    res = api.create_package(create_package_payload(owner["id"], "PRO"),
                             make_owner_headers(owner["id"]))
    pkg = validate_success(res, 201)
    assert pkg["credits_total"] == 17
    assert pkg["price_paid_cents"] == 57600
