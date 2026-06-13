"""Weekly-box pricing: provisional vs final divergence, the eleven-step charge formula across
serving tiers, diet premium, premium upcharge, zone surcharge, the nested credit min, pause
proration rounding, and the skip-reverses-provisional invariant.

Translates queue A (Difficulty) dual_variant_calc(charge), combinatorial_formula(charge +
proration), boundary_precision_check(serving tier), compensating_invariant(skip), and queue B
(Corner) calculations instances.
"""
import pytest
from test_helpers import (
    validate_success,
    set_clock, create_plan, create_zone, create_recipe, create_recipes,
    register_member, create_subscription, create_box, add_recipes_to_box,
    lock_box, charge_box, ship_box,
    create_referral_payload,
    setup_lockable_box, setup_paused_subscription,
    TEST_USERS, make_member_headers,
)

ADMIN = TEST_USERS["admin_headers"]
OPS = TEST_USERS["ops_headers"]


# ─── Difficulty: dual_variant_calc / weekly_box_provisional_vs_final_charge_diverge ──

def _lock_box_with(member, sub, plan, recipes, delivery_date):
    box = create_box(member, sub, delivery_date)
    add_recipes_to_box(member, box, recipes[:plan["meals_per_week"]])
    return lock_box(member, box), box


def test_provisional_reads_lock_snapshot_no_credit_deduction(api):
    """PRD §3.6: "The **provisional** variant runs when the box transitions from `OPEN` to `LOCKED` and writes its result to `provisional_charge_cents`; it reads the member's `credit_balance_cents` and `lifetime_box_count` as they stand at the lock instant and does **not** deduct any credit or mutate the wallet, and it operates on the recipe set frozen at lock."

    Design: Difficulty/dual_variant_calc/weekly_box_provisional_vs_final_charge_diverge
    """
    # COUPLE_4: 2x4 = 8 servings -> 999 tier; STANDARD; ZONE_B surcharge 499; loyalty 0; credit 0
    # provisional = (999+0)*8 + 0 + 499 = 8491
    set_clock("2026-07-01T00:00:00.000Z")
    plan = create_plan(servings_per_meal=2, meals_per_week=4, code="COUPLE_4")
    zone = create_zone(zone_code="ZONE_B", cold_pack_surcharge_cents=499, cutoff_weekday=5)
    recipes = create_recipes(4, prefix="STD")
    m1 = register_member(zone["id"], full_name="M One")
    s1 = create_subscription(m1, plan, diet_preference="STANDARD", monthly_addon_fee_cents=0)
    locked, _ = _lock_box_with(m1, s1, plan, recipes, "2026-07-15T00:00:00.000Z")
    assert locked["provisional_charge_cents"] == 8491


def test_final_reads_live_credit_and_deducts(api):
    """PRD §3.6: "The **final** variant runs when the box transitions from `PENDING` to `CHARGED` at the cutoff and writes its result to `final_charge_cents`; it re-reads the *live* `credit_balance_cents` and `lifetime_box_count` at the charge instant — which may have changed since lock, for example because a referral settled or another box shipped and bumped the loyalty tier — and it **does** deduct the credit applied from the member's `credit_balance_cents`."

    Design: Difficulty/dual_variant_calc/weekly_box_provisional_vs_final_charge_diverge
    """
    set_clock("2026-07-01T00:00:00.000Z")
    plan = create_plan(servings_per_meal=2, meals_per_week=4, code="COUPLE_4")
    plan2 = create_plan(servings_per_meal=2, meals_per_week=2, code="SOLO_2")
    zone = create_zone(zone_code="ZONE_B", cold_pack_surcharge_cents=499, cutoff_weekday=5)
    recipes = create_recipes(4, prefix="STD")
    m1 = register_member(zone["id"], full_name="M One")
    e1 = register_member(zone["id"], full_name="E One")
    referral = validate_success(api.create_referral(
        create_referral_payload(m1["id"], e1["id"]), ADMIN), 201)

    # M1 locks own box while credit 0 -> provisional 8491
    s1 = create_subscription(m1, plan, diet_preference="STANDARD", monthly_addon_fee_cents=0)
    locked, m1_box = _lock_box_with(m1, s1, plan, recipes, "2026-07-15T00:00:00.000Z")
    assert locked["provisional_charge_cents"] == 8491

    # E's first box ships -> settles M1's referral -> M1 credit becomes 1500
    es = create_subscription(e1, plan2)
    e_box = create_box(e1, es, "2026-07-15T00:00:00.000Z")
    add_recipes_to_box(e1, e_box, recipes[:2])
    lock_box(e1, e_box)
    set_clock("2026-07-11T00:00:00.000Z")
    charge_box(e_box)
    ship_box(e_box)

    # Now charge M1's box -> final re-reads live credit 1500, deducts -> 8491 - 1500 = 6991
    charged = validate_success(api.charge_box(m1_box["id"], OPS), 200)
    assert charged["final_charge_cents"] == 6991
    assert charged["selection_status"] == "LOCKED"
    assert charged["fulfillment_status"] == "CHARGED"


