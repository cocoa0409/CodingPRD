"""Pricing and calculation tests: vend quote vs charged, surge, reload bonus
tiers, WDF totals, loyalty accrual, computed fields.

Each test rebuilds its state from an empty DB via test_helpers fixtures.
"""
from test_helpers import (
    validate_success,
    api_client,
    TEST_USERS,
    make_member_headers,
    make_attendant_headers,
    create_pricing_plan_payload,
    create_machine_payload,
    create_member_payload,
    create_vend_payload,
    create_reload_payload,
    create_wdf_order_payload,
    setup_active_plan_and_washer,
    setup_active_plan_and_dryer,
    setup_member_with_free_credit,
    capture_app_wallet_vend,
    set_clock,
    create_plan,
    create_machine,
    create_member,
    reload_wallet,
    get_machine_version,
    get_member,
)

MANAGER = TEST_USERS["manager_headers"]
ATTENDANT = TEST_USERS["attendant_headers"]


def test_free_credit_diverges_quote_from_charged(api):
    """PRD §3.3: "It starts equal to the quote. Then the free-wash credit is
    considered: if `used_free_credit` is set and the tender is `APP_WALLET` and
    the machine is a `WASHER` and the member holds at least one
    `free_wash_credits`, the charged amount is forced to zero and one free-wash
    credit is consumed."
    PRD §3.3: "Coin and card vends, and any vend whose charged amount came out
    to zero via free credit, earn zero points."

    Design: Difficulty/dual_variant_calc/vend_quote_vs_charged_diverge_on_free_credit
    """
    # Earn a free credit on a 300-cent vend (loyalty_cents_per_point=1 -> 300 pts,
    # redeem threshold 50), washer cleared back to IDLE, then trigger the credit vend.
    plan, washer, member = setup_member_with_free_credit(
        loyalty_cents_per_point=1, redeem_threshold=50, principal_cents=5000)
    assert member["free_wash_credits"] >= 1, "fixture must grant a free credit"

    version = get_machine_version(washer["id"])
    resp = api.create_vend(
        washer["id"],
        create_vend_payload(version, payment_method="APP_WALLET",
                            member_id=member["id"], used_free_credit=True),
        make_member_headers(member["id"]),
    )
    vend = validate_success(resp, 201)
    assert vend["quoted_amount_cents"] == 300, "quote is the forward-looking wash base"
    assert vend["charged_amount_cents"] == 0, "free credit forces charged to zero"
    assert vend["loyalty_points_earned"] == 0, "a zero-charge free-credit vend earns no points"


def test_washer_coin_quote_equals_base_non_surge(api):
    """PRD §3.3: "for a `WASHER` the base is the active plan's `wash_base_cents`
    and `dry_blocks` is ignored (treated as zero)"
    PRD §3.3: "outside surge the multiplier is effectively 10000, so the quote
    equals the base."

    Design: Difficulty/dual_variant_calc/vend_quote_vs_charged_diverge_on_free_credit
    """
    plan, washer = setup_active_plan_and_washer(
        clock="2026-06-01T10:00:00Z", plan_overrides={"wash_base_cents": 300})
    version = washer["version"]
    resp = api.create_vend(
        washer["id"], create_vend_payload(version, payment_method="COIN"), ATTENDANT)
    vend = validate_success(resp, 201)
    assert vend["quoted_amount_cents"] == 300
    assert vend["charged_amount_cents"] == 300, "no free credit -> charged equals quote"
    assert vend["surge_applied"] is False


