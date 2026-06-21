"""Pricing-engine and quote tests.

The quote runs at pay time (PRD §3.2): single most-favorable discount (max, not
stacked), round-half-up per ticket, then add combo, then multiply by party_size.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    make_guest_headers, TEST_USERS,
    create_park_payload, create_pricing_policy_payload, create_guest_payload,
    create_order_payload,
    setup_confirmed_admission,
)

PM = TEST_USERS["park_manager_headers"]
FC = TEST_USERS["finance_clerk_headers"]
GA = TEST_USERS["gate_agent_headers"]


def _park(**ov):
    return get_success_data(api_client.create_park(create_park_payload(**ov), PM))


def _policy(park_id, **ov):
    return get_success_data(api_client.create_pricing_policy(
        create_pricing_policy_payload(park_id, **ov), PM))


def _guest(**ov):
    return get_success_data(api_client.create_guest(create_guest_payload(**ov), TEST_USERS["guest_headers"]))


def _order(park_id, guest_id, **ov):
    return get_success_data(api_client.create_order(
        create_order_payload(park_id, guest_id, **ov), make_guest_headers(guest_id)))


def _pay(order_id, guest_id):
    return get_success_data(api_client.pay_order(order_id, make_guest_headers(guest_id)))


# ───────────────── Queue A: dual_variant_calc ─────────────────

def test_group_variant_vs_standard_variant_subtotal_divergence(api):
    """PRD §3.2: "Group eligibility, recorded as group_rate_applied, is true exactly
    when the order's party_size is at least the active policy's group_threshold."
    PRD §3.2: "a party at or above the threshold carries group_rate_applied true and
    the effective discount becomes the larger of resident and group."

    Design: Difficulty/dual_variant_calc/quote_order_group_vs_standard_variant_divergence
    """
    park = _park(resident_zip_prefixes=[], rain_check_value_cents=4000)
    _policy(park["id"], product_type="DAY_TICKET", base_price_cents=5000,
            resident_discount_pct=0.20, group_threshold=10, group_discount_pct=0.15,
            combo_price_cents=800)
    guest = _guest(zip_code="99999", height_cm=175)
    order_big = _order(park["id"], guest["id"], product_type="DAY_TICKET", party_size=12,
                       food_beverage_combo=False)
    order_small = _order(park["id"], guest["id"], product_type="DAY_TICKET", party_size=4,
                         food_beverage_combo=False)

    big = _pay(order_big["id"], guest["id"])
    small = _pay(order_small["id"], guest["id"])

    # party 12 >= threshold 10 → group variant: round(5000*0.85)=4250 per ticket * 12
    assert big["group_rate_applied"] is True
    assert big["subtotal_cents"] == 51000, f"expected 51000, got {big['subtotal_cents']}"
    # party 4 < threshold → standard variant, no discount eligible (non-resident): 5000 * 4
    assert small["group_rate_applied"] is False
    assert small["subtotal_cents"] == 20000, f"expected 20000, got {small['subtotal_cents']}"


def test_group_variant_party_size_at_threshold_applies_group(api):
    """PRD §3.2: "Group eligibility, recorded as group_rate_applied, is true exactly
    when the order's party_size is at least the active policy's group_threshold."

    Design: Difficulty/dual_variant_calc/quote_order_group_vs_standard_variant_divergence
    """
    park = _park(resident_zip_prefixes=[])
    _policy(park["id"], product_type="DAY_TICKET", base_price_cents=5000,
            resident_discount_pct=0.20, group_threshold=10, group_discount_pct=0.15,
            combo_price_cents=800)
    guest = _guest(zip_code="99999")
    order = _order(park["id"], guest["id"], product_type="DAY_TICKET", party_size=10,
                   food_beverage_combo=False)
    paid = _pay(order["id"], guest["id"])
    # party 10 == threshold 10 → "at least" → group applies: round(5000*0.85)=4250 * 10
    assert paid["group_rate_applied"] is True
    assert paid["subtotal_cents"] == 42500, f"expected 42500, got {paid['subtotal_cents']}"


def test_freeze_days_first_then_subsequent_episode_accumulates(api):
    """PRD §3.5: "on a pass's first freeze the running total equals just that first
    episode's days, and on every later episode the total grows by that episode's days."
    PRD §3.5: "converts that elapsed time to whole days by rounding up so that any
    partial day counts as a full day (86,400 seconds make a day), and adds that
    episode's day count to the running freeze_days_used."

    Design: Difficulty/dual_variant_calc/freeze_days_first_vs_subsequent_episode_divergence
    """
    ctx = setup_confirmed_admission(
        product_type="SEASON_PASS",
        clock="2026-06-01T00:00:00Z",
        policy_overrides={"base_price_cents": 30000},
        window_overrides={"starts_at": "2026-06-01T09:00:00Z",
                          "ends_at": "2026-12-31T23:00:00Z", "window_capacity": 50},
    )
    adm_id = ctx["admission"]["id"]
    gh = make_guest_headers(ctx["guest"]["id"])

    # First episode: frozen at 2026-06-01T00:00:00Z, unfrozen at 2026-06-03T12:00:00Z
    # = 2.5 days → ceil = 3.
    get_success_data(api_client.freeze_admission(adm_id, gh))
    get_success_data(api_client.set_clock({"to_iso8601": "2026-06-03T12:00:00Z"}, PM))
    after_first = get_success_data(api_client.unfreeze_admission(adm_id, gh))
    assert after_first["freeze_days_used"] == 3, \
        f"first episode: expected 3, got {after_first['freeze_days_used']}"

    # Second episode: frozen at 2026-06-03T12:00:00Z, unfrozen at 2026-06-04T01:00:00Z
    # = 13h → ceil = 1 day → running total 3 + 1 = 4.
    get_success_data(api_client.freeze_admission(adm_id, gh))
    get_success_data(api_client.set_clock({"to_iso8601": "2026-06-04T01:00:00Z"}, PM))
    after_second = get_success_data(api_client.unfreeze_admission(adm_id, gh))
    assert after_second["freeze_days_used"] == 4, \
        f"second episode accumulates: expected 4, got {after_second['freeze_days_used']}"


def test_freeze_days_first_episode_partial_day_counts_full(api):
    """PRD §3.5: "converts that elapsed time to whole days by rounding up so that any
    partial day counts as a full day (86,400 seconds make a day), and adds that
    episode's day count to the running freeze_days_used."
    PRD §3.5: "on a pass's first freeze the running total equals just that first
    episode's days"

    Design: Difficulty/dual_variant_calc/freeze_days_first_vs_subsequent_episode_divergence
    """
    ctx = setup_confirmed_admission(
        product_type="SEASON_PASS",
        clock="2026-06-01T00:00:00Z",
        policy_overrides={"base_price_cents": 30000},
        window_overrides={"starts_at": "2026-06-01T09:00:00Z",
                          "ends_at": "2026-12-31T23:00:00Z", "window_capacity": 50},
    )
    adm_id = ctx["admission"]["id"]
    gh = make_guest_headers(ctx["guest"]["id"])
    get_success_data(api_client.freeze_admission(adm_id, gh))
    # Unfreeze 1 hour later: 1h elapsed → ceil = 1 full day, first episode total = 1.
    get_success_data(api_client.set_clock({"to_iso8601": "2026-06-01T01:00:00Z"}, PM))
    after = get_success_data(api_client.unfreeze_admission(adm_id, gh))
    assert after["freeze_days_used"] == 1, \
        f"first episode partial day → 1, got {after['freeze_days_used']}"


# ───────────────── Queue A: combinatorial_formula ─────────────────

def test_max_discount_not_stacked_resident_and_group_both_eligible(api):
    """PRD §3.2: "uses the single larger of those two percentages as the effective
    discount — the maximum of the two, never their product or their sum."
    PRD §3.2: "The combo surcharge — the policy's combo_price_cents when the order's
    food_beverage_combo flag is set, otherwise zero — is added to the rounded
    discounted base to give the per-ticket price"

    Design: Difficulty/combinatorial_formula/quote_order_max_discount_not_stacked_mode_a
    """
    park = _park(resident_zip_prefixes=["900"])
    _policy(park["id"], product_type="DAY_TICKET", base_price_cents=5000,
            resident_discount_pct=0.20, group_threshold=10, group_discount_pct=0.15,
            combo_price_cents=800)
    guest = _guest(zip_code="90011", height_cm=180)
    order = _order(park["id"], guest["id"], product_type="DAY_TICKET", party_size=12,
                   food_beverage_combo=True)
    paid = _pay(order["id"], guest["id"])

    assert paid["resident_rate_applied"] is True
    assert paid["group_rate_applied"] is True
    # max(0.20, 0.15)=0.20: round(5000*0.80)=4000 +800 combo =4800 per ticket *12 =57600
    # (stacked would give 3400+800=4200 *12 = 50400 — must NOT happen)
    assert paid["subtotal_cents"] == 57600, f"expected 57600 (max discount), got {paid['subtotal_cents']}"


def test_max_discount_picks_group_when_group_pct_larger(api):
    """PRD §3.2: "uses the single larger of those two percentages as the effective
    discount — the maximum of the two, never their product or their sum."

    Design: Difficulty/combinatorial_formula/quote_order_max_discount_not_stacked_mode_a
    """
    park = _park(resident_zip_prefixes=["900"])
    _policy(park["id"], product_type="DAY_TICKET", base_price_cents=5000,
            resident_discount_pct=0.10, group_threshold=10, group_discount_pct=0.25,
            combo_price_cents=0)
    guest = _guest(zip_code="90011")
    order = _order(park["id"], guest["id"], product_type="DAY_TICKET", party_size=12,
                   food_beverage_combo=False)
    paid = _pay(order["id"], guest["id"])
    assert paid["resident_rate_applied"] is True
    assert paid["group_rate_applied"] is True
    # max(0.10, 0.25)=0.25: round(5000*0.75)=3750 per ticket * 12 = 45000
    assert paid["subtotal_cents"] == 45000, f"expected 45000, got {paid['subtotal_cents']}"


def test_round_per_ticket_first_then_multiply(api):
    """PRD §3.2: "rounds that discounted base to a whole number of cents using
    round-half-up at this per-ticket step."
    PRD §3.2: "The decisive rule, repeated for emphasis, is round-half-up per
    ticket first, then add the combo, then multiply by the party size."

    Design: Difficulty/combinatorial_formula/quote_order_round_then_multiply_mode_b
    """
    park = _park(resident_zip_prefixes=[])
    _policy(park["id"], product_type="DAY_TICKET", base_price_cents=3333,
            resident_discount_pct=0.15, group_threshold=99, group_discount_pct=0.10,
            combo_price_cents=0)
    guest = _guest(zip_code="55555", height_cm=170)
    # resident NOT eligible (zip 55555 not under any prefix) so no discount applies.
    # round(3333 * 1.0) = 3333 per ticket * 12 = 39996. But the design pins the
    # resident-eligible variant; replicate it exactly:
    order = _order(park["id"], guest["id"], product_type="DAY_TICKET", party_size=12,
                   food_beverage_combo=False)
    paid = _pay(order["id"], guest["id"])
    # No discount eligible: per-ticket 3333 * 12 = 39996.
    assert paid["subtotal_cents"] == 39996, f"expected 39996, got {paid['subtotal_cents']}"


def test_round_per_ticket_first_then_multiply_resident_eligible(api):
    """PRD §3.2: "The decisive rule, repeated for emphasis, is round-half-up per
    ticket first, then add the combo, then multiply by the party size."

    Design: Difficulty/combinatorial_formula/quote_order_round_then_multiply_mode_b
    """
    park = _park(resident_zip_prefixes=["555"])
    _policy(park["id"], product_type="DAY_TICKET", base_price_cents=3333,
            resident_discount_pct=0.15, group_threshold=99, group_discount_pct=0.10,
            combo_price_cents=0)
    guest = _guest(zip_code="55555", height_cm=170)
    order = _order(park["id"], guest["id"], product_type="DAY_TICKET", party_size=12,
                   food_beverage_combo=False)
    paid = _pay(order["id"], guest["id"])
    assert paid["resident_rate_applied"] is True
    # round_half_up(3333 * 0.85) = round(2833.05) = 2833 per ticket * 12 = 33996.
    # multiply-then-round would give round(3333*0.85*12)=round(33996.6)=33997.
    assert paid["subtotal_cents"] == 33996, \
        f"expected 33996 (round-then-multiply), got {paid['subtotal_cents']}"


# ───────────────── Queue B: calculations ─────────────────

def test_resident_pricing_applied_on_zip_prefix_match(api):
    """PRD §3.2: "Resident eligibility, recorded as resident_rate_applied, is true
    exactly when the purchasing guest's zip_code begins with at least one of the
    park's resident_zip_prefixes entries."

    Design: Corner/calculations/resident_pricing_applied_when_zip_prefix_matches
    """
    park = _park(resident_zip_prefixes=["90"])
    _policy(park["id"], product_type="DAY_TICKET", base_price_cents=5000,
            resident_discount_pct=0.20)
    guest = _guest(zip_code="90210", height_cm=160)
    order = _order(park["id"], guest["id"], product_type="DAY_TICKET", party_size=1)
    paid = _pay(order["id"], guest["id"])
    assert paid["resident_rate_applied"] is True
    # round(5000 * 0.80) = 4000 per ticket * 1
    assert paid["subtotal_cents"] == 4000, f"expected 4000, got {paid['subtotal_cents']}"


def test_wallet_credit_caps_at_subtotal_on_pay(api):
    """PRD §3.2: "The amount of credit consumed, wallet_credit_used_cents, is the
    smaller of the guest's available wallet_credit_cents and the subtotal_cents, so
    it never exceeds either the balance or the bill. The final total_cents is the
    subtotal minus the credit consumed."

    Design: Corner/calculations/wallet_credit_caps_at_subtotal_on_pay
    """
    # Seed wallet to 3000 via a settled rain-check, then pay a 5000 subtotal order.
    park = _park(rain_check_value_cents=3000)
    get_success_data(api_client.set_clock({"to_iso8601": "2026-07-01T10:00:00Z"}, PM))
    _policy(park["id"], product_type="DAY_TICKET", base_price_cents=5000)
    window = get_success_data(api_client.create_entry_window(
        park["id"], {"starts_at": "2026-07-01T09:00:00Z", "ends_at": "2026-07-01T17:00:00Z",
                     "window_capacity": 50}, PM))
    guest = _guest()
    gh = make_guest_headers(guest["id"])
    seed = _order(park["id"], guest["id"], product_type="DAY_TICKET", party_size=1)
    get_success_data(api_client.pay_order(seed["id"], gh))
    get_success_data(api_client.fulfill_order(seed["id"], gh))
    adm = get_success_data(api_client.list_order_admissions(seed["id"], gh))[0]
    get_success_data(api_client.bind_guest(adm["id"], {"guest_id": guest["id"]}, gh))
    fresh = get_success_data(api_client.get_entry_window(window["id"], PM))
    get_success_data(api_client.assign_window(
        adm["id"], {"entry_window_id": window["id"],
                    "expected_entry_window_version": fresh["version"]}, gh))
    get_success_data(api_client.set_park_weather(park["id"], {"weather_status": "RAINED_OUT"}, PM))
    get_success_data(api_client.rain_out_entry_window(window["id"], PM))
    rc = get_success_data(api_client.list_rain_checks(FC, params={"park_id": park["id"]}))[0]
    get_success_data(api_client.settle_rain_check(rc["id"], FC))

    # Now wallet has 3000. New order subtotal 5000.
    order = _order(park["id"], guest["id"], product_type="DAY_TICKET", party_size=1)
    paid = _pay(order["id"], guest["id"])
    assert paid["wallet_credit_used_cents"] == 3000, \
        f"expected 3000 used, got {paid['wallet_credit_used_cents']}"
    assert paid["total_cents"] == 2000, f"expected total 2000, got {paid['total_cents']}"
    guest_after = get_success_data(api_client.get_guest(guest["id"], gh))
    assert guest_after["wallet_credit_cents"] == 0, \
        f"wallet should drain to 0, got {guest_after['wallet_credit_cents']}"


def test_pay_with_no_active_policy_rejected(api):
    """PRD §3.2: "The engine first selects the single active PricingPolicy for the
    order's park_id and product_type; if no such active policy exists the payment is
    rejected with ERR_NO_ACTIVE_POLICY."

    Design: Corner/calculations/pay_with_no_active_policy_returns_error
    """
    park = _park()
    guest = _guest()
    order = _order(park["id"], guest["id"], product_type="DAY_TICKET", party_size=1)
    res = api_client.pay_order(order["id"], make_guest_headers(guest["id"]))
    validate_error(res, "ERR_NO_ACTIVE_POLICY")


def test_band_green_floor_boundary_at_122cm(api):
    """PRD §3.4: "a height of at least 122 centimeters earns GREEN (all attractions)"
    PRD §3.4: "the comparison is exact integer-against-floor, so a height equal to a
    floor takes the higher band."

    Design: Corner/calculations/band_green_floor_boundary_122cm
    """
    ctx = setup_confirmed_admission(clock="2026-07-01T10:00:00Z",
                                    guest_overrides={"height_cm": 122})
    checked = get_success_data(api_client.check_in_admission(ctx["admission"]["id"], GA))
    assert checked["band_color"] == "GREEN", \
        f"height 122 == GREEN_MIN_CM should be GREEN, got {checked['band_color']}"


def test_immediate_subtotal_total_in_pay_response(api):
    """PRD §3.2: "The per-ticket price is then multiplied by party_size to give
    subtotal_cents."
    PRD §3.3: "Paying runs the quote of §3.2, writing subtotal_cents, total_cents,
    wallet_credit_used_cents, resident_rate_applied, and group_rate_applied onto the
    order"

    Design: Corner/consistency_model/immediate_visibility_of_subtotal_in_pay_response
    """
    park = _park()
    _policy(park["id"], product_type="DAY_TICKET", base_price_cents=5000, group_threshold=99)
    guest = _guest()
    order = _order(park["id"], guest["id"], product_type="DAY_TICKET", party_size=2)
    paid = _pay(order["id"], guest["id"])
    # base 5000, no discount, party 2 → subtotal 10000, no wallet → total 10000.
    assert paid["subtotal_cents"] == 10000, f"expected 10000, got {paid['subtotal_cents']}"
    assert paid["total_cents"] == 10000, f"expected 10000, got {paid['total_cents']}"
