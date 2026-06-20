"""Cost-per-acre (provisional vs final, multi-input overhead allocation) and yield
aggregation (graded-only filter, sum-then-round order) — full close lifecycle.

Difficulty queue A: dual_variant_calc (provisional vs final diverge; graded vs
gross-basis yield diverge), combinatorial_formula (three-input overhead
allocation; net-quantity round-then-field-round order pinned).
Corner queue B: calculations (net_quantity moisture adjustment).
"""
from test_helpers import (
    validate_success,
    TEST_USERS,
    make_applicator_headers,
    set_clock, create_parcel, create_draft_plan, create_and_approve_plan,
    create_seed_product, create_input_product, create_restricted_product,
    create_input_lot, create_applicator, create_equipment_asset,
    record_planting, record_harvest, create_graded_lot, create_lot,
    log_application, setup_harvesting_plan,
)

FM = TEST_USERS["farm_manager_headers"]
AG = TEST_USERS["agronomist_headers"]


# ===========================================================================
# Difficulty: dual_variant_calc — cost_per_acre_provisional_vs_final_diverge
# ===========================================================================
def test_cost_per_acre_provisional_vs_final_diverge(api):
    """PRD §3.7: "its numerator is the sum of `budget_input_cost`, `budget_labor_cost`,
    and `budget_equipment_cost`, and its denominator is `planned_acres`;
    `provisional_cost_per_acre` is that quotient rounded to two decimal places".
    PRD §3.7: "The final numerator is the direct costs plus the equipment overhead
    multiplied by that allocation factor; the denominator is the plan's actual
    `harvested_acres`, not its planned acres."

    Design: Difficulty/dual_variant_calc/cost_per_acre_provisional_vs_final_diverge
    """
    set_clock("2026-06-01T00:00:00Z")
    parcel = create_parcel(name="North 100", acreage=100.0, soil_type="LOAM")
    seed = create_seed_product(name="Hybrid Corn Seed", unit_cost=1.0)
    seed_lot = create_input_lot(seed["id"], lot_code="SEEDLOT1", quantity_received=1000.0)
    chem = create_restricted_product(
        name="Atrazine RU", unit_cost=12.50, reentry_interval_hours=48, preharvest_interval_days=7)
    appl = create_applicator(full_name="Pat Applicator", license_no="RU-1", certified=True)
    plan = create_draft_plan(parcel["id"], crop="CORN", planned_acres=100.0,
                             budget_input_cost=4000.0, budget_labor_cost=3000.0,
                             budget_equipment_cost=2000.0)
    validate_success(api.approve_crop_plan(plan["id"], {"expected_parcel_version": parcel["version"]}, FM))
    record_planting(plan["id"], seed_lot["id"], acres_planted=100.0, seed_rate_per_acre=2.0)
    validate_success(api.begin_growing(plan["id"], AG))
    # CHEMICAL application: 2 * 40 * 12.50 = 1000 actual_input_cost.
    rec = log_application(plan["id"], chem["id"], appl["id"], rate_per_acre=2.0, acres_treated=40.0)
    validate_success(api.confirm_application(rec["id"], make_applicator_headers(appl["id"])))
    # Labor 30h * 20 = 600.
    validate_success(api.create_labor_entry(
        {"crop_plan_id": plan["id"], "worker_name": "W1", "hours": 30.0, "hourly_rate": 20.0}, AG), 201)
    # Equipment 5h * 80 = 400.
    equip = create_equipment_asset(name="Combine 1", kind="COMBINE", hourly_cost=80.0)
    validate_success(api.create_equipment_usage({
        "equipment_asset_id": equip["id"], "crop_plan_id": plan["id"],
        "window_start": "2026-06-18T08:00:00Z", "window_end": "2026-06-18T13:00:00Z"}, AG), 201)
    set_clock("2026-06-20T00:00:00Z")  # PHI (7d from 2026-06-01) elapsed.
    validate_success(api.begin_harvest(plan["id"], AG))
    record_harvest(plan["id"], acres_harvested=50.0, gross_quantity=1000.0, moisture_pct=0.0)

    closed = validate_success(api.close_crop_plan(plan["id"], FM))
    # provisional = (4000+3000+2000)/100 = 90.00
    assert closed["provisional_cost_per_acre"] == 90.00, (
        f"provisional must be 90.00, got {closed['provisional_cost_per_acre']}")
    # final = (1000+600+400)/50 = 40.00
    assert closed["final_cost_per_acre"] == 40.00, (
        f"final must be 40.00, got {closed['final_cost_per_acre']}")
    assert closed["provisional_cost_per_acre"] != closed["final_cost_per_acre"], (
        "provisional and final cost-per-acre must diverge")


