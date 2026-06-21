"""Pricing calculations: add-on quote/settled dual variant, tiered ammo,
per-line-then-sum invoice, field fee, deposit settlement.

Queue A (Difficulty) — dual_variant_calc, combinatorial_formula,
boundary_precision_check.
Queue B (Corner) — calculations.
"""
import pytest
from test_helpers import (
    validate_success,
    create_add_on_order_payload, create_party_package_payload,
    create_booking_payload,
    TEST_USERS,
    create_arena, create_field, setup_arena_and_field, create_held_booking,
    create_confirmed_booking, create_package, create_equipment,
    reserve_rental, check_in_booking, complete_booking, create_referee,
    assign_referee,
)

AM = TEST_USERS["arena_manager_headers"]
FD = TEST_USERS["front_desk_headers"]
FM = TEST_USERS["field_marshal_headers"]


# ─────────────────────────────────────────────────────────────────────────────
# Queue A — dual_variant_calc: add-on quote vs settled diverge (two tests)
# ─────────────────────────────────────────────────────────────────────────────
def _setup_addon_dual_variant():
    """Arena + LASER_TAG field + discount package + CONFIRMED party-10 booking +
    QUOTED add-on (ammo 2200, co2 2). Returns (arena, booking, addon)."""
    arena, field = setup_arena_and_field(
        clock="2026-06-15T09:00:00Z", field_overrides={"capacity_max": 12}
    )
    pkg = create_package(
        arena["id"], name="Blitz", included_players=10, extra_player_fee_cents=500,
        base_fee_cents=9000, included_ammo_balls=200, discount_pct=0.20, active=True,
    )
    booking = create_confirmed_booking(
        arena, field, booking_type="WALK_IN", party_size=10,
        window_start="2026-06-15T09:00:00Z", window_end="2026-06-15T11:00:00Z",
        package_id=pkg["id"],
    )
    addon = validate_success(
        api_create_addon(arena["id"], booking["id"]), 201
    )
    return arena, booking, addon


def api_create_addon(arena_id, booking_id):
    from test_helpers import api_client
    return api_client.create_add_on_order(
        create_add_on_order_payload(arena_id, booking_id, ammo_balls=2200, co2_tanks=2, misc_cents=0), FD
    )


def test_addon_quote_total_set_at_creation(api):
    """PRD §3.5: "The **quote variant** computed at order creation applies no package
    context: it bills every ball ordered through the tier schedule, adds the CO2 and
    miscellaneous charges, and stores that exact integer-cent sum as `quote_total_cents`."

    Design: Difficulty/dual_variant_calc/addon_quote_vs_settled_diverge_on_addonorder
    """
    arena, booking, addon = _setup_addon_dual_variant()
    assert addon["quote_total_cents"] == 19600, \
        f"quote for ammo 2200 + 2 CO2 must be 19600, got {addon['quote_total_cents']}"


def test_addon_settled_total_differs_from_quote_at_completion(api):
    """PRD §3.5: "First, the package's `included_ammo_balls` allowance (zero when the
    booking has no package) is consumed off the top: the billable ball count is the
    ordered `ammo_balls` minus the included allowance, floored at zero. ... Then a
    discount is computed as the package's `discount_pct` times the metered ammunition
    cost only (the discount never touches CO2 or miscellaneous charges), rounded half up
    to the nearest cent. The discount is subtracted from the gross to yield
    `settled_total_cents`."

    Design: Difficulty/dual_variant_calc/addon_quote_vs_settled_diverge_on_addonorder
    """
    arena, booking, addon = _setup_addon_dual_variant()
    check_in_booking(booking["id"], 10)
    complete_booking(booking["id"])
    settled = validate_success(api.get_add_on_order(addon["id"], FM), 200)
    assert settled["status"] == "SETTLED"
    assert settled["settled_total_cents"] == 15000, \
        f"settled total must be 15000, got {settled['settled_total_cents']}"
    assert settled["quote_total_cents"] != settled["settled_total_cents"], \
        "quote and settled totals must diverge for this discounted booking"


