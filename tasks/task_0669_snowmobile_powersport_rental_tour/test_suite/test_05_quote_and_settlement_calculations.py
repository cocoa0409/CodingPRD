"""Dual-variant and combinatorial billing calculations: the confirmation estimate
vs the final settlement, membership tiering, pinned rounding order, and the
deposit waterfall. Covers difficulty rules dual_variant_calc, combinatorial_formula,
and boundary_precision_check (late-fee grace)."""
from test_helpers import (
    validate_success, TEST_USERS,
    setup_confirmed_reservation, setup_checked_out_reservation,
    set_clock, read_reservation, read_member,
    create_trail, create_unit, create_gear, create_departure,
    register_signed_member, train_member, create_and_confirm_reservation,
    assert_settlement, assert_settlement_reconciles,
)

DISPATCH = TEST_USERS["dispatch_headers"]


# ===================================================================
# Rule dual_variant_calc
# ===================================================================

def test_estimate_excludes_fuel_and_late_but_settlement_adds_them(api):
    """PRD §3.5: "The quote is forward-looking and assumes a full-tank return, so it
    folds in no fuel, late, or damage charges."
    PRD §3.9: "The `rental_charge_cents` line is carried over verbatim from the
    reservation's `estimated_total_cents`; it is not recomputed against actual return
    time, because lateness is billed separately."

    Design: Difficulty/dual_variant_calc/reservation_estimate_vs_final_diverge_on_fuel_and_late
    """
    bundle = setup_checked_out_reservation(
        trail_overrides={"name": "Ridge", "required_class": "UTILITY", "max_riders": 20},
        unit_overrides={"unit_class": "UTILITY", "daily_rate_cents": 8000,
                        "deposit_cents": 30000, "tank_capacity_liters": 40},
        departure_overrides={"starts_at": "2026-12-01T09:00:00Z", "ends_at": "2026-12-01T17:00:00Z",
                             "required_guide_class": "UTILITY", "capacity_riders": 20},
        member_overrides={"membership_tier": "SEASON", "membership_expires_at": "2027-04-01T00:00:00Z"},
        guide_overrides={"max_class": "UTILITY"},
        with_helmet=True, with_suit=True,
        depart_clock="2026-12-01T09:30:00Z")

    res = read_reservation(bundle["reservation"]["id"])
    assert res["estimated_total_cents"] == 15345, "estimate excludes fuel/late"

    set_clock("2026-12-01T18:30:00Z")  # 90 min after ends_at
    settle = validate_success(
        api.return_reservation(bundle["reservation"]["id"], {"fuel_return_fraction": 0.70}, DISPATCH), 200)
    assert_settlement(settle)
    assert settle["rental_charge_cents"] == 15345
    assert settle["fuel_charge_cents"] == 1800
    assert settle["late_charge_cents"] == 2500
    assert settle["deposit_applied_cents"] == 19645
    assert settle["refund_cents"] == 10355
    assert settle["net_charge_cents"] == 0
    assert_settlement_reconciles(settle)


def test_premier_zero_strike_deposit_waived_vs_standard_full_deposit(api):
    """PRD §3.8: "a member whose `membership_tier` is `PREMIER`, whose benefits are
    active at confirmation (by the same active test used for the discount in §3.5),
    and whose `lifetime_damage_strikes` count is exactly zero has the deposit waived
    to zero, carrying the deposit risk personally."

    Design: Difficulty/dual_variant_calc/member_deposit_hold_premier_waived_vs_standard_diverge
    """
    bundle = setup_confirmed_reservation(
        trail_overrides={"name": "Flat", "required_class": "TRAIL", "max_riders": 10},
        unit_overrides={"unit_class": "TRAIL", "daily_rate_cents": 5000,
                        "deposit_cents": 30000, "tank_capacity_liters": 30},
        departure_overrides={"starts_at": "2026-12-05T09:00:00Z", "ends_at": "2026-12-05T12:00:00Z",
                             "required_guide_class": "TRAIL", "capacity_riders": 10},
        member_overrides={"membership_tier": "PREMIER", "membership_expires_at": "2027-04-01T00:00:00Z",
                          "date_of_birth": "1985-03-03"})

    res = read_reservation(bundle["reservation"]["id"])
    assert res["deposit_hold_cents"] == 0, "premier zero-strike deposit waived to 0"
    assert res["settlement_status"] == "HELD"

    member = read_member(bundle["member"]["id"])
    assert member["deposit_hold_cents"] == 0