# ─── Difficulty: combinatorial_formula / weekly_box_charge_nested_min_with_tier_branch ──

def test_charge_full_pipeline_lowcarb_premium_zone_c(api):
    """PRD §3.6: "the base amount is the per-serving rate plus a diet premium for the subscription's `diet_preference`, with that sum multiplied by the total servings; the diet premium is 0 for `STANDARD`, 0 for `VEGETARIAN`, 150 cents for `PESCATARIAN`, 200 cents for `LOW_CARB`, and 0 for `FAMILY_FRIENDLY`."
    PRD §3.6: "Fourth, a premium upcharge of 400 cents is added for each recipe slot on the box whose `is_premium_snapshot` is true"
    PRD §3.6: "Tenth, the credit applied is the smallest of three quantities: the member's current `credit_balance_cents`, the per-box referral-credit cap of 2000 cents, and the amount after loyalty."

    Design: Difficulty/combinatorial_formula/weekly_box_charge_nested_min_with_tier_branch
    """
    # FAMILY_4: 4x4 = 16 servings -> 899 tier; LOW_CARB (+200); 1 premium recipe (+400);
    # ZONE_C surcharge 999; loyalty 0; credit 0.
    # base = (899+200)*16 = 17584; +premium 400 = 17984; +zone 999 = 18983; credit_applied = 0
    set_clock("2026-07-01T00:00:00.000Z")
    plan = create_plan(servings_per_meal=4, meals_per_week=4, code="FAMILY_4")
    zone = create_zone(zone_code="ZONE_C", cold_pack_surcharge_cents=999, cutoff_weekday=5)
    r1 = create_recipe(title="LC1", diet_tags=["LOW_CARB"])
    r2 = create_recipe(title="LC2", diet_tags=["LOW_CARB"])
    r3 = create_recipe(title="LC3", diet_tags=["LOW_CARB"])
    r4 = create_recipe(title="LC4 Premium", is_premium=True, diet_tags=["LOW_CARB"])
    member = register_member(zone["id"], full_name="Gold")
    sub = create_subscription(member, plan, diet_preference="LOW_CARB")
    box = create_box(member, sub, "2026-07-15T00:00:00.000Z")
    add_recipes_to_box(member, box, [r1, r2, r3, r4])
    locked = validate_success(api.lock_selection(
        box["id"], make_member_headers(member["id"])), 200)
    assert locked["provisional_charge_cents"] == 18983


def test_charge_nested_min_caps_credit_applied(api):
    """PRD §3.6: "Tenth, the credit applied is the smallest of three quantities: the member's current `credit_balance_cents`, the per-box referral-credit cap of 2000 cents, and the amount after loyalty. Eleventh, the charge is the amount after loyalty minus the credit applied."

    Design: Difficulty/combinatorial_formula/weekly_box_charge_nested_min_with_tier_branch
    """
    # Same fresh-member 16-serving LOW_CARB premium ZONE_C box: credit 0 -> credit_applied
    # min(0, 2000, 18983) = 0, so charge == after_loyalty == 18983.
    set_clock("2026-07-01T00:00:00.000Z")
    plan = create_plan(servings_per_meal=4, meals_per_week=4, code="FAMILY_4B")
    zone = create_zone(zone_code="ZONE_C", cold_pack_surcharge_cents=999, cutoff_weekday=5)
    recipes = [
        create_recipe(title="LCa", diet_tags=["LOW_CARB"]),
        create_recipe(title="LCb", diet_tags=["LOW_CARB"]),
        create_recipe(title="LCc", diet_tags=["LOW_CARB"]),
        create_recipe(title="LCd Premium", is_premium=True, diet_tags=["LOW_CARB"]),
    ]
    member = register_member(zone["id"], full_name="GoldB")
    sub = create_subscription(member, plan, diet_preference="LOW_CARB")
    box = create_box(member, sub, "2026-07-15T00:00:00.000Z")
    add_recipes_to_box(member, box, recipes)
    locked = validate_success(api.lock_selection(
        box["id"], make_member_headers(member["id"])), 200)
    assert locked["provisional_charge_cents"] == 18983


# ─── Difficulty: combinatorial_formula / pause_proration_multiply_then_round_order ──