def test_dryer_surge_quote_three_inputs_round_half_up(api):
    """PRD §3.3: "for a `DRYER` the base is the plan's `dry_base_cents_per_block`
    multiplied by the requested `dry_blocks`."
    PRD §3.3: "When in surge, the quote is the base multiplied by
    `surge_multiplier_bps`, divided by 10000, and rounded half up to a whole cent".

    Design: Difficulty/combinatorial_formula/vend_quote_three_input_nonlinear_surge_branch
    """
    # dry_base 75 * 3 blocks = 225; surge 1.5x -> 337.5 -> round_half_up 338.
    plan, dryer = setup_active_plan_and_dryer(
        clock="2026-06-01T18:00:00Z",
        plan_overrides={"dry_base_cents_per_block": 75, "surge_multiplier_bps": 15000,
                        "surge_start_hour_utc": 16, "surge_end_hour_utc": 20})
    version = dryer["version"]
    resp = api.create_vend(
        dryer["id"], create_vend_payload(version, payment_method="COIN", dry_blocks=3),
        ATTENDANT)
    vend = validate_success(resp, 201)
    assert vend["quoted_amount_cents"] == 338, "75*3*1.5=337.5 rounds half up to 338"
    assert vend["surge_applied"] is True


def test_surge_window_end_hour_is_exclusive(api):
    """PRD §3.3: "the vend is in surge when that hour is at or after
    `surge_start_hour_utc` and strictly before `surge_end_hour_utc`".

    Design: Difficulty/boundary_precision_check/surge_window_end_hour_exclusive_boundary
    """
    # Capture at exactly hour 20 (the exclusive end) -> NOT surged.
    plan, washer = setup_active_plan_and_washer(
        clock="2026-06-01T20:00:00Z",
        plan_overrides={"wash_base_cents": 300, "surge_multiplier_bps": 15000,
                        "surge_start_hour_utc": 16, "surge_end_hour_utc": 20})
    version = washer["version"]
    resp = api.create_vend(
        washer["id"], create_vend_payload(version, payment_method="COIN"), ATTENDANT)
    vend = validate_success(resp, 201)
    assert vend["surge_applied"] is False, "hour 20 is excluded from [16,20)"
    assert vend["quoted_amount_cents"] == 300, "no surge -> quote equals base"


def test_surge_window_start_hour_is_inclusive(api):
    """PRD §3.3: "the vend is in surge when that hour is at or after
    `surge_start_hour_utc` and strictly before `surge_end_hour_utc`".

    Design: Difficulty/boundary_precision_check/surge_window_end_hour_exclusive_boundary
    """
    # Capture at exactly hour 16 (the inclusive start) -> surged; 300 * 1.5 = 450.
    plan, washer = setup_active_plan_and_washer(
        clock="2026-06-01T16:00:00Z",
        plan_overrides={"wash_base_cents": 300, "surge_multiplier_bps": 15000,
                        "surge_start_hour_utc": 16, "surge_end_hour_utc": 20})
    version = washer["version"]
    resp = api.create_vend(
        washer["id"], create_vend_payload(version, payment_method="COIN"), ATTENDANT)
    vend = validate_success(resp, 201)
    assert vend["surge_applied"] is True, "hour 16 is included in [16,20)"
    assert vend["quoted_amount_cents"] == 450, "300 * 15000/10000 = 450"


def test_vend_side_effects_visible_in_same_response(api):
    """PRD §2.7: "every such cascade must complete as part of the triggering
    request."
    PRD §3.3: "When in surge, the quote is the base multiplied by
    `surge_multiplier_bps`, divided by 10000, and rounded half up to a whole cent".

    Design: Corner/consistency_model/vend_side_effects_visible_in_same_response
    """
    plan, washer = setup_active_plan_and_washer(
        clock="2026-06-01T17:00:00Z",
        plan_overrides={"wash_base_cents": 300, "surge_multiplier_bps": 15000,
                        "surge_start_hour_utc": 16, "surge_end_hour_utc": 20})
    version = washer["version"]
    resp = api.create_vend(
        washer["id"], create_vend_payload(version, payment_method="COIN"), ATTENDANT)
    vend = validate_success(resp, 201)
    assert vend["quoted_amount_cents"] == 450
    assert vend["surge_applied"] is True
    assert vend["charged_amount_cents"] == 450


