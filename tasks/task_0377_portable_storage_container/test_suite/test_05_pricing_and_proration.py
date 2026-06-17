"""Depth tests for dual-variant and combinatorial pricing/proration formulas, plus the
move-class and late-fee boundary precision checks (PRD §3.4, §3.6, §3.7, §3.8, §3.9)."""
from test_helpers import (
    validate_success, validate_paginated,
    create_packing_supply_order_payload,
    TEST_USERS, make_customer_headers,
)
from test_helpers import fixtures as F

DO = TEST_USERS["dispatch_operator_headers"]
BC = TEST_USERS["billing_clerk_headers"]


# ── Rule 1: dual_variant_calc / rental_proration_calendar_vs_fixed30_diverge ──

def _proration_amount(api, agreement_id):
    charges, _ = validate_paginated(
        api.list_charges(agreement_id, BC, params={"charge_type": "RENTAL_PRORATION"}))
    assert len(charges) == 1
    return charges[0]["amount_cents"]


def test_proration_calendar_day_july_16(api):
    """PRD §3.4: "Under the `CALENDAR_DAY` method, the proration is the monthly amount
    multiplied by the days billed and divided by the actual number of days in the delivery
    calendar month (28, 29, 30, or 31), rounded half up to whole cents."

    Design: Difficulty/dual_variant_calc/rental_proration_calendar_vs_fixed30_diverge
    """
    # C16 monthly 19900, delivered 2026-07-16: days_billed = 31-16+1 = 16.
    # CALENDAR_DAY: round(19900*16/31) = round(10270.96..) = 10271.
    world, ag, unit = F.setup_active_agreement(
        tier_code="NONE", proration_method="CALENDAR_DAY", monthly_rate_cents=19900)
    assert _proration_amount(api, ag["id"]) == 10271


def test_proration_fixed30_diverges_from_calendar(api):
    """PRD §3.4: "Under the `FIXED_30` method, the proration is the monthly amount
    multiplied by the days billed and divided by 30 regardless of the month's true length,
    rounded half up to whole cents; the two methods diverge in any 31-day month and in
    February."

    Design: Difficulty/dual_variant_calc/rental_proration_calendar_vs_fixed30_diverge
    """
    # FIXED_30: round(19900*16/30) = round(10613.33) = 10613; divergence from CALENDAR 342.
    world, ag, unit = F.setup_active_agreement(
        tier_code="NONE", proration_method="FIXED_30", monthly_rate_cents=19900)
    fixed = _proration_amount(api, ag["id"])
    assert fixed == 10613
    assert fixed - 10271 == 342


# ── Rule 1: dual_variant_calc / agreement_balance_provisional_vs_final_diverge ──

def test_balance_provisional_excludes_move(api):
    """PRD §3.8: "Under the provisional variant — used while `lifecycle_status` is `ACTIVE`
    or `ON_HOLD` — only debits of type `DELIVERY_FEE`, `RENTAL_PRORATION`, `RENTAL_CYCLE`,
    `PROTECTION_PREMIUM`, `PACKING_SUPPLIES`, and `ACCESS_FEE` are counted; `MOVE` and
    `LATE_FEE` debits are excluded because they are not collectible until closeout."

    Design: Difficulty/dual_variant_calc/agreement_balance_provisional_vs_final_diverge
    """
    # PLUS C16 delivered 2026-07-16: DELIVERY_FEE 8900 + RENTAL_PRORATION 10271 +
    # PROTECTION_PREMIUM 5500 (1500 + round(80*500000/10000=4000)=5500) = 24671 provisional.
    world, ag, unit = F.setup_active_agreement(
        tier_code="PLUS", declared_value_cents=500000,
        plan_overrides={"base_premium_cents": 1500, "rate_bps": 80,
                        "min_premium_cents": 2000, "coverage_cap_cents": 100000000},
        with_truck=True)
    F.schedule_move(world, ag, unit, destination_state_code="CA", distance_miles=30)

    fresh = validate_success(api.get_rental_agreement(ag["id"], BC), 200)
    assert fresh["balance_due_cents"] == 24671  # MOVE 19400 excluded under PROVISIONAL


def test_balance_final_after_move_cancel_nets_to_provisional(api):
    """PRD §3.6: "Cancelling a scheduled move advances it `SCHEDULED → CANCELLED`; if a
    `MOVE` charge was posted at scheduling, the system posts a compensating `ADJUSTMENT`
    charge equal to the negative of `quoted_cost_cents` and recomputes `balance_due_cents`,
    so the ledger nets back to where it stood before the move."

    Design: Difficulty/dual_variant_calc/agreement_balance_provisional_vs_final_diverge
    """
    world, ag, unit = F.setup_active_agreement(
        tier_code="PLUS", declared_value_cents=500000,
        plan_overrides={"base_premium_cents": 1500, "rate_bps": 80,
                        "min_premium_cents": 2000, "coverage_cap_cents": 100000000},
        with_truck=True)
    cust_id = world["customer"]["id"]
    move = F.schedule_move(world, ag, unit, destination_state_code="CA", distance_miles=30)

    validate_success(api.cancel_move_order(move["id"], DO), 200)
    F.request_closeout(ag, cust_id)  # flip to FINAL scope

    final = validate_success(api.get_rental_agreement(ag["id"], BC), 200)
    # FINAL includes MOVE 19400 and the -19400 ADJUSTMENT, netting to the pre-move 24671.
    assert final["balance_due_cents"] == 24671