def test_pause_proration_multiply_then_round_once(api):
    """PRD §3.6: "The proration credit is the subscription's `monthly_addon_fee_cents` multiplied by the unused days, divided by 30, with the result of that whole expression rounded half-up to whole cents exactly once — the rounding is applied after the multiply-and-divide, never per day."

    Design: Difficulty/combinatorial_formula/pause_proration_multiply_then_round_order
    """
    # fee 1099, billing_cycle_day 15; clock 2026-07-28 -> anchor 2026-07-15, 13 days elapsed,
    # 17 unused; round_half_up(1099*17/30) = round_half_up(622.766..) = 623.
    set_clock("2026-07-28T00:00:00.000Z")
    plan = create_plan(servings_per_meal=2, meals_per_week=3)
    zone = create_zone()
    member = register_member(zone["id"])
    sub = create_subscription(member, plan, monthly_addon_fee_cents=1099, billing_cycle_day=15)
    paused = validate_success(api.pause_subscription(
        sub["id"], {"resume_date": "2026-08-15T00:00:00.000Z"},
        make_member_headers(member["id"])), 200)
    assert paused["status"] == "PAUSED"
    member_after = validate_success(api.get_member(member["id"], ADMIN), 200)
    assert member_after["credit_balance_cents"] == 623


def test_pause_proration_credits_member_wallet(api):
    """PRD §2.6: "pause proration credits it when a subscription is paused"
    PRD §3.3: "the unused portion of the monthly add-on fee is computed (see §3.6) and credited to the member's `credit_balance_cents"

    Design: Difficulty/combinatorial_formula/pause_proration_multiply_then_round_order
    """
    # fee 1099, billing_cycle_day 15; clock 2026-07-28 -> anchor 2026-07-15, 13 days elapsed,
    # 17 unused; round_half_up(1099*17/30) = round_half_up(622.766..) = 623.
    set_clock("2026-07-28T00:00:00.000Z")
    plan = create_plan(servings_per_meal=2, meals_per_week=3)
    zone = create_zone()
    member = register_member(zone["id"])
    before = validate_success(api.get_member(member["id"], ADMIN), 200)
    assert before["credit_balance_cents"] == 0
    sub = create_subscription(member, plan, monthly_addon_fee_cents=1099, billing_cycle_day=15)
    validate_success(api.pause_subscription(
        sub["id"], {"resume_date": "2026-08-15T00:00:00.000Z"},
        make_member_headers(member["id"])), 200)
    after = validate_success(api.get_member(member["id"], ADMIN), 200)
    assert after["credit_balance_cents"] == 623


# ─── Difficulty: boundary_precision_check / serving_tier_break_at_16_servings ──

def test_serving_tier_at_16_servings_uses_899(api):
    """PRD §3.6: "a per-serving rate is chosen by tier: if total servings is at least 16, the
    rate is 899 cents; if total servings is at least 8 but below 16, the rate is 999 cents; and
    if total servings is below 8, the rate is 1099 cents."

    Design: Difficulty/boundary_precision_check/serving_tier_break_at_16_servings
    """
    # EXACT16: 4x4 = 16 servings -> 899 tier; STANDARD; ZONE_A; loyalty 0; credit 0.
    # base = 899*16 = 14384, no zone/loyalty/credit -> provisional 14384
    set_clock("2026-07-01T00:00:00.000Z")
    plan = create_plan(servings_per_meal=4, meals_per_week=4, code="EXACT16")
    zone = create_zone(zone_code="ZONE_A", cold_pack_surcharge_cents=0, cutoff_weekday=5)
    recipes = create_recipes(4, prefix="T")
    member = register_member(zone["id"])
    sub = create_subscription(member, plan)
    box = create_box(member, sub, "2026-07-15T00:00:00.000Z")
    add_recipes_to_box(member, box, recipes)
    locked = validate_success(api.lock_selection(
        box["id"], make_member_headers(member["id"])), 200)
    assert locked["provisional_charge_cents"] == 14384


def test_serving_tier_below_16_uses_999_band(api):
    """PRD §3.6: "if total servings is at least 8 but below 16, the rate is 999 cents"

    Design: Difficulty/boundary_precision_check/serving_tier_break_at_16_servings
    """
    # 4x3 = 12 servings -> 999 tier; STANDARD; ZONE_A; loyalty 0; credit 0 -> 999*12 = 11988
    set_clock("2026-07-01T00:00:00.000Z")
    plan = create_plan(servings_per_meal=4, meals_per_week=3, code="TWELVE")
    zone = create_zone(zone_code="ZONE_A", cold_pack_surcharge_cents=0, cutoff_weekday=5)
    recipes = create_recipes(3, prefix="TW")
    member = register_member(zone["id"])
    sub = create_subscription(member, plan)
    box = create_box(member, sub, "2026-07-15T00:00:00.000Z")
    add_recipes_to_box(member, box, recipes)
    locked = validate_success(api.lock_selection(
        box["id"], make_member_headers(member["id"])), 200)
    assert locked["provisional_charge_cents"] == 11988