# ===================================================================
# Rule combinatorial_formula
# ===================================================================

def test_quote_expired_season_membership_zeroes_discount(api):
    """PRD §3.5: "Benefits are active exactly when the `membership_tier` is `SEASON`
    or `PREMIER` and, additionally, either `membership_expires_at` is null or
    `membership_expires_at` is strictly later than the logical clock now."
    PRD §3.5: "a `NONE` member, or any member whose benefits have lapsed, takes a
    zero discount."

    Design: Difficulty/combinatorial_formula/quote_membership_tiered_nonlinear_mode_a
    """
    trail = create_trail(name="Peak", required_class="MOUNTAIN", max_riders=8)
    unit = create_unit(unit_class="MOUNTAIN", daily_rate_cents=12000,
                       deposit_cents=40000, tank_capacity_liters=50)
    helmet = create_gear(kind="HELMET", size_code="M", replacement_cost_cents=12000)
    suit = create_gear(kind="SUIT", size_code="L", replacement_cost_cents=20000)
    dep = create_departure(trail["id"], starts_at="2026-12-10T09:00:00Z",
                           ends_at="2026-12-11T09:00:00Z", required_guide_class="MOUNTAIN",
                           capacity_riders=8)
    # SEASON member whose benefits lapsed (expires 2026-05-01) at confirm clock 2026-12-09.
    member = register_signed_member(membership_tier="SEASON",
                                    membership_expires_at="2026-05-01T00:00:00Z",
                                    date_of_birth="1988-01-01")
    train_member(member["id"], "BASIC")
    train_member(member["id"], "ADVANCED")
    set_clock("2026-12-09T08:00:00Z")
    res = create_and_confirm_reservation(member, dep["id"], unit["id"],
                                         helmet_id=helmet["id"], suit_id=suit["id"],
                                         expected_version=dep["version"])
    # gross = 12000*1 + 9000(MOUNTAIN tour) + 1525*2 = 24050; lapsed SEASON -> discount 0
    assert res["estimated_total_cents"] == 24050
    assert res["reservation_status"] == "CONFIRMED"


def test_quote_discount_rounded_once_on_combined_gross(api):
    """PRD §3.5: "the discount is computed once against the combined gross — gross
    multiplied by the discount percentage, rounded half-up to whole cents a single
    time — and that one rounded discount is then subtracted from the gross.
    Discounting each line separately and rounding each before summing is incorrect
    and may differ by a cent."

    Design: Difficulty/combinatorial_formula/quote_discount_rounding_order_pinned_mode_b
    """
    bundle = setup_confirmed_reservation(
        trail_overrides={"name": "Mid", "required_class": "UTILITY", "max_riders": 10},
        unit_overrides={"unit_class": "UTILITY", "daily_rate_cents": 4525,
                        "deposit_cents": 20000, "tank_capacity_liters": 30},
        departure_overrides={"starts_at": "2026-12-12T09:00:00Z", "ends_at": "2026-12-12T15:00:00Z",
                             "required_guide_class": "UTILITY", "capacity_riders": 10},
        member_overrides={"membership_tier": "SEASON", "membership_expires_at": "2027-04-01T00:00:00Z"},
        with_helmet=True, with_suit=False)
    # gross = 4525 + 6000 + 1525 = 12050; round_half_up(1205.0)=1205; total = 10845
    res = read_reservation(bundle["reservation"]["id"])
    assert res["estimated_total_cents"] == 10845