def test_final_cost_per_acre_null_until_closed(api):
    """PRD §3.7: "The resulting `final_cost_per_acre` is rounded to two decimal places,
    rounded once at the very end, and remains null until the plan is `CLOSED`."

    Design: Difficulty/dual_variant_calc/cost_per_acre_provisional_vs_final_diverge
    """
    ctx = setup_harvesting_plan(crop="CORN", planned_acres=40.0, acreage=50.0)
    data = validate_success(api.get_crop_plan(ctx["plan"]["id"], FM))
    assert data["final_cost_per_acre"] is None, (
        f"final_cost_per_acre must be null before CLOSED, got {data['final_cost_per_acre']}")


# ===========================================================================
# Difficulty: dual_variant_calc — yield_graded_vs_gross_basis_diverge
# ===========================================================================
def test_total_yield_units_graded_only_excludes_ungraded(api):
    """PRD §3.6: "The plan's realized yield, `total_yield_units`, is the sum over the
    plan's harvest lots whose `quality_status` is `GRADE_A` or `GRADE_B` of each lot's
    `quantity`, rounded to two decimal places, with the rounding applied once after the
    full sum. Lots that are `UNGRADED` or `REJECTED` are excluded from
    `total_yield_units`."

    Design: Difficulty/dual_variant_calc/yield_graded_vs_gross_basis_diverge
    """
    set_clock("2026-06-01T00:00:00Z")
    parcel = create_parcel(name="Yield Field", acreage=80.0, soil_type="SILT")
    seed = create_seed_product(name="Soy Seed", unit_cost=0.50)
    seed_lot = create_input_lot(seed["id"], lot_code="SL1", quantity_received=500.0)
    plan, _ = create_and_approve_plan(parcel, crop="SOY", planned_acres=60.0,
                                      budgets=(100.0, 100.0, 100.0))
    record_planting(plan["id"], seed_lot["id"], acres_planted=60.0, seed_rate_per_acre=2.0)
    validate_success(api.begin_growing(plan["id"], AG))
    validate_success(api.begin_harvest(plan["id"], AG))
    he = record_harvest(plan["id"], acres_harvested=60.0, gross_quantity=1000.0, moisture_pct=0.0)
    create_graded_lot(he["id"], 500.5, "GRADE_A")
    create_graded_lot(he["id"], 300.25, "GRADE_B")
    lot_u = create_lot(he["id"], 100.0)  # left UNGRADED

    closed = validate_success(api.close_crop_plan(plan["id"], FM))
    # graded-only: 500.5 + 300.25 = 800.75 (gross basis would be 900.75).
    assert closed["total_yield_units"] == 800.75, (
        f"total_yield_units must be 800.75 (graded only), got {closed['total_yield_units']}")
    lot_u_after = validate_success(api.get_harvest_lot(lot_u["id"], FM))
    assert lot_u_after["quality_status"] == "UNGRADED", (
        f"UNGRADED lot must remain UNGRADED, got {lot_u_after['quality_status']}")


def test_total_yield_units_zero_when_no_graded_lots(api):
    """PRD §3.6: "Lots that are `UNGRADED` or `REJECTED` are excluded from
    `total_yield_units`. This persisted yield always uses the graded-only filter".

    Design: Difficulty/dual_variant_calc/yield_graded_vs_gross_basis_diverge
    """
    set_clock("2026-06-01T00:00:00Z")
    ctx = setup_harvesting_plan(crop="CORN", planned_acres=40.0, acreage=50.0)
    he = record_harvest(ctx["plan"]["id"], acres_harvested=40.0, gross_quantity=500.0, moisture_pct=0.0)
    create_lot(he["id"], 200.0)  # UNGRADED, never graded.
    closed = validate_success(api.close_crop_plan(ctx["plan"]["id"], FM))
    assert closed["total_yield_units"] == 0, (
        f"total_yield_units must be 0 with no graded lots, got {closed['total_yield_units']}")