# ─────────────────────────────────────────────────────────────────────────────
# Queue A — combinatorial_formula: tiered ammo (two tests)
# ─────────────────────────────────────────────────────────────────────────────
def test_addon_tiered_ammo_quote_nonlinear(api):
    """PRD §3.5: "The first 500 balls are billed at 10 cents each; the next 1500 balls
    (those from the 501st through the 2000th) at 8 cents each; and every ball beyond
    2000 at 6 cents each. ... The ammunition cost is the tier-one quantity times 10
    cents plus the tier-two quantity times 8 cents plus the tier-three quantity times 6
    cents. Each CO2 tank adds 700 cents."

    Design: Difficulty/combinatorial_formula/addon_tiered_ammo_min_max_nonlinear
    """
    arena, field = setup_arena_and_field(
        clock="2026-06-15T09:00:00Z", field_overrides={"capacity_max": 20}
    )
    booking = create_held_booking(
        arena["id"], field["id"], booking_type="WALK_IN", party_size=5,
        window_start="2026-06-15T09:00:00Z", window_end="2026-06-15T10:00:00Z",
    )
    addon = validate_success(
        api.create_add_on_order(
            create_add_on_order_payload(arena["id"], booking["id"], ammo_balls=2200, co2_tanks=2, misc_cents=0), FD
        ), 201
    )
    assert addon["quote_total_cents"] == 19600, \
        f"tiered quote for 2200 balls + 2 CO2 must be 19600, got {addon['quote_total_cents']}"


def test_addon_tiered_ammo_tier3_remainder_beyond_2000(api):
    """PRD §3.5: "the tier-one quantity is the ball count capped at 500; the tier-two
    quantity is whatever remains after removing the first 500, capped at 1500; and the
    tier-three quantity is whatever remains beyond 2000. The ammunition cost is the
    tier-one quantity times 10 cents plus the tier-two quantity times 8 cents plus the
    tier-three quantity times 6 cents."

    Design: Difficulty/combinatorial_formula/addon_tiered_ammo_min_max_nonlinear
    """
    arena, field = setup_arena_and_field(
        clock="2026-06-15T09:00:00Z", field_overrides={"capacity_max": 20}
    )
    booking = create_held_booking(
        arena["id"], field["id"], booking_type="WALK_IN", party_size=5,
        window_start="2026-06-15T09:00:00Z", window_end="2026-06-15T10:00:00Z",
    )
    # 2500 balls -> 500*10 + 1500*8 + 500*6 = 5000 + 12000 + 3000 = 20000; no CO2/misc
    addon = validate_success(
        api.create_add_on_order(
            create_add_on_order_payload(arena["id"], booking["id"], ammo_balls=2500, co2_tanks=0, misc_cents=0), FD
        ), 201
    )
    assert addon["quote_total_cents"] == 20000, \
        f"2500 balls across all three tiers must quote 20000, got {addon['quote_total_cents']}"


def test_invoice_round_per_line_then_sum_pins_order(api):
    """PRD §3.8: "Each line is taxed independently at the 8.25 percent sales rate: a
    line's taxed value is the line plus the line times 0.0825 rounded half up to the
    nearest cent. The `invoice_total_cents` is then the sum of the three taxed lines.
    The order is fixed — round each line's tax to a whole cent first, then add the three
    taxed lines together. Summing the three raw lines and taxing the total once is
    explicitly not the algorithm and can differ by a cent or two."

    Design: Difficulty/combinatorial_formula/invoice_round_per_line_then_sum_pins_order
    """
    arena = create_arena(clock="2026-06-15T09:00:00Z", marker_pool_total=1)
    field = create_field(arena["id"], name="PB2", game_mode="PAINTBALL", capacity_max=10)
    pkg = create_package(
        arena["id"], name="Pkg10", included_players=10, extra_player_fee_cents=500,
        base_fee_cents=9000, included_ammo_balls=200, discount_pct=0.20, active=True,
    )
    unit = create_equipment(arena["id"], unit_type="MARKER", asset_tag="M-4", deposit_cents=5000)
    referee = create_referee(arena["id"], name="RefPB", certified_paintball=True)
    booking = create_confirmed_booking(
        arena, field, booking_type="WALK_IN", party_size=10,
        window_start="2026-06-15T09:00:00Z", window_end="2026-06-15T11:00:00Z",
        package_id=pkg["id"],
    )
    assign_referee(arena["id"], booking["id"], referee["id"])
    rental = reserve_rental(arena["id"], booking["id"], unit["id"])
    addon = validate_success(
        api.create_add_on_order(
            create_add_on_order_payload(arena["id"], booking["id"], ammo_balls=2200, co2_tanks=2, misc_cents=0), FD
        ), 201
    )
    check_in_booking(booking["id"], 10)
    validate_success(api.return_rental(rental["id"], {"damage_fee_cents": 1200}, FM), 200)
    completed = validate_success(api.complete_booking(booking["id"], FM), 200)

    assert completed["field_fee_cents"] == 9000, \
        f"field_fee must be 9000, got {completed['field_fee_cents']}"
    settled = validate_success(api.get_add_on_order(addon["id"], FM), 200)
    assert settled["settled_total_cents"] == 15000
    final_rental = validate_success(api.get_rental(rental["id"], FM), 200)
    assert final_rental["deposit_forfeit_cents"] == 1200
    assert completed["invoice_total_cents"] == 27280, \
        f"per-line-taxed invoice must be 27280, got {completed['invoice_total_cents']}"