def test_settlement_waterfall_pinned_eval_order(api):
    """PRD §3.9: "the deposit consumed, `deposit_applied_cents`, is the smaller of the
    held `deposit_hold_cents` and the total charges. The amount returned to the member,
    `refund_cents`, is the held deposit minus the deposit applied. The amount charged
    beyond the deposit, `net_charge_cents`, is the total charges minus the held deposit,
    but never less than zero."

    Design: Difficulty/combinatorial_formula/settlement_waterfall_pinned_eval_order_mode_c
    """
    bundle = setup_checked_out_reservation(
        trail_overrides={"name": "Ridge2", "required_class": "UTILITY", "max_riders": 20},
        unit_overrides={"unit_class": "UTILITY", "daily_rate_cents": 8000,
                        "deposit_cents": 30000, "tank_capacity_liters": 40},
        departure_overrides={"starts_at": "2026-12-15T09:00:00Z", "ends_at": "2026-12-15T17:00:00Z",
                             "required_guide_class": "UTILITY", "capacity_riders": 20},
        member_overrides={"membership_tier": "SEASON", "membership_expires_at": "2027-04-01T00:00:00Z"},
        guide_overrides={"max_class": "UTILITY"},
        with_helmet=True, with_suit=True,
        depart_clock="2026-12-15T09:30:00Z")
    set_clock("2026-12-15T19:00:00Z")  # 120 min late
    settle = validate_success(
        api.return_reservation(bundle["reservation"]["id"],
                               {"fuel_return_fraction": 0.70, "damage_assessed_cents": 6000},
                               DISPATCH), 200)
    # rental 15345, fuel 1800, late 5000 (120-30=90 -> ceil(90/60)=2 blocks *2500), damage 6000
    # total = 28145 < deposit 30000 -> applied 28145, refund 1855, net 0
    assert settle["rental_charge_cents"] == 15345
    assert settle["fuel_charge_cents"] == 1800
    assert settle["late_charge_cents"] == 5000
    assert settle["damage_assessed_cents"] == 6000
    assert settle["deposit_applied_cents"] == 28145
    assert settle["refund_cents"] == 1855
    assert settle["net_charge_cents"] == 0
    assert_settlement_reconciles(settle)


# ===================================================================
# Rule boundary_precision_check (late-fee grace)
# ===================================================================

def test_late_fee_zero_at_exactly_grace_boundary(api):
    """PRD §3.9: "Lateness within the grace window of 30 minutes inclusive is free,
    so the charge is zero whenever the late minutes are 30 or fewer."

    Design: Difficulty/boundary_precision_check/late_fee_grace_boundary_inclusive_on_return
    """
    bundle = setup_checked_out_reservation(
        trail_overrides={"name": "LateT", "required_class": "TRAIL", "max_riders": 10},
        unit_overrides={"unit_class": "TRAIL", "daily_rate_cents": 5000,
                        "deposit_cents": 25000, "tank_capacity_liters": 30},
        departure_overrides={"starts_at": "2026-12-28T09:00:00Z", "ends_at": "2026-12-28T17:00:00Z",
                             "required_guide_class": "TRAIL", "capacity_riders": 10},
        depart_clock="2026-12-28T09:30:00Z")
    set_clock("2026-12-28T17:30:00Z")  # exactly 30 min late
    settle = validate_success(
        api.return_reservation(bundle["reservation"]["id"], {"fuel_return_fraction": 1.0}, DISPATCH), 200)
    assert settle["late_charge_cents"] == 0
    assert settle["fuel_charge_cents"] == 0


def test_late_fee_charged_one_minute_past_grace(api):
    """PRD §3.9: "Beyond grace, the billable minutes are the late minutes minus the
    30-minute grace, the number of late blocks is those billable minutes divided by
    the 60-minute block length and rounded up so that any started block bills in full,
    and the late charge is that block count multiplied by 2500 cents per block."

    Design: Difficulty/boundary_precision_check/late_fee_grace_boundary_inclusive_on_return
    """
    bundle = setup_checked_out_reservation(
        trail_overrides={"name": "LateT2", "required_class": "TRAIL", "max_riders": 10},
        unit_overrides={"unit_class": "TRAIL", "daily_rate_cents": 5000,
                        "deposit_cents": 25000, "tank_capacity_liters": 30},
        departure_overrides={"starts_at": "2026-12-28T09:00:00Z", "ends_at": "2026-12-28T17:00:00Z",
                             "required_guide_class": "TRAIL", "capacity_riders": 10},
        depart_clock="2026-12-28T09:30:00Z")
    set_clock("2026-12-28T17:31:00Z")  # 31 min late -> 1 billable minute -> 1 block
    settle = validate_success(
        api.return_reservation(bundle["reservation"]["id"], {"fuel_return_fraction": 1.0}, DISPATCH), 200)
    assert settle["late_charge_cents"] == 2500


