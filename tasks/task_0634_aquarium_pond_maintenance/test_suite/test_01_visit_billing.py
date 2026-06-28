"""Visit billing: tiered pricing, dual ROUTINE/EMERGENCY variants, combinatorial
inputs, discount-then-surcharge order, and the included-minutes boundary.

All amounts are integer cents per the PRD's monetary-precision rules.
"""
from test_helpers import (
    validate_success,
    make_field_tech_headers,
    create_started_visit,
    create_dispatched_emergency,
    create_completed_visit,
    TEST_USERS,
)

AM = TEST_USERS["account_manager_headers"]
DISP = TEST_USERS["dispatcher_headers"]


def test_routine_and_emergency_visit_totals_diverge_by_surcharge(api):
    """PRD §3.4: "For an EMERGENCY visit an emergency surcharge of 25% of the
    after-discount amount, rounded half-up to whole cents, is added on top; for
    identical labor and lines this makes an emergency visit's total strictly
    higher than the routine equivalent."

    Design: Difficulty/dual_variant_calc/visit_billing_routine_vs_emergency_diverge
    """
    tech_headers = make_field_tech_headers("tech-1")

    # ROUTINE visit on a BASIC system, labor 75 min, no consumable lines.
    routine = create_started_visit(service_tier="BASIC", tech_user_id="tech-1",
                                   nominal_volume_l=200, substrate_displacement_pct=0.10,
                                   scheduled_start="2026-02-02T09:00:00Z",
                                   scheduled_end="2026-02-02T10:00:00Z")
    routine_visit = validate_success(
        api.complete_visit(routine["visit"]["id"], {"labor_minutes": 75}, tech_headers))
    routine_total = routine_visit["total_cents"]
    assert routine_total == 12000, f"Expected routine total 12000, got {routine_total}"

    # EMERGENCY visit on a BASIC system, same labor 75 min, no consumable lines.
    em = create_dispatched_emergency(service_tier="BASIC", tech_user_id="tech-2",
                                     nominal_volume_l=200,
                                     reported_at="2026-02-03T08:00:00Z",
                                     scheduled_start="2026-02-03T09:00:00Z",
                                     scheduled_end="2026-02-03T10:00:00Z")
    em_tech_headers = make_field_tech_headers("tech-2")
    validate_success(api.start_visit(em["dispatched_visit_id"], em_tech_headers))
    em_visit = validate_success(
        api.complete_visit(em["dispatched_visit_id"], {"labor_minutes": 75}, em_tech_headers))
    emergency_total = em_visit["total_cents"]
    assert emergency_total == 15000, f"Expected emergency total 15000, got {emergency_total}"

    assert emergency_total - routine_total == 3000, (
        f"Expected a 3000-cent surcharge divergence, got {emergency_total - routine_total}")


def test_routine_visit_total_matches_tier_base_plus_blocks(api):
    """PRD §3.4: "The base charge is the tier's base: 6000 cents for BASIC, 9000
    cents for PLUS, and 13000 cents for PREMIUM. Each tier includes a block of
    labor at no extra charge: 30 minutes for BASIC ... That overage is then
    divided into 15-minute blocks, rounding up so that any partial block bills as
    a whole block, and each block costs 2000 cents".

    BASIC, labor 75: 45 overage -> 3 blocks @2000 = 6000; base 6000; no discount;
    ROUTINE total 12000.

    Design: Difficulty/dual_variant_calc/visit_billing_routine_vs_emergency_diverge
    """
    tech_headers = make_field_tech_headers("tech-1")
    routine = create_started_visit(service_tier="BASIC", tech_user_id="tech-1",
                                   nominal_volume_l=200,
                                   scheduled_start="2026-02-02T09:00:00Z",
                                   scheduled_end="2026-02-02T10:00:00Z")
    visit = validate_success(
        api.complete_visit(routine["visit"]["id"], {"labor_minutes": 75}, tech_headers))
    assert visit["total_cents"] == 12000, f"Expected 12000, got {visit['total_cents']}"