def test_invoice_field_only_line_taxed_half_up(api):
    """PRD §3.8: "Each line is taxed independently at the 8.25 percent sales rate: a
    line's taxed value is the line plus the line times 0.0825 rounded half up to the
    nearest cent. The `invoice_total_cents` is then the sum of the three taxed lines.
    The order is fixed — round each line's tax to a whole cent first, then add the three
    taxed lines together."

    Design: Difficulty/combinatorial_formula/invoice_round_per_line_then_sum_pins_order
    """
    # A package booking with no add-ons and no rentals: only the field line is taxed.
    arena, field = setup_arena_and_field(
        clock="2026-06-15T09:00:00Z", field_overrides={"capacity_max": 12}
    )
    pkg = create_package(
        arena["id"], name="FieldOnly", included_players=10, extra_player_fee_cents=500,
        base_fee_cents=9000, active=True,
    )
    booking = create_confirmed_booking(
        arena, field, booking_type="WALK_IN", party_size=10,
        window_start="2026-06-15T09:00:00Z", window_end="2026-06-15T11:00:00Z",
        package_id=pkg["id"],
    )
    check_in_booking(booking["id"], 10)
    completed = validate_success(api.complete_booking(booking["id"], FM), 200)
    # field 9000 -> tax round_half_up(742.5) = 743 -> taxed 9743; addon/forfeit lines 0.
    assert completed["invoice_total_cents"] == 9743, \
        f"field-only invoice must be 9743 (9000 + round-half-up 743), got {completed['invoice_total_cents']}"


# ─────────────────────────────────────────────────────────────────────────────
# Queue A — boundary_precision_check: ammo tier boundary 500 vs 501 (two tests)
# ─────────────────────────────────────────────────────────────────────────────
def test_ammo_tier_boundary_exactly_500_billed_at_tier1(api):
    """PRD §3.5: "the tier-one quantity is the ball count capped at 500; the tier-two
    quantity is whatever remains after removing the first 500, capped at 1500; and the
    tier-three quantity is whatever remains beyond 2000. The ammunition cost is the
    tier-one quantity times 10 cents plus the tier-two quantity times 8 cents plus the
    tier-three quantity times 6 cents."

    Design: Difficulty/boundary_precision_check/ammo_tier_boundary_500_vs_501
    """
    arena, field = setup_arena_and_field(clock="2026-06-15T09:00:00Z")
    booking = create_held_booking(
        arena["id"], field["id"], booking_type="WALK_IN", party_size=4,
        window_start="2026-06-15T09:00:00Z", window_end="2026-06-15T10:00:00Z",
    )
    addon = validate_success(
        api.create_add_on_order(
            create_add_on_order_payload(arena["id"], booking["id"], ammo_balls=500, co2_tanks=0, misc_cents=0), FD
        ), 201
    )
    assert addon["quote_total_cents"] == 5000, \
        f"500 balls (tier1 only) must quote 5000, got {addon['quote_total_cents']}"


def test_ammo_tier_boundary_501_crosses_into_tier2(api):
    """PRD §3.5: "The first 500 balls are billed at 10 cents each; the next 1500 balls
    (those from the 501st through the 2000th) at 8 cents each; and every ball beyond
    2000 at 6 cents each."

    Design: Difficulty/boundary_precision_check/ammo_tier_boundary_500_vs_501
    """
    arena, field = setup_arena_and_field(clock="2026-06-15T09:00:00Z")
    booking = create_held_booking(
        arena["id"], field["id"], booking_type="WALK_IN", party_size=4,
        window_start="2026-06-15T09:00:00Z", window_end="2026-06-15T10:00:00Z",
    )
    addon = validate_success(
        api.create_add_on_order(
            create_add_on_order_payload(arena["id"], booking["id"], ammo_balls=501, co2_tanks=0, misc_cents=0), FD
        ), 201
    )
    assert addon["quote_total_cents"] == 5008, \
        f"501 balls = 5000 + 1*8 must quote 5008, got {addon['quote_total_cents']}"


