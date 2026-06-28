"""Reward-amount and cash-out fee/payout calculations.

Translates difficulty `dual_variant_calc` (reward-rate divergence) and
`combinatorial_formula` (mode-a rate selection, mode-c fee tier) instances, plus
corner `calculations` instances (in-store cap, streak bonus, fees, clawback,
base-rate-only).
"""
from test_helpers import (
    validate_success, api_client, TEST_USERS, make_member_headers,
    create_merchant, create_offer, create_member, create_verified_member,
    create_online_click_and_claim, create_in_store_approved_claim,
    create_cashout_reserving, set_clock,
    member_version, get_member,
)

_PA = TEST_USERS["platform_admin_headers"]
_RA = TEST_USERS["review_agent_headers"]
_FA = TEST_USERS["finance_admin_headers"]


def test_online_reward_diverges_from_in_store_reward(api):
    """PRD §3.3: "If an offer is present, it is a `LINKED` offer, and
    `purchase_amount_cents` is at least the offer's `min_spend_cents`, then the
    effective rate is the base plus the offer's `bonus_rate_bps`".
    PRD §3.4: "The in-store variant uses the in-store rate plus the flat rebate; it
    ignores any linked `bonus_rate_bps`."

    The same purchase on the same merchant yields a different reward under the
    online linked-rate variant versus the in-store rebate variant.

    Design: Difficulty/dual_variant_calc/reward_rate_online_vs_in_store_diverge
    """
    merchant = create_merchant(online_rate_bps=500, instore_rate_bps=200,
                               double_dip_allowed=True, attribution_window_hours=168,
                               maturity_hold_days=30)
    linked = create_offer(merchant["id"], "LINKED", bonus_rate_bps=300, min_spend_cents=5000)
    rebate = create_offer(merchant["id"], "RECEIPT_REBATE", rebate_cents=300, min_spend_cents=2000)
    member = create_member("mb@x.com")
    _, online_claim = create_online_click_and_claim(
        member["id"], merchant["id"], 10000, offer_id=linked["id"])
    _, instore_claim = create_in_store_approved_claim(
        member["id"], merchant["id"], rebate["id"], 10000)
    # Online: rate = min(500+300, 5000) = 800 -> floor(10000*800/10000) = 800.
    assert online_claim["amount_cents"] == 800, \
        f"online linked-rate reward must be 800, got {online_claim['amount_cents']}"
    assert online_claim["amount_cents"] != instore_claim["amount_cents"], \
        "online and in-store rewards must diverge for the same purchase"


def test_in_store_variant_uses_instore_rate_plus_rebate(api):
    """PRD §3.4: "Compute the percentage component as `purchase_amount_cents`
    multiplied by the merchant's `instore_rate_bps`, divided by 10,000, floored to
    whole cents. Then determine the flat component: if the offer's `offer_type` is
    `RECEIPT_REBATE` and `purchase_amount_cents` is at least the offer's
    `min_spend_cents`, the flat component is the offer's `rebate_cents` ... The
    reward `amount_cents` is the sum of the flat component and the floored
    percentage component".

    The in-store variant is the receipt-attributed half of the dual-variant rule;
    here floor(8000*200/10000)=160 plus rebate 300 = 460, distinct from any online
    linked-rate figure on the same merchant.

    Design: Difficulty/dual_variant_calc/reward_rate_online_vs_in_store_diverge
    """
    merchant = create_merchant(online_rate_bps=500, instore_rate_bps=200,
                               double_dip_allowed=True, maturity_hold_days=30)
    rebate = create_offer(merchant["id"], "RECEIPT_REBATE", rebate_cents=300, min_spend_cents=2000)
    member = create_member("mbiv@x.com")
    _, instore_claim = create_in_store_approved_claim(
        member["id"], merchant["id"], rebate["id"], 8000)
    assert instore_claim["attribution"] == "IN_STORE"
    assert instore_claim["amount_cents"] == 460, \
        f"in-store rebate variant must be 460, got {instore_claim['amount_cents']}"


def test_online_linked_rate_below_cap_stacks_bonus(api):
    """PRD §3.3: "If an offer is present, it is a `LINKED` offer, and
    `purchase_amount_cents` is at least the offer's `min_spend_cents`, then the
    effective rate is the base plus the offer's `bonus_rate_bps`".

    Below the 5,000bps ceiling the bonus stacks in full: 1000 + 300 = 1300bps ->
    floor(10000*1300/10000) = 1300, the un-capped companion to the capped case.

    Design: Difficulty/combinatorial_formula/reward_amount_mode_a_three_input_rate_selection
    """
    merchant = create_merchant(online_rate_bps=1000, instore_rate_bps=200, maturity_hold_days=30)
    linked = create_offer(merchant["id"], "LINKED", bonus_rate_bps=300, min_spend_cents=0)
    member = create_member("mcstack@x.com")
    _, claim = create_online_click_and_claim(
        member["id"], merchant["id"], 10000, offer_id=linked["id"])
    assert claim["amount_cents"] == 1300, \
        f"stacked rate 1300bps must yield 1300, got {claim['amount_cents']}"