# ===========================================================================
# Difficulty: combinatorial_formula — final_cost_per_acre_three_input_overhead
# ===========================================================================
def test_final_cost_per_acre_three_input_overhead_allocation(api):
    """PRD §3.7: "When this plan is the only plan harvested on its parcel for its
    `season_year`, the allocation factor is one and the full equipment cost lands on the
    plan."
    PRD §3.7: "The final numerator is the direct costs plus the equipment overhead
    multiplied by that allocation factor; the denominator is the plan's actual
    `harvested_acres`, not its planned acres."

    Design: Difficulty/combinatorial_formula/final_cost_per_acre_three_input_overhead_allocation
    """
    set_clock("2026-06-01T00:00:00Z")
    parcel = create_parcel(name="Combo Field", acreage=100.0, soil_type="LOAM")
    seed = create_seed_product(name="Wheat Seed", unit_cost=0.40)
    seed_lot = create_input_lot(seed["id"], lot_code="WL1", quantity_received=1000.0)
    fert = create_input_product(name="Liquid N", category="FERTILIZER", unit="GAL", unit_cost=12.50)
    appl = create_applicator(full_name="Lee", license_no="RU-2", certified=True)
    plan = create_draft_plan(parcel["id"], crop="WHEAT", planned_acres=100.0,
                             budget_input_cost=100.0, budget_labor_cost=100.0,
                             budget_equipment_cost=100.0)
    validate_success(api.approve_crop_plan(plan["id"], {"expected_parcel_version": parcel["version"]}, FM))
    record_planting(plan["id"], seed_lot["id"], acres_planted=100.0, seed_rate_per_acre=1.0)
    validate_success(api.begin_growing(plan["id"], AG))
    # input: 2 * 40 * 12.50 = 1000.
    rec = log_application(plan["id"], fert["id"], appl["id"], rate_per_acre=2.0, acres_treated=40.0)
    validate_success(api.confirm_application(rec["id"], make_applicator_headers(appl["id"])))
    # labor: 30 * 20 = 600.
    validate_success(api.create_labor_entry(
        {"crop_plan_id": plan["id"], "worker_name": "W", "hours": 30.0, "hourly_rate": 20.0}, AG), 201)
    # equipment: 5h * 80 = 400.
    equip = create_equipment_asset(name="Sprayer", kind="SPRAYER", hourly_cost=80.0)
    validate_success(api.create_equipment_usage({
        "equipment_asset_id": equip["id"], "crop_plan_id": plan["id"],
        "window_start": "2026-06-02T08:00:00Z", "window_end": "2026-06-02T13:00:00Z"}, AG), 201)
    validate_success(api.begin_harvest(plan["id"], AG))  # no restricted apps -> PHI vacuous.
    record_harvest(plan["id"], acres_harvested=50.0, gross_quantity=500.0, moisture_pct=0.0)

    closed = validate_success(api.close_crop_plan(plan["id"], FM))
    assert closed["actual_equipment_cost"] == 400.00, (
        f"actual_equipment_cost must be 400.00, got {closed['actual_equipment_cost']}")
    # f=1 (only plan): (1000 + 600 + 400)/50 = 40.00.
    assert closed["final_cost_per_acre"] == 40.00, (
        f"final_cost_per_acre must be 40.00, got {closed['final_cost_per_acre']}")


def test_final_cost_per_acre_accrues_three_actual_inputs(api):
    """PRD §3.7: "Its direct costs are the sum of `actual_input_cost` (the sum of
    `applied_cost` across the plan's non-voided confirmed applications) and
    `actual_labor_cost` (the sum of `labor_cost` across the plan's labor entries)."
    PRD §3.7: "Its overhead is `actual_equipment_cost` (the sum of `usage_cost` across the
    plan's `RECORDED` equipment usages), and that overhead is allocated to the plan by an
    acreage-share factor."

    Design: Difficulty/combinatorial_formula/final_cost_per_acre_three_input_overhead_allocation
    """
    set_clock("2026-06-01T00:00:00Z")
    parcel = create_parcel(name="Combo Field 2", acreage=100.0, soil_type="LOAM")
    seed = create_seed_product(name="Wheat Seed 2", unit_cost=0.40)
    seed_lot = create_input_lot(seed["id"], lot_code="WL2", quantity_received=1000.0)
    fert = create_input_product(name="Liquid N2", category="FERTILIZER", unit="GAL", unit_cost=12.50)
    appl = create_applicator(full_name="Lee2", license_no="RU-3", certified=True)
    plan = create_draft_plan(parcel["id"], crop="WHEAT", planned_acres=100.0,
                             budget_input_cost=100.0, budget_labor_cost=100.0,
                             budget_equipment_cost=100.0)
    validate_success(api.approve_crop_plan(plan["id"], {"expected_parcel_version": parcel["version"]}, FM))
    record_planting(plan["id"], seed_lot["id"], acres_planted=100.0, seed_rate_per_acre=1.0)
    validate_success(api.begin_growing(plan["id"], AG))
    rec = log_application(plan["id"], fert["id"], appl["id"], rate_per_acre=2.0, acres_treated=40.0)
    validate_success(api.confirm_application(rec["id"], make_applicator_headers(appl["id"])))
    validate_success(api.create_labor_entry(
        {"crop_plan_id": plan["id"], "worker_name": "W", "hours": 30.0, "hourly_rate": 20.0}, AG), 201)
    equip = create_equipment_asset(name="Sprayer 2", kind="SPRAYER", hourly_cost=80.0)
    validate_success(api.create_equipment_usage({
        "equipment_asset_id": equip["id"], "crop_plan_id": plan["id"],
        "window_start": "2026-06-02T08:00:00Z", "window_end": "2026-06-02T13:00:00Z"}, AG), 201)
    validate_success(api.begin_harvest(plan["id"], AG))
    record_harvest(plan["id"], acres_harvested=50.0, gross_quantity=500.0, moisture_pct=0.0)
    closed = validate_success(api.close_crop_plan(plan["id"], FM))
    # All three actual cost lines must each be accrued.
    assert closed["actual_input_cost"] == 1000.00, (
        f"actual_input_cost must be 1000.00, got {closed['actual_input_cost']}")
    assert closed["actual_labor_cost"] == 600.00, (
        f"actual_labor_cost must be 600.00, got {closed['actual_labor_cost']}")
    assert closed["actual_equipment_cost"] == 400.00, (
        f"actual_equipment_cost must be 400.00, got {closed['actual_equipment_cost']}")