# ─────────────────────────────────────────────────────────────────────────────
# Queue B — calculations: field fee, addon co2+misc, deposit full refund
# ─────────────────────────────────────────────────────────────────────────────
def test_field_fee_zero_for_a_la_carte_booking(api):
    """PRD §3.3: "If the booking has no `package_id`, `field_fee_cents` is zero."

    Design: Corner/calculations/field_fee_zero_for_a_la_carte_booking
    """
    arena, field = setup_arena_and_field(clock="2026-06-15T09:00:00Z")
    confirmed = create_confirmed_booking(
        arena, field, booking_type="WALK_IN", party_size=4,
        window_start="2026-06-15T09:00:00Z", window_end="2026-06-15T10:00:00Z",
    )
    assert confirmed["field_fee_cents"] == 0, \
        f"a la carte booking field_fee must be 0, got {confirmed['field_fee_cents']}"


def test_field_fee_extra_player_surcharge(api):
    """PRD §3.3: "the number of extra players is the booking's `party_size` minus the
    package's `included_players`, floored at zero so a party that fits within the
    included headcount contributes no extras; the `field_fee_cents` is then the
    package's `base_fee_cents` plus that extra-player count multiplied by the package's
    `extra_player_fee_cents`."

    Design: Corner/calculations/field_fee_extra_player_surcharge
    """
    arena, field = setup_arena_and_field(
        clock="2026-06-15T09:00:00Z", field_overrides={"capacity_max": 12}
    )
    pkg = create_package(
        arena["id"], name="P8", included_players=8, extra_player_fee_cents=500,
        base_fee_cents=9000, active=True,
    )
    confirmed = create_confirmed_booking(
        arena, field, booking_type="WALK_IN", party_size=10,
        window_start="2026-06-15T09:00:00Z", window_end="2026-06-15T10:00:00Z",
        package_id=pkg["id"],
    )
    assert confirmed["field_fee_cents"] == 10000, \
        f"9000 + 2*500 must be 10000, got {confirmed['field_fee_cents']}"


def test_addon_quote_co2_and_misc_only(api):
    """PRD §3.5: "Each CO2 tank adds 700 cents. The miscellaneous charge is added as-is."

    Design: Corner/calculations/addon_quote_co2_and_misc_only
    """
    arena, field = setup_arena_and_field(clock="2026-06-15T09:00:00Z")
    booking = create_held_booking(
        arena["id"], field["id"], booking_type="WALK_IN", party_size=4,
        window_start="2026-06-15T09:00:00Z", window_end="2026-06-15T10:00:00Z",
    )
    addon = validate_success(
        api.create_add_on_order(
            create_add_on_order_payload(arena["id"], booking["id"], ammo_balls=0, co2_tanks=3, misc_cents=250), FD
        ), 201
    )
    assert addon["quote_total_cents"] == 2350, \
        f"3*700 + 250 must be 2350, got {addon['quote_total_cents']}"


def test_deposit_full_refund_when_no_damage(api):
    """PRD §3.4: "the unit returns to `AVAILABLE` when `damage_fee_cents` is zero, but
    moves to `MAINTENANCE` when any damage fee was charged ..."
    PRD §3.4: "the refunded amount, `deposit_refund_cents`, is the held deposit minus
    that forfeit, which is never negative. The two always sum back exactly to
    `deposit_hold_cents`."

    Design: Corner/calculations/deposit_full_refund_when_no_damage
    """
    arena = create_arena(clock="2026-06-15T09:00:00Z", marker_pool_total=1)
    field = create_field(arena["id"], name="Fc4", game_mode="LASER_TAG", capacity_max=8)
    unit = create_equipment(arena["id"], unit_type="MARKER", asset_tag="M-c4", deposit_cents=4000)
    booking = create_confirmed_booking(
        arena, field, booking_type="WALK_IN", party_size=4,
        window_start="2026-06-15T09:00:00Z", window_end="2026-06-15T10:00:00Z",
    )
    rental = reserve_rental(arena["id"], booking["id"], unit["id"])
    check_in_booking(booking["id"], 4)
    returned = validate_success(api.return_rental(rental["id"], {}, FM), 200)
    assert returned["deposit_refund_cents"] == 4000, \
        f"full refund must be 4000, got {returned['deposit_refund_cents']}"
    assert returned["deposit_forfeit_cents"] == 0
    unit_after = validate_success(api.get_equipment_unit(unit["id"], AM), 200)
    assert unit_after["status"] == "AVAILABLE", \
        f"undamaged return must leave unit AVAILABLE, got {unit_after['status']}"