# ── Rule 2: combinatorial_formula / move_pricing_marginal_tiered_bands_mode_a ──

def test_long_distance_move_pricing_marginal_bands(api):
    """PRD §3.6: "the first 500 miles are billed at 180 cents per mile; the miles above 500
    and up to 1,500 are billed at 140 cents per mile; the miles above 1,500 are billed at
    110 cents per mile. Summing those three band contributions gives the mileage amount.
    The fuel surcharge is 12 percent of that mileage amount, computed once on the summed
    mileage amount and rounded half up to whole cents. Per-container handling adds a flat
    12,500 cents for the single container the move carries. The `quoted_cost_cents` is the
    sum of the mileage amount, the fuel surcharge, and the handling amount."

    Design: Difficulty/combinatorial_formula/move_pricing_marginal_tiered_bands_mode_a
    """
    # 1800mi: 500*180 + 1000*140 + 300*110 = 263000 mileage; fuel round(263000*0.12)=31560;
    # handling 12500; total 307060.
    world, ag, unit = F.setup_active_agreement(tier_code="NONE", with_truck=True)
    move = F.schedule_move(
        world, ag, unit, destination_state_code="TX", distance_miles=1800,
        window_start="2026-07-20T09:00:00Z", window_end="2026-07-21T11:00:00Z")
    assert move["move_class"] == "LONG_DISTANCE"
    assert move["quoted_cost_cents"] == 307060


def test_long_distance_move_posts_move_charge(api):
    """PRD §3.6: "On successful creation the system posts a `MOVE` charge equal to
    `quoted_cost_cents`".

    Design: Difficulty/combinatorial_formula/move_pricing_marginal_tiered_bands_mode_a
    """
    world, ag, unit = F.setup_active_agreement(tier_code="NONE", with_truck=True)
    move = F.schedule_move(
        world, ag, unit, destination_state_code="TX", distance_miles=1800,
        window_start="2026-07-20T09:00:00Z", window_end="2026-07-21T11:00:00Z")
    charges, _ = validate_paginated(
        api.list_charges(ag["id"], BC, params={"charge_type": "MOVE"}))
    assert len(charges) == 1
    assert charges[0]["amount_cents"] == 307060 == move["quoted_cost_cents"]


# ── Rule 2: combinatorial_formula / packing_supplies_sum_then_tax_mode_b ──

def _packing_three_733_lines(api, agreement_id, cust_id):
    lines = [
        {"sku": "BUBBLE", "qty": 1, "unit_price_cents": 733, "bulk_threshold": 5, "bulk_pct": 0},
        {"sku": "PAPER", "qty": 1, "unit_price_cents": 733, "bulk_threshold": 5, "bulk_pct": 0},
        {"sku": "TAPE", "qty": 1, "unit_price_cents": 733, "bulk_threshold": 5, "bulk_pct": 0},
    ]
    return validate_success(api.create_packing_supply_order(
        create_packing_supply_order_payload(agreement_id, lines=lines, tax_rate_bps=825),
        make_customer_headers(cust_id)), 201)


def test_packing_supplies_subtotal_sum_of_line_nets(api):
    """PRD §3.7: "The `subtotal_cents` is the sum of all the line nets."

    Design: Difficulty/combinatorial_formula/packing_supplies_sum_then_tax_mode_b
    """
    world, ag, unit = F.setup_active_agreement(tier_code="NONE")
    pso = _packing_three_733_lines(api, ag["id"], world["customer"]["id"])
    assert pso["subtotal_cents"] == 2199  # 733*3


def test_packing_supplies_tax_once_on_summed_subtotal(api):
    """PRD §3.7: "The `tax_cents` is computed exactly once on the summed subtotal —
    `subtotal_cents` multiplied by `tax_rate_bps` divided by 10,000, rounded half up to
    whole cents — and never per line. The `total_cents` is `subtotal_cents` plus
    `tax_cents`."

    Design: Difficulty/combinatorial_formula/packing_supplies_sum_then_tax_mode_b
    """
    world, ag, unit = F.setup_active_agreement(tier_code="NONE")
    pso = _packing_three_733_lines(api, ag["id"], world["customer"]["id"])
    # round(2199*825/10000)=round(181.4175)=181; total 2380 (per-line tax would give 2379).
    assert pso["tax_cents"] == 181
    assert pso["total_cents"] == 2380