def test_cashout_fee_gross_tier_applies_to_gift_card(api):
    """PRD §3.6: "For `PAYPAL` and `GIFT_CARD` a percentage tier also applies - if
    `requested_amount_cents` is at least the large-cash-out threshold of 5,000
    cents ($50.00) the percentage rate is 0 (large cash-outs are fee-free),
    otherwise the percentage rate is the small-cash-out rate of 200 basis points
    (2.00%)".

    The gross-keyed small tier (1000 < 5000) charges 2% for gift card just as for
    PayPal: fee = floor(1000*200/10000) = 20.

    Design: Difficulty/combinatorial_formula/cashout_fee_mode_c_circular_tier_pinned_on_gross
    """
    merchant = create_merchant(online_rate_bps=1000, instore_rate_bps=200, maturity_hold_days=30)
    member = create_verified_member("mdgc@x.com")
    create_online_click_and_claim(member["id"], merchant["id"], 10000)
    set_clock("2026-02-15T00:00:00Z")
    cashout = create_cashout_reserving(member["id"], 1000, method="GIFT_CARD")
    assert cashout["fee_cents"] == 20, f"gift-card small-tier fee must be 20, got {cashout['fee_cents']}"
    assert cashout["net_payout_cents"] == 980, \
        f"net payout must be 980, got {cashout['net_payout_cents']}"


def test_online_linked_rate_capped_at_combined_ceiling(api):
    """PRD §3.3: "The effective rate is then capped at no more than the
    combined-rate ceiling of 5,000 basis points (a hard 50.00% cap). Finally,
    `amount_cents` is `purchase_amount_cents` multiplied by the capped rate in
    basis points, divided by 10,000, with the result floored to whole cents."

    Design: Difficulty/combinatorial_formula/reward_amount_mode_a_three_input_rate_selection
    """
    merchant = create_merchant(online_rate_bps=4800, instore_rate_bps=200, maturity_hold_days=30)
    linked = create_offer(merchant["id"], "LINKED", bonus_rate_bps=400, min_spend_cents=0)
    member = create_member("mc@x.com")
    _, claim = create_online_click_and_claim(
        member["id"], merchant["id"], 10000, offer_id=linked["id"])
    # 4800 + 400 = 5200, capped to 5000 -> floor(10000*5000/10000) = 5000.
    assert claim["amount_cents"] == 5000, \
        f"capped-rate reward must be 5000, got {claim['amount_cents']}"


def test_cashout_fee_keyed_on_gross_small_paypal(api):
    """PRD §3.6: "otherwise the percentage rate is the small-cash-out rate of 200
    basis points (2.00%)".
    PRD §3.6: "Step two computes `fee_cents` as the flat portion plus the floor of
    `requested_amount_cents` multiplied by the percentage basis points divided by
    10,000. Step three computes `net_payout_cents` as `requested_amount_cents`
    minus `fee_cents`."

    Design: Difficulty/combinatorial_formula/cashout_fee_mode_c_circular_tier_pinned_on_gross
    """
    merchant = create_merchant(online_rate_bps=1000, instore_rate_bps=200, maturity_hold_days=30)
    member = create_verified_member("md@x.com")
    create_online_click_and_claim(member["id"], merchant["id"], 10000)
    set_clock("2026-02-15T00:00:00Z")
    cashout = create_cashout_reserving(member["id"], 1000, method="PAYPAL")
    # 1000 < 5000 -> 2% -> fee = floor(1000*200/10000) = 20, net = 980.
    assert cashout["fee_cents"] == 20, f"fee must be 20, got {cashout['fee_cents']}"
    assert cashout["net_payout_cents"] == 980, \
        f"net payout must be 980, got {cashout['net_payout_cents']}"


def test_in_store_reward_capped_at_purchase_amount(api):
    """PRD §3.4: "The reward `amount_cents` is the sum of the flat component and the
    floored percentage component, but capped so it never exceeds
    `purchase_amount_cents` - that is, take the smaller of the sum and the purchase
    amount."

    Design: Corner/calculations/instore_amount_capped_at_purchase
    """
    merchant = create_merchant(online_rate_bps=500, instore_rate_bps=200)
    offer = create_offer(merchant["id"], "RECEIPT_REBATE", rebate_cents=500, min_spend_cents=0)
    member = create_member("cap@x.com")
    _, claim = create_in_store_approved_claim(member["id"], merchant["id"], offer["id"], 100)
    # min(500 + floor(100*200/10000)=2, 100) = min(502, 100) = 100.
    assert claim["amount_cents"] == 100, \
        f"in-store reward must cap at purchase 100, got {claim['amount_cents']}"