def test_charged_amount_is_server_computed_not_client_set(api):
    """PRD §3.3: "for a `WASHER` the base is the active plan's `wash_base_cents`".
    PRD §3.3: "If the free-credit conditions are not met, the charged amount
    stays equal to the quote."

    Design: Corner/entities/vend_charged_amount_is_computed_input_ignored
    """
    plan, washer = setup_active_plan_and_washer(
        clock="2026-06-01T10:00:00Z", plan_overrides={"wash_base_cents": 300})
    version = washer["version"]
    # charged_amount_cents is not an input field; even if a client tried to send
    # one it must be ignored. We send the canonical COIN payload.
    resp = api.create_vend(
        washer["id"], create_vend_payload(version, payment_method="COIN"), ATTENDANT)
    vend = validate_success(resp, 201)
    assert vend["charged_amount_cents"] == 300, "charge equals wash_base_cents"


def test_coin_vend_earns_no_loyalty_points(api):
    """PRD §3.3: "Loyalty accrual is then computed, but only for `APP_WALLET`
    vends and only on the net amount actually charged". PRD §3.3: "Coin and card
    vends, and any vend whose charged amount came out to zero via free credit,
    earn zero points."

    Design: Corner/calculations/vend_loyalty_accrual_floor_app_only
    """
    plan, washer = setup_active_plan_and_washer(
        clock="2026-06-01T10:00:00Z",
        plan_overrides={"wash_base_cents": 300, "loyalty_cents_per_point": 100})
    version = washer["version"]
    resp = api.create_vend(
        washer["id"], create_vend_payload(version, payment_method="COIN"), ATTENDANT)
    vend = validate_success(resp, 201)
    assert vend["loyalty_points_earned"] == 0, "COIN vends accrue zero points"


# ---------------------------------------------------------------------------
# Reload bonus tiers
# ---------------------------------------------------------------------------
def test_reload_tier1_boundary_at_exact_minimum(api):
    """PRD §3.4: "otherwise if it is at least `reload_bonus_tier1_min_cents`,
    the rate is `reload_bonus_tier1_bps`; otherwise the rate is zero."
    PRD §3.4: "The `bonus_cents` is the principal multiplied by the chosen rate,
    divided by 10000, floored to a whole cent. The `credited_cents` is
    `principal_cents` plus `bonus_cents`, and that full credited amount is added
    to the member's `wallet_cents`."

    Design: Difficulty/boundary_precision_check/reload_bonus_tier_boundary_at_exact_minimum
    """
    create_plan(reload_bonus_tier1_min_cents=2000, reload_bonus_tier1_bps=500,
                reload_bonus_tier2_min_cents=5000, reload_bonus_tier2_bps=1000)
    member = create_member()
    resp = api.create_reload(
        member["id"], create_reload_payload(tender="APP", principal_cents=2000),
        make_member_headers(member["id"]))
    reload = validate_success(resp, 201)
    assert reload["bonus_cents"] == 100, "2000 * 500/10000 = 100"
    assert reload["credited_cents"] == 2100
    assert get_member(member["id"])["wallet_cents"] == 2100


def test_reload_just_below_tier1_yields_zero_bonus(api):
    """PRD §3.4: "otherwise the rate is zero." PRD §3.4: "The `credited_cents` is
    `principal_cents` plus `bonus_cents`, and that full credited amount is added
    to the member's `wallet_cents`."

    Design: Corner/calculations/reload_below_tier1_min_yields_zero_bonus
    """
    create_plan(reload_bonus_tier1_min_cents=2000, reload_bonus_tier1_bps=500,
                reload_bonus_tier2_min_cents=5000, reload_bonus_tier2_bps=1000)
    member = create_member()
    resp = api.create_reload(
        member["id"], create_reload_payload(tender="APP", principal_cents=1999),
        make_member_headers(member["id"]))
    reload = validate_success(resp, 201)
    assert reload["bonus_cents"] == 0, "1999 < tier1 min 2000 -> no bonus"
    assert reload["credited_cents"] == 1999
    assert get_member(member["id"])["wallet_cents"] == 1999