# ===================================================================
# Second tests per instance (≥2 coverage)
# ===================================================================

def test_settlement_fuel_charge_billed_below_full_tank_threshold(api):
    """PRD §3.9: "there is no charge when the returned fuel fraction is at or above the
    full-tank threshold of 0.95, so a shortfall is billed only when `fuel_return_fraction`
    is strictly below 0.95. When it is below, the shortfall in liters is the difference
    between 0.95 and the returned fraction, multiplied by the unit's `tank_capacity_liters`,
    and the charge is that liter shortfall multiplied by the fuel price of 180 cents per
    liter, rounded half-up to whole cents."

    Design: Difficulty/dual_variant_calc/reservation_estimate_vs_final_diverge_on_fuel_and_late
    """
    bundle = setup_checked_out_reservation(
        trail_overrides={"name": "Ridge3", "required_class": "UTILITY", "max_riders": 20},
        unit_overrides={"unit_class": "UTILITY", "daily_rate_cents": 8000,
                        "deposit_cents": 30000, "tank_capacity_liters": 40},
        departure_overrides={"starts_at": "2026-12-01T09:00:00Z", "ends_at": "2026-12-01T17:00:00Z",
                             "required_guide_class": "UTILITY", "capacity_riders": 20},
        member_overrides={"membership_tier": "SEASON", "membership_expires_at": "2027-04-01T00:00:00Z"},
        guide_overrides={"max_class": "UTILITY"},
        with_helmet=True, with_suit=True,
        depart_clock="2026-12-01T09:30:00Z")
    set_clock("2026-12-01T18:30:00Z")  # 90 min late
    settle = validate_success(
        api.return_reservation(bundle["reservation"]["id"], {"fuel_return_fraction": 0.70}, DISPATCH), 200)
    # shortfall = (0.95-0.70)*40 = 10L * 180 = 1800
    assert settle["fuel_charge_cents"] == 1800


def test_standard_member_holds_full_unit_deposit(api):
    """PRD §3.8: "Any member who is not premier, or whose benefits have lapsed, or who
    carries at least one damage strike, holds the full `deposit_cents`."

    Design: Difficulty/dual_variant_calc/member_deposit_hold_premier_waived_vs_standard_diverge
    """
    bundle = setup_confirmed_reservation(
        trail_overrides={"name": "Flat2", "required_class": "TRAIL", "max_riders": 10},
        unit_overrides={"unit_class": "TRAIL", "daily_rate_cents": 5000,
                        "deposit_cents": 30000, "tank_capacity_liters": 30},
        departure_overrides={"starts_at": "2026-12-05T09:00:00Z", "ends_at": "2026-12-05T12:00:00Z",
                             "required_guide_class": "TRAIL", "capacity_riders": 10},
        member_overrides=None)  # NONE-tier standard member
    res = read_reservation(bundle["reservation"]["id"])
    assert res["deposit_hold_cents"] == 30000, "standard member holds full Unit.deposit_cents"
    assert read_member(bundle["member"]["id"])["deposit_hold_cents"] == 30000