def test_visit_billing_combines_base_block_and_consumable_line(api):
    """PRD §3.4: "Add the base, the labor overage, and the consumable total to
    get the subtotal. The plan discount is the subtotal multiplied by the tier's
    discount rate — 0% for BASIC, 10% for PLUS, and 15% for PREMIUM — rounded
    half-up to whole cents, and is subtracted from the subtotal to give the
    after-discount amount."

    PLUS tier, labor 60 (15 over the 45 included = 1 block @2000), one line
    qty 1 @2500: (9000 + 2000 + 2500) = 13500 subtotal, 10% discount 1350 ->
    after-discount 12150.

    Design: Difficulty/combinatorial_formula/visit_billing_nonlinear_multi_input_mode_a
    """
    tech_headers = make_field_tech_headers("tech-1")
    base = create_started_visit(service_tier="PLUS", tech_user_id="tech-1",
                                nominal_volume_l=250,
                                scheduled_start="2026-02-04T09:00:00Z",
                                scheduled_end="2026-02-04T10:30:00Z")
    visit = validate_success(api.complete_visit(
        base["visit"]["id"],
        {"labor_minutes": 60, "consumable_lines": [{"qty": 1, "unit_price_cents": 2500}]},
        tech_headers))
    assert visit["total_cents"] == 12150, f"Expected 12150, got {visit['total_cents']}"


def test_plus_tier_discount_lowers_total_below_subtotal(api):
    """PRD §3.4: "The plan discount is the subtotal multiplied by the tier's
    discount rate — 0% for BASIC, 10% for PLUS, and 15% for PREMIUM — rounded
    half-up to whole cents, and is subtracted from the subtotal to give the
    after-discount amount. For a ROUTINE visit there is no further charge and
    total_cents equals the after-discount amount."

    PLUS tier, labor 60, one line @2500: subtotal 13500, 10% discount 1350 ->
    after-discount 12150. The 1350 discount is exactly subtotal - total.

    Design: Difficulty/combinatorial_formula/visit_billing_nonlinear_multi_input_mode_a
    """
    tech_headers = make_field_tech_headers("tech-1")
    base = create_started_visit(service_tier="PLUS", tech_user_id="tech-1",
                                nominal_volume_l=250,
                                scheduled_start="2026-02-04T11:00:00Z",
                                scheduled_end="2026-02-04T12:30:00Z")
    visit = validate_success(api.complete_visit(
        base["visit"]["id"],
        {"labor_minutes": 60, "consumable_lines": [{"qty": 1, "unit_price_cents": 2500}]},
        tech_headers))
    # subtotal (13500) minus total (12150) == the 10% discount of 1350.
    assert 13500 - visit["total_cents"] == 1350, (
        f"Expected a 1350-cent PLUS discount, got {13500 - visit['total_cents']}")


def test_visit_billing_discount_taken_before_emergency_surcharge(api):
    """PRD §3.4: "For an EMERGENCY visit an emergency surcharge of 25% of the
    after-discount amount, rounded half-up to whole cents, is added on top".

    PREMIUM tier, labor 90 (30 over the 60 included = 2 blocks @2000 = 4000),
    one line qty 1 @5000, EMERGENCY: subtotal 13000 + 4000 + 5000 = 22000,
    15% discount 3300 -> after-discount 18700, surcharge 25% = 4675 -> 23375.

    Design: Difficulty/combinatorial_formula/visit_billing_discount_then_surcharge_order_mode_c
    """
    em = create_dispatched_emergency(service_tier="PREMIUM", tech_user_id="tech-1",
                                     certified_for_reef=True, system_kind="REEF",
                                     nominal_volume_l=300, severity="CRITICAL",
                                     trip_fee_cents=9000,
                                     reported_at="2026-02-05T08:00:00Z",
                                     scheduled_start="2026-02-05T09:00:00Z",
                                     scheduled_end="2026-02-05T11:00:00Z")
    tech_headers = make_field_tech_headers("tech-1")
    validate_success(api.start_visit(em["dispatched_visit_id"], tech_headers))
    visit = validate_success(api.complete_visit(
        em["dispatched_visit_id"],
        {"labor_minutes": 90, "consumable_lines": [{"qty": 1, "unit_price_cents": 5000}]},
        tech_headers))
    assert visit["total_cents"] == 23375, f"Expected 23375, got {visit['total_cents']}"