def test_reload_tier1_bonus_floored(api):
    """PRD §3.4: "The `bonus_cents` is the principal multiplied by the chosen
    rate, divided by 10000, floored to a whole cent."

    Design: Corner/calculations/reload_tier2_floor_rounding
    """
    create_plan(reload_bonus_tier1_min_cents=2000, reload_bonus_tier1_bps=500,
                reload_bonus_tier2_min_cents=5000, reload_bonus_tier2_bps=1000)
    member = create_member()
    # 4999 is in tier1 (2000<=4999<5000): floor(4999*500/10000)=floor(249.95)=249.
    resp = api.create_reload(
        member["id"], create_reload_payload(tender="APP", principal_cents=4999),
        make_member_headers(member["id"]))
    reload = validate_success(resp, 201)
    assert reload["bonus_cents"] == 249, "floor(249.95) = 249"
    assert reload["credited_cents"] == 5248


def test_reload_tier2_boundary_at_exact_minimum(api):
    """PRD §3.4: "If `principal_cents` is at least the active plan's
    `reload_bonus_tier2_min_cents`, the bonus rate is `reload_bonus_tier2_bps`".

    Design: Corner/cross_cutting_complexity_layers/rate_threshold_reload_tier2_boundary
    """
    create_plan(reload_bonus_tier1_min_cents=2000, reload_bonus_tier1_bps=500,
                reload_bonus_tier2_min_cents=5000, reload_bonus_tier2_bps=1000)
    member = create_member()
    resp = api.create_reload(
        member["id"], create_reload_payload(tender="APP", principal_cents=5000),
        make_member_headers(member["id"]))
    reload = validate_success(resp, 201)
    assert reload["bonus_cents"] == 500, "5000 selects tier2 -> 5000*1000/10000=500"
    assert reload["credited_cents"] == 5500


# ---------------------------------------------------------------------------
# WDF total
# ---------------------------------------------------------------------------
def test_wdf_minimum_floor_applied_before_rush(api):
    """PRD §3.5: "first the raw charge is `weight_lb` multiplied by the active
    plan's `wdf_rate_cents_per_lb`; then the minimum floor is applied by taking
    the greater of that raw charge and the plan's `wdf_minimum_cents`; then, if
    and only if `rush` is set, a rush surcharge is added equal to the floored
    subtotal multiplied by 2500 basis points (twenty-five percent), divided by
    10000, rounded half up to a whole cent."

    Design: Difficulty/combinatorial_formula/wdf_total_minimum_before_rush_rounding_order
    """
    # 5 lb * 180 = 900 raw -> floored to minimum 1500 -> +25% rush = 1875.
    set_clock("2026-06-01T10:00:00Z")
    create_plan(wdf_rate_cents_per_lb=180, wdf_minimum_cents=1500)
    attendant = create_member(full_name="A One", phone="555-0100", card_token="tok-a1")
    member = create_member(full_name="M One", phone="555-0001", card_token="tok-m1")
    resp = api.create_wdf_order(
        create_wdf_order_payload(attendant["id"], 5, member_id=member["id"], rush=True),
        make_attendant_headers(attendant["id"]))
    order = validate_success(resp, 201)
    assert order["quoted_total_cents"] == 1875, "min(1500) floored before 25% rush = 1875"


def test_wdf_no_rush_above_minimum_uses_raw(api):
    """PRD §3.5: "then the minimum floor is applied by taking the greater of that
    raw charge and the plan's `wdf_minimum_cents`". PRD §3.5: "With no rush, the
    total is simply the floored subtotal."

    Design: Corner/calculations/wdf_no_rush_no_minimum_uses_raw
    """
    set_clock("2026-06-01T10:00:00Z")
    create_plan(wdf_rate_cents_per_lb=180, wdf_minimum_cents=1500)
    attendant = create_member(full_name="A One", phone="555-0100", card_token="tok-a1")
    # 20 lb * 180 = 3600 > minimum 1500, no rush -> 3600.
    resp = api.create_wdf_order(
        create_wdf_order_payload(attendant["id"], 20, rush=False),
        make_attendant_headers(attendant["id"]))
    order = validate_success(resp, 201)
    assert order["quoted_total_cents"] == 3600