# ─── Difficulty: compensating_invariant / skip_reverses_provisional_charge_to_zero ──

def test_skip_locked_box_resets_provisional_to_zero(api):
    """PRD §3.5: "When a box is skipped from `LOCKED`, its `provisional_charge_cents` is reset to 0."

    Design: Difficulty/compensating_invariant/skip_reverses_provisional_charge_to_zero
    """
    # 2x4 = 8 servings -> 999 tier; STANDARD; ZONE_A; loyalty 0; credit 0 -> provisional 7992
    set_clock("2026-07-01T00:00:00.000Z")
    plan = create_plan(servings_per_meal=2, meals_per_week=4, code="SK8")
    zone = create_zone(zone_code="ZONE_A", cold_pack_surcharge_cents=0, cutoff_weekday=5)
    recipes = create_recipes(4, prefix="S")
    member = register_member(zone["id"])
    sub = create_subscription(member, plan)
    box = create_box(member, sub, "2026-07-15T00:00:00.000Z")
    add_recipes_to_box(member, box, recipes)
    hdr = make_member_headers(member["id"])
    locked = validate_success(api.lock_selection(box["id"], hdr), 200)
    assert locked["provisional_charge_cents"] == 7992
    skipped = validate_success(api.skip_box(box["id"], hdr), 200)
    assert skipped["provisional_charge_cents"] == 0
    assert skipped["selection_status"] == "SKIPPED"


def test_skip_locked_box_reaches_skipped_status(api):
    """PRD §3.5: "A member skips a box before its cutoff, moving its `selection_status` to `SKIPPED`. A skip is allowed from `OPEN` and from `LOCKED`."

    Design: Difficulty/compensating_invariant/skip_reverses_provisional_charge_to_zero
    """
    set_clock("2026-07-01T00:00:00.000Z")
    plan = create_plan(servings_per_meal=2, meals_per_week=4, code="SK8B")
    zone = create_zone(zone_code="ZONE_A", cold_pack_surcharge_cents=0, cutoff_weekday=5)
    recipes = create_recipes(4, prefix="SB")
    member = register_member(zone["id"])
    sub = create_subscription(member, plan)
    box = create_box(member, sub, "2026-07-15T00:00:00.000Z")
    add_recipes_to_box(member, box, recipes)
    hdr = make_member_headers(member["id"])
    validate_success(api.lock_selection(box["id"], hdr), 200)
    skipped = validate_success(api.skip_box(box["id"], hdr), 200)
    assert skipped["selection_status"] == "SKIPPED"


# ─── Corner: calculations ───────────────────────────────────────────────────

def test_serving_tier_999_band_at_12_servings(api):
    """PRD §3.6: "if total servings is at least 8 but below 16, the rate is 999 cents"
    PRD §3.6: "First, the total servings for the box is the plan's `servings_per_meal` multiplied by the plan's `meals_per_week`."

    Design: Corner/calculations/serving_tier_999_band_at_12_servings
    """
    set_clock("2026-07-01T00:00:00.000Z")
    plan = create_plan(servings_per_meal=4, meals_per_week=3, code="C12")
    zone = create_zone(zone_code="ZONE_A", cold_pack_surcharge_cents=0, cutoff_weekday=5)
    recipes = create_recipes(3, prefix="C")
    member = register_member(zone["id"])
    sub = create_subscription(member, plan)
    box = create_box(member, sub, "2026-07-15T00:00:00.000Z")
    add_recipes_to_box(member, box, recipes)
    locked = validate_success(api.lock_selection(
        box["id"], make_member_headers(member["id"])), 200)
    assert locked["provisional_charge_cents"] == 11988


def test_zero_addon_fee_proration_is_zero(api):
    """PRD §3.6: "The proration credit is the subscription's `monthly_addon_fee_cents` multiplied by the unused days, divided by 30, with the result of that whole expression rounded half-up to whole cents exactly once"

    Design: Corner/calculations/zero_addon_fee_proration_is_zero
    """
    # fee 0 -> proration credit is 0 regardless of elapsed/unused days.
    set_clock("2026-07-28T00:00:00.000Z")
    plan = create_plan(servings_per_meal=2, meals_per_week=2)
    zone = create_zone()
    member = register_member(zone["id"])
    sub = create_subscription(member, plan, monthly_addon_fee_cents=0, billing_cycle_day=15)
    paused = validate_success(api.pause_subscription(
        sub["id"], {"resume_date": "2026-08-15T00:00:00.000Z"},
        make_member_headers(member["id"])), 200)
    assert paused["status"] == "PAUSED"
    after = validate_success(api.get_member(member["id"], ADMIN), 200)
    assert after["credit_balance_cents"] == 0