def test_premium_emergency_surcharge_is_25pct_of_after_discount(api):
    """PRD §3.4: "For an EMERGENCY visit an emergency surcharge of 25% of the
    after-discount amount, rounded half-up to whole cents, is added on top".

    PREMIUM, labor 90, one line @5000, EMERGENCY: subtotal 22000, 15% discount
    3300 -> after-discount 18700, surcharge 25% of 18700 = 4675 -> total 23375.
    The 4675 surcharge is exactly total - after_discount.

    Design: Difficulty/combinatorial_formula/visit_billing_discount_then_surcharge_order_mode_c
    """
    em = create_dispatched_emergency(service_tier="PREMIUM", tech_user_id="tech-1",
                                     certified_for_reef=True, system_kind="REEF",
                                     nominal_volume_l=300, severity="CRITICAL",
                                     trip_fee_cents=9000,
                                     reported_at="2026-02-05T07:00:00Z",
                                     scheduled_start="2026-02-05T12:00:00Z",
                                     scheduled_end="2026-02-05T14:00:00Z")
    tech_headers = make_field_tech_headers("tech-1")
    validate_success(api.start_visit(em["dispatched_visit_id"], tech_headers))
    visit = validate_success(api.complete_visit(
        em["dispatched_visit_id"],
        {"labor_minutes": 90, "consumable_lines": [{"qty": 1, "unit_price_cents": 5000}]},
        tech_headers))
    # total (23375) minus after-discount (18700) == surcharge 4675.
    assert visit["total_cents"] - 18700 == 4675, (
        f"Expected a 4675-cent emergency surcharge, got {visit['total_cents'] - 18700}")


def test_labor_at_included_minutes_bills_zero_overage_blocks(api):
    """PRD §3.4: "The overage is the recorded labor_minutes minus the tier's
    included minutes, floored at zero so a visit under the allowance has no
    overage. That overage is then divided into 15-minute blocks, rounding up so
    that any partial block bills as a whole block, and each block costs 2000
    cents".

    BASIC includes 30 minutes; labor exactly 30 -> 0 overage blocks -> total 6000.

    Design: Difficulty/boundary_precision_check/labor_included_minutes_boundary_zero_blocks
    """
    base = create_completed_visit(service_tier="BASIC", tech_user_id="tech-1",
                                  labor_minutes=30,
                                  scheduled_start="2026-02-10T09:00:00Z",
                                  scheduled_end="2026-02-10T10:00:00Z")
    assert base["visit"]["total_cents"] == 6000, (
        f"Expected 6000 at labor 30 (== included), got {base['visit']['total_cents']}")


def test_labor_one_minute_over_included_bills_one_block(api):
    """PRD §3.4: "That overage is then divided into 15-minute blocks, rounding up
    so that any partial block bills as a whole block, and each block costs 2000
    cents".

    BASIC includes 30 minutes; labor 31 -> 1-minute overage -> 1 ceil block
    @2000 -> base 6000 + 2000 = 8000.

    Design: Difficulty/boundary_precision_check/labor_included_minutes_boundary_zero_blocks
    """
    base = create_completed_visit(service_tier="BASIC", tech_user_id="tech-1",
                                  labor_minutes=31,
                                  scheduled_start="2026-02-11T09:00:00Z",
                                  scheduled_end="2026-02-11T10:00:00Z")
    assert base["visit"]["total_cents"] == 8000, (
        f"Expected 8000 at labor 31 (1 block), got {base['visit']['total_cents']}")