# ===========================================================================
# Difficulty: combinatorial_formula — net_quantity_round_then_field_round_order_pinned
# ===========================================================================
def test_total_yield_units_sum_then_round_order_pinned(api):
    """PRD §3.6: "the sum over the plan's harvest lots whose `quality_status` is `GRADE_A`
    or `GRADE_B` of each lot's `quantity`, rounded to two decimal places, with the
    rounding applied once after the full sum."

    Design: Difficulty/combinatorial_formula/net_quantity_round_then_field_round_order_pinned
    """
    set_clock("2026-06-01T00:00:00Z")
    parcel = create_parcel(name="Round Field", acreage=50.0, soil_type="CLAY")
    seed = create_seed_product(name="Corn S", unit_cost=0.50)
    seed_lot = create_input_lot(seed["id"], lot_code="L", quantity_received=200.0)
    plan, _ = create_and_approve_plan(parcel, crop="CORN", planned_acres=40.0,
                                      budgets=(1.0, 1.0, 1.0))
    record_planting(plan["id"], seed_lot["id"], acres_planted=40.0, seed_rate_per_acre=2.0)
    validate_success(api.begin_growing(plan["id"], AG))
    validate_success(api.begin_harvest(plan["id"], AG))
    he = record_harvest(plan["id"], acres_harvested=40.0, gross_quantity=700.0, moisture_pct=0.0)
    create_graded_lot(he["id"], 333.333, "GRADE_A")
    create_graded_lot(he["id"], 333.334, "GRADE_A")

    closed = validate_success(api.close_crop_plan(plan["id"], FM))
    # sum-then-round: round(333.333 + 333.334, 2) = round(666.667, 2) = 666.67
    # (per-lot rounding then summing would give 333.33 + 333.33 = 666.66).
    assert closed["total_yield_units"] == 666.67, (
        f"total_yield_units must be 666.67 (sum-then-round), got {closed['total_yield_units']}")


def test_net_quantity_rounded_to_two_decimals_per_event(api):
    """PRD §3.5: "Its dry-weight `net_quantity` is computed from the gross quantity
    reduced by the moisture fraction — that is, `gross_quantity` multiplied by the
    quantity (one minus `moisture_pct` divided by 100) — rounded to two decimal places."

    Design: Difficulty/combinatorial_formula/net_quantity_round_then_field_round_order_pinned
    """
    set_clock("2026-06-01T00:00:00Z")
    ctx = setup_harvesting_plan(crop="CORN", planned_acres=40.0, acreage=50.0)
    # 1000.5 * (1 - 0.125) = 875.4375 -> round-half-up to 875.44.
    he = validate_success(api.create_harvest_event({
        "crop_plan_id": ctx["plan"]["id"], "acres_harvested": 40.0,
        "gross_quantity": 1000.5, "moisture_pct": 12.5}, AG), 201)
    assert he["net_quantity"] == 875.44, (
        f"net_quantity must round to 875.44, got {he['net_quantity']}")


def test_net_quantity_moisture_adjustment(api):
    """PRD §3.5: "Its dry-weight `net_quantity` is computed from the gross quantity
    reduced by the moisture fraction — that is, `gross_quantity` multiplied by the
    quantity (one minus `moisture_pct` divided by 100) — rounded to two decimal places."

    Design: Corner/calculations/net_quantity_moisture_adjustment
    """
    set_clock("2026-06-01T00:00:00Z")
    ctx = setup_harvesting_plan(crop="CORN", planned_acres=40.0, acreage=50.0)
    he = validate_success(api.create_harvest_event({
        "crop_plan_id": ctx["plan"]["id"], "acres_harvested": 40.0,
        "gross_quantity": 1000.0, "moisture_pct": 15.0}, AG), 201)
    # 1000 * (1 - 0.15) = 850.00.
    assert he["net_quantity"] == 850.00, (
        f"net_quantity must be 850.00, got {he['net_quantity']}")