def test_online_no_offer_uses_base_rate_only(api):
    """PRD §3.3: "Begin with the merchant's `online_rate_bps` as the base. If an
    offer is present, it is a `LINKED` offer, and `purchase_amount_cents` is at
    least the offer's `min_spend_cents`, then the effective rate is the base plus
    the offer's `bonus_rate_bps`; otherwise the effective rate is just the base."

    Design: Corner/calculations/online_no_linked_offer_uses_base_rate_only
    """
    merchant = create_merchant(online_rate_bps=500, instore_rate_bps=200)
    member = create_member("nb@x.com")
    _, claim = create_online_click_and_claim(member["id"], merchant["id"], 10000)
    assert claim["amount_cents"] == 500, \
        f"base-rate-only reward must be 500, got {claim['amount_cents']}"


def test_check_cashout_applies_flat_fee(api):
    """PRD §3.6: "for `CHECK` the flat portion is 200 cents."
    PRD §3.6: "Step two computes `fee_cents` as the flat portion plus the floor of
    `requested_amount_cents` multiplied by the percentage basis points divided by
    10,000."

    Design: Corner/calculations/check_cashout_flat_fee_applied
    """
    merchant = create_merchant(online_rate_bps=3000, instore_rate_bps=200, maturity_hold_days=30)
    member = create_verified_member("chk@x.com")
    create_online_click_and_claim(member["id"], merchant["id"], 10000)
    set_clock("2026-02-15T00:00:00Z")
    cashout = create_cashout_reserving(member["id"], 3000, method="CHECK")
    assert cashout["fee_cents"] == 200, f"CHECK flat fee must be 200, got {cashout['fee_cents']}"
    assert cashout["net_payout_cents"] == 2800, \
        f"net payout must be 2800, got {cashout['net_payout_cents']}"


def test_large_paypal_cashout_is_fee_free(api):
    """PRD §3.6: "if `requested_amount_cents` is at least the large-cash-out
    threshold of 5,000 cents ($50.00) the percentage rate is 0 (large cash-outs
    are fee-free)".

    Design: Corner/calculations/large_paypal_cashout_fee_free_boundary
    """
    merchant = create_merchant(online_rate_bps=5000, instore_rate_bps=200, maturity_hold_days=30)
    member = create_verified_member("lg@x.com")
    create_online_click_and_claim(member["id"], merchant["id"], 10000)
    set_clock("2026-02-15T00:00:00Z")
    cashout = create_cashout_reserving(member["id"], 5000, method="PAYPAL")
    assert cashout["fee_cents"] == 0, f"5000 PayPal must be fee-free, got {cashout['fee_cents']}"
    assert cashout["net_payout_cents"] == 5000, \
        f"net payout must be 5000, got {cashout['net_payout_cents']}"


def test_streak_bonus_three_weeks_per_week_round_then_sum(api):
    """PRD §3.8: "For each week in the current streak, that week's bonus in cents is
    the base of 25 cents multiplied by the quantity (1 plus 0.5 times the week's
    position in the streak minus 1) ... and that per-week figure is rounded half-up
    to whole cents. The `pending_streak_bonus_cents` is the sum of those rounded
    per-week bonuses."
    PRD §3.8: "The `current_streak_weeks` is the count of consecutive week indexes,
    ending at the latest qualifying week, in which the member had at least one
    claim reach `AVAILABLE`."

    Design: Corner/calculations/streak_bonus_three_weeks_per_week_round_then_sum
    """
    merchant = create_merchant(online_rate_bps=1000, instore_rate_bps=200, maturity_hold_days=0)
    member = create_member("stk@x.com")
    hdr = make_member_headers(member["id"])
    # Three consecutive Mon-Sun UTC weeks. maturity_hold_days=0 means a claim's
    # matures_at equals its created_at, but PENDING->AVAILABLE fires only on a
    # clock advance (PRD §2.10, §3.5). The streak's qualifying week is the week in
    # which a claim *reaches* AVAILABLE (PRD §3.8), so each claim must be matured by
    # advancing the clock to a later instant *within the same week it was filed*.
    set_clock("2026-01-05T00:00:00Z")
    create_online_click_and_claim(member["id"], merchant["id"], 10000)
    set_clock("2026-01-05T01:00:00Z")  # matures claim 1 inside week index 2922
    set_clock("2026-01-12T00:00:00Z")
    create_online_click_and_claim(member["id"], merchant["id"], 10000)
    set_clock("2026-01-12T01:00:00Z")  # matures claim 2 inside week index 2923
    set_clock("2026-01-19T00:00:00Z")
    create_online_click_and_claim(member["id"], merchant["id"], 10000)
    set_clock("2026-01-19T01:00:00Z")  # matures claim 3 inside week index 2924
    streak = validate_success(api.get_member_bonus_streak(member["id"], hdr))
    if isinstance(streak, list):
        streak = streak[0]
    assert streak["current_streak_weeks"] == 3, \
        f"expected a 3-week streak, got {streak['current_streak_weeks']}"
    # Per-week round_half_up then sum: 25 + round(37.5)=38 + 50 = 113.
    assert streak["pending_streak_bonus_cents"] == 113, \
        f"streak bonus must be 113, got {streak['pending_streak_bonus_cents']}"