# ── Rule 6: boundary_precision_check / late_fee_grace_boundary_5_vs_6_days ──

def test_late_fee_at_grace_boundary_5_days_no_fee(api):
    """PRD §3.9: "A grace period of 5 days applies: while `days_overdue` is at or below 5,
    the late fee is 0." PRD §3.9: "An agreement that is `CURRENT` and whose `days_overdue`
    is above 5 but at or below 20 advances `CURRENT → PAST_DUE`".

    Design: Difficulty/boundary_precision_check/late_fee_grace_boundary_5_vs_6_days
    """
    # Delivered 2026-07-16 (oldest due 2026-07-16); at 2026-07-21 days_overdue == 5.
    world, ag, unit = F.setup_active_agreement(
        tier_code="PLUS", declared_value_cents=500000,
        plan_overrides={"base_premium_cents": 1500, "rate_bps": 80,
                        "min_premium_cents": 2000, "coverage_cap_cents": 100000000})
    F.advance_clock_and_sweep("2026-07-21T12:00:00Z")
    at5 = validate_success(api.get_rental_agreement(ag["id"], BC), 200)
    assert at5["billing_status"] == "CURRENT"
    late, _ = validate_paginated(
        api.list_charges(ag["id"], BC, params={"charge_type": "LATE_FEE"}))
    assert len(late) == 0


def test_late_fee_just_past_grace_6_days_posts_fee(api):
    """PRD §3.9: "Beyond the grace period, let the effective overdue days be `days_overdue`
    minus 5. The first 10 of those effective days are tier-one days; any effective days
    beyond 10 are tier-two escalation days. The gross late fee is a flat 2,500 cents, plus
    200 cents for each tier-one day, plus 500 cents for each tier-two day."

    Design: Difficulty/boundary_precision_check/late_fee_grace_boundary_5_vs_6_days
    """
    # At 2026-07-22 days_overdue == 6; eff=1; gross 2500+200=2700; balance 24671 so cap not binding.
    world, ag, unit = F.setup_active_agreement(
        tier_code="PLUS", declared_value_cents=500000,
        plan_overrides={"base_premium_cents": 1500, "rate_bps": 80,
                        "min_premium_cents": 2000, "coverage_cap_cents": 100000000})
    F.advance_clock_and_sweep("2026-07-22T12:00:00Z")
    at6 = validate_success(api.get_rental_agreement(ag["id"], BC), 200)
    assert at6["billing_status"] == "PAST_DUE"
    late, _ = validate_paginated(
        api.list_charges(ag["id"], BC, params={"charge_type": "LATE_FEE"}))
    assert len(late) == 1
    assert late[0]["amount_cents"] == 2700


# ── Rule 6: boundary_precision_check / move_class_radius_boundary_50_vs_51_miles ──

def test_move_class_local_at_radius_boundary(api):
    """PRD §3.6: "The move is classified `LOCAL` when its `distance_miles` is at or below
    the origin depot's `service_radius_miles` ... the boundary at exactly the radius is
    `LOCAL`." PRD §3.6: "A `LOCAL` move's `quoted_cost_cents` is a flat base of 8,900 cents
    plus 350 cents for each mile of `distance_miles`".

    Design: Difficulty/boundary_precision_check/move_class_radius_boundary_50_vs_51_miles
    """
    # radius 50, distance 50 -> LOCAL: 8900 + 350*50 = 26400.
    world, ag, unit = F.setup_active_agreement(
        tier_code="NONE", with_truck=True, service_radius_miles=50)
    move = F.schedule_move(world, ag, unit, destination_state_code="CA", distance_miles=50)
    assert move["move_class"] == "LOCAL"
    assert move["quoted_cost_cents"] == 26400


def test_move_class_long_distance_just_past_radius(api):
    """PRD §3.6: "and `LONG_DISTANCE` when the distance exceeds that radius". PRD §3.6:
    "the first 500 miles are billed at 180 cents per mile ... The fuel surcharge is 12
    percent of that mileage amount, computed once on the summed mileage amount and rounded
    half up to whole cents. Per-container handling adds a flat 12,500 cents".

    Design: Difficulty/boundary_precision_check/move_class_radius_boundary_50_vs_51_miles
    """
    # radius 50, distance 51 -> LONG_DISTANCE: mileage 51*180=9180; fuel round(9180*0.12)=1102;
    # handling 12500; total 22782.
    world, ag, unit = F.setup_active_agreement(
        tier_code="NONE", with_truck=True, service_radius_miles=50)
    move = F.schedule_move(world, ag, unit, destination_state_code="CA", distance_miles=51)
    assert move["move_class"] == "LONG_DISTANCE"
    assert move["quoted_cost_cents"] == 22782