def test_quote_none_member_takes_zero_discount(api):
    """PRD §3.5: "a `NONE` member, or any member whose benefits have lapsed, takes a zero
    discount."

    Design: Difficulty/combinatorial_formula/quote_membership_tiered_nonlinear_mode_a
    """
    # NONE-tier member on a UTILITY route (no training gate): gross with no discount.
    bundle = setup_confirmed_reservation(
        trail_overrides={"name": "PeakNone", "required_class": "UTILITY", "max_riders": 8},
        unit_overrides={"unit_class": "UTILITY", "daily_rate_cents": 12000,
                        "deposit_cents": 40000, "tank_capacity_liters": 50},
        departure_overrides={"starts_at": "2026-12-10T09:00:00Z", "ends_at": "2026-12-11T09:00:00Z",
                             "required_guide_class": "UTILITY", "capacity_riders": 8},
        member_overrides=None, with_helmet=True, with_suit=True)
    res = read_reservation(bundle["reservation"]["id"])
    # gross = 12000*1 + 6000(UTILITY tour) + 1525*2 = 21050; NONE -> discount 0 -> total 21050
    assert res["estimated_total_cents"] == 21050


def test_quote_premier_discount_combined_gross_rounding(api):
    """PRD §3.5: "When active, the discount percentage is 10 percent for a `SEASON`
    member and 20 percent for a `PREMIER` member".
    PRD §3.5: "the discount is computed once against the combined gross — gross
    multiplied by the discount percentage, rounded half-up to whole cents a single
    time — and that one rounded discount is then subtracted from the gross."

    Design: Difficulty/combinatorial_formula/quote_discount_rounding_order_pinned_mode_b
    """
    bundle = setup_confirmed_reservation(
        trail_overrides={"name": "Mid2", "required_class": "UTILITY", "max_riders": 10},
        unit_overrides={"unit_class": "UTILITY", "daily_rate_cents": 4525,
                        "deposit_cents": 20000, "tank_capacity_liters": 30},
        departure_overrides={"starts_at": "2026-12-12T09:00:00Z", "ends_at": "2026-12-12T15:00:00Z",
                             "required_guide_class": "UTILITY", "capacity_riders": 10},
        member_overrides={"membership_tier": "PREMIER", "membership_expires_at": "2027-04-01T00:00:00Z"},
        with_helmet=True, with_suit=False)
    # gross = 4525 + 6000 + 1525 = 12050; PREMIER 0.20 -> round_half_up(2410.0)=2410; total 9640
    res = read_reservation(bundle["reservation"]["id"])
    assert res["estimated_total_cents"] == 9640


def test_settlement_net_charge_when_charges_exceed_deposit(api):
    """PRD §3.9: "The amount charged beyond the deposit, `net_charge_cents`, is the total
    charges minus the held deposit, but never less than zero."

    Design: Difficulty/combinatorial_formula/settlement_waterfall_pinned_eval_order_mode_c
    """
    bundle = setup_checked_out_reservation(
        trail_overrides={"name": "Ridge3wf", "required_class": "UTILITY", "max_riders": 20},
        unit_overrides={"unit_class": "UTILITY", "daily_rate_cents": 8000,
                        "deposit_cents": 30000, "tank_capacity_liters": 40},
        departure_overrides={"starts_at": "2026-12-15T09:00:00Z", "ends_at": "2026-12-15T17:00:00Z",
                             "required_guide_class": "UTILITY", "capacity_riders": 20},
        member_overrides={"membership_tier": "SEASON", "membership_expires_at": "2027-04-01T00:00:00Z"},
        guide_overrides={"max_class": "UTILITY"},
        with_helmet=True, with_suit=True,
        depart_clock="2026-12-15T09:30:00Z")
    # On-time return, large damage so total exceeds the 30000 deposit.
    set_clock("2026-12-15T17:00:00Z")
    settle = validate_success(
        api.return_reservation(bundle["reservation"]["id"],
                               {"fuel_return_fraction": 1.0, "damage_assessed_cents": 50000},
                               DISPATCH), 200)
    # rental 15345 + damage 50000 = 65345 total; deposit 30000 fully applied; refund 0; net 35345
    assert settle["rental_charge_cents"] == 15345
    assert settle["damage_assessed_cents"] == 50000
    assert settle["deposit_applied_cents"] == 30000
    assert settle["refund_cents"] == 0
    assert settle["net_charge_cents"] == 35345
    assert_settlement_reconciles(settle)
