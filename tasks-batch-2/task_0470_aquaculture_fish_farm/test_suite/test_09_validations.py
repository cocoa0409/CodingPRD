"""Domain validation surface: grading conservation and split-target gates,
biomass capacity, broodstock allocation, sales availability/lot integrity,
species code uniqueness, pagination range, duplicate lines, water-temp banding,
harvest/processing weight ceilings, posture-override and split shape checks.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    create_species,
    create_tank,
    create_cohort,
    create_broodstock_batch,
    create_planned_grading,
    drive_tank_restricted,
    create_product_lot,
    create_sales_order,
    add_line,
    get_lot,
    create_harvest_order,
    create_grading_event_payload,
    create_cohort_payload,
    create_stocking_event_payload,
    create_harvest_order_payload,
)

FM = TEST_USERS["farm_manager_headers"]
FT = TEST_USERS["farm_technician_headers"]
HO = TEST_USERS["harvest_operator_headers"]
SA = TEST_USERS["sales_agent_headers"]


# ===========================================================================
# validations :: grading_plan_fish_count_mismatch
# ===========================================================================
def test_grading_plan_fish_count_mismatch_rejected():
    """PRD §3.5: "The sum of the fish_count across all planned_splits must exactly
    equal the source cohort's fish_count - no fish created or destroyed; a mismatch
    is rejected with ERR_FISH_COUNT_MISMATCH (HTTP 422)."

    Design: Corner/validations/grading_plan_fish_count_mismatch
    """
    species = create_species()
    t1 = create_tank(name="T1")
    t2 = create_tank(name="T2")
    cohort = create_cohort(species["id"], t1["id"], fish_count=1000)
    splits = [{"label": "x", "fish_count": 900, "target_tank_id": t2["id"],
               "avg_weight_g": 60}]
    g = get_success_data(
        api_client.create_grading_event(
            create_grading_event_payload(cohort["id"], splits), FT
        )
    )
    resp = api_client.plan_grading_event(g["id"], FT)
    validate_error(resp, ApiErrorId.ERR_FISH_COUNT_MISMATCH.value)


# ===========================================================================
# validations :: grading_plan_target_tank_not_open
# ===========================================================================
def test_grading_plan_target_tank_not_open_rejected():
    """PRD §3.5: "Each split's target_tank_id must reference a tank whose posture
    is OPEN; a target whose posture is anything other than OPEN is rejected with
    ERR_INVALID_SPLIT_TARGET (HTTP 409)."

    Design: Corner/validations/grading_plan_target_tank_not_open
    """
    species = create_species()
    t1 = create_tank(name="T1")
    t2 = create_tank(name="T2")
    drive_tank_restricted(t2["id"])
    cohort = create_cohort(species["id"], t1["id"], fish_count=100)
    splits = [{"label": "x", "fish_count": 100, "target_tank_id": t2["id"],
               "avg_weight_g": 60}]
    g = get_success_data(
        api_client.create_grading_event(
            create_grading_event_payload(cohort["id"], splits), FT
        )
    )
    resp = api_client.plan_grading_event(g["id"], FT)
    validate_error(resp, ApiErrorId.ERR_INVALID_SPLIT_TARGET.value)


# ===========================================================================
# validations :: stocking_biomass_capacity_exceeded
# ===========================================================================
def test_stocking_biomass_capacity_exceeded_rejected():
    """PRD §3.6: "The event must also respect biomass capacity: a stocking event
    that would push the tank's current_biomass_kg above its max_biomass_kg is
    rejected with ERR_TANK_BIOMASS_EXCEEDED (HTTP 422)."

    Design: Corner/validations/stocking_biomass_capacity_exceeded
    """
    species = create_species()
    tank = create_tank(volume_liters=100000, max_biomass_kg=5)
    cohort = create_cohort(species["id"], tank["id"], fish_count=1000,
                           stocked_avg_weight_g=50)
    resp = api_client.create_stocking_event(
        create_stocking_event_payload(cohort["id"], tank["id"], fish_count=1000,
                                      stocked_at="2026-01-01T00:00:00Z",
                                      expected_harvest_at="2026-06-01T00:00:00Z"),
        FT,
    )
    validate_error(resp, ApiErrorId.ERR_TANK_BIOMASS_EXCEEDED.value)


# ===========================================================================
# validations :: broodstock_allocation_insufficient
# ===========================================================================
def test_broodstock_allocation_insufficient_rejected():
    """PRD §3.2: "When a cohort draws from a broodstock batch, the draw must not
    exceed the batch's remaining fingerlings - that is, the requested fish_count
    may not exceed fingerling_count minus allocated_count. A draw that would exceed
    the remainder is rejected with ERR_BROODSTOCK_INSUFFICIENT (HTTP 422)."

    Design: Corner/validations/broodstock_allocation_insufficient
    """
    species = create_species()
    tank = create_tank()
    batch = create_broodstock_batch(species["id"], fingerling_count=1000)
    payload = create_cohort_payload(species["id"], tank["id"],
                                    origin_broodstock_id=batch["id"], fish_count=2000,
                                    stocked_avg_weight_g=5,
                                    stocked_at="2026-01-01T00:00:00Z")
    resp = api_client.create_cohort(payload, FT)
    validate_error(resp, ApiErrorId.ERR_BROODSTOCK_INSUFFICIENT.value)


# ===========================================================================
# validations :: sales_confirm_empty_order_rejected
# ===========================================================================
def test_confirm_empty_order_rejected():
    """PRD §3.10: "The order must have at least one line; a confirm on an order
    with zero lines is rejected with ERR_EMPTY_ORDER (HTTP 422)."

    Design: Corner/validations/sales_confirm_empty_order_rejected
    """
    order = create_sales_order(discount_tier="NONE")
    resp = api_client.confirm_sales_order(
        order["id"], {"expected_lot_version": order["version"]}, SA
    )
    validate_error(resp, ApiErrorId.ERR_EMPTY_ORDER.value)


# ===========================================================================
# validations :: sales_confirm_insufficient_lot_weight
# ===========================================================================
def test_confirm_insufficient_lot_weight_rejected():
    """PRD §3.10: "Each line's weight_kg must not exceed its lot's
    available_weight_kg, and the aggregate reserved per lot across the order's
    lines must not exceed that lot's available_weight_kg; an over-reservation is
    rejected with ERR_INSUFFICIENT_LOT_WEIGHT (HTTP 422)."

    Design: Corner/validations/sales_confirm_insufficient_lot_weight
    """
    lot, _species, _tank = create_product_lot(50.0, price_per_kg=10.0)
    order = create_sales_order(discount_tier="NONE")
    add_line(order["id"], lot["id"], 60.0)
    lot_now = get_lot(lot["id"])
    resp = api_client.confirm_sales_order(
        order["id"], {"expected_lot_version": lot_now["version"]}, SA
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_LOT_WEIGHT.value)


# ===========================================================================
# validations :: duplicate_species_code_rejected
# ===========================================================================
def test_duplicate_species_code_rejected():
    """PRD §3.1: "it must be unique across all species; an attempt to register a
    code that already exists is rejected with ERR_DUPLICATE_CODE (HTTP 409)."

    Design: Corner/validations/duplicate_species_code_rejected
    """
    create_species(common_name="Atlantic Salmon", code="SALM")
    resp = api_client.create_species(
        {"common_name": "Coho", "code": "SALM", "target_market_weight_g": 3000,
         "base_daily_growth_g": 4.0, "default_processing_yield_pct": 0.60,
         "min_water_temp_c": 4, "max_water_temp_c": 16},
        FM,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_CODE.value)


# ===========================================================================
# validations :: pagination_limit_out_of_range
# ===========================================================================
def test_pagination_limit_above_max_rejected():
    """PRD §2.3: "A limit below 1 or above 100, or a negative offset, is rejected
    with ERR_VALIDATION_LIMIT_RANGE (HTTP 400)."

    Design: Corner/validations/pagination_limit_out_of_range
    """
    resp = api_client.list_cohorts(FT, params={"limit": 500})
    validate_error(resp, ApiErrorId.ERR_VALIDATION_LIMIT_RANGE.value)


# ===========================================================================
# validations :: duplicate_line_same_lot_rejected
# ===========================================================================
def test_duplicate_line_same_lot_rejected():
    """PRD §3.10: "Two lines on the same order may not reference the same
    product_lot_id; a duplicate lot across lines is rejected with
    ERR_DUPLICATE_LINE_LOT (HTTP 409), because availability is aggregated per lot
    and requires one line per lot."

    Design: Corner/validations/duplicate_line_same_lot_rejected
    """
    lot, _species, _tank = create_product_lot(50.0, price_per_kg=10.0)
    order = create_sales_order(discount_tier="NONE")
    add_line(order["id"], lot["id"], 10.0)
    resp = api_client.add_sales_order_line(
        order["id"], {"product_lot_id": lot["id"], "weight_kg": 5.0}, SA
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_LINE_LOT.value)


# ===========================================================================
# validations :: water_temp_out_of_band_rejected
# ===========================================================================
def test_water_temp_out_of_band_rejected():
    """PRD §2.9: "When a water-quality reading is recorded on a tank that currently
    holds one or more cohorts, the reading's water_temp_c must fall within the
    species band of those residing cohorts. A reading whose water_temp_c lies
    outside that band is rejected with ERR_WATER_TEMP_OUT_OF_BAND (HTTP 422)."

    Design: Corner/validations/water_temp_out_of_band_rejected
    """
    species = create_species(min_water_temp_c=2, max_water_temp_c=18)
    tank = create_tank()
    create_cohort(species["id"], tank["id"], fish_count=100)
    resp = api_client.create_water_quality_reading(
        tank["id"],
        {"measured_at": "2026-01-02T00:00:00Z", "dissolved_oxygen_mg_l": 8.0,
         "ammonia_mg_l": 0.1, "water_temp_c": 30.0},
        FT,
    )
    validate_error(resp, ApiErrorId.ERR_WATER_TEMP_OUT_OF_BAND.value)


# ===========================================================================
# validations :: harvest_planned_count_exceeds_cohort
# ===========================================================================
def test_harvest_planned_count_exceeds_cohort_rejected():
    """PRD §3.8: "a planned_fish_count exceeding the cohort's fish_count is
    rejected with ERR_HARVEST_COUNT_EXCEEDS (HTTP 422)."

    Design: Corner/validations/harvest_planned_count_exceeds_cohort
    """
    species = create_species()
    tank = create_tank()
    cohort = create_cohort(species["id"], tank["id"], fish_count=1000)
    ho = create_harvest_order(cohort["id"], planned_fish_count=2000,
                              scheduled_at="2026-01-05T00:00:00Z")
    resp = api_client.schedule_harvest_order(ho["id"], HO)
    validate_error(resp, ApiErrorId.ERR_HARVEST_COUNT_EXCEEDS.value)


# ===========================================================================
# validations :: processing_actual_weight_exceeds_input
# ===========================================================================
def test_processing_actual_weight_exceeds_input_rejected():
    """PRD §3.9: "the actual_processed_weight_kg must be greater than zero and must
    not exceed the batch's input_live_weight_kg. An actual weight exceeding the
    input is rejected with ERR_PROCESSING_WEIGHT_EXCEEDS (HTTP 422)."

    Design: Corner/validations/processing_actual_weight_exceeds_input
    """
    species = create_species()
    tank = create_tank()
    cohort = create_cohort(species["id"], tank["id"], fish_count=1000)
    ho = create_harvest_order(cohort["id"], planned_fish_count=500,
                              scheduled_at="2026-01-01T00:00:00Z")
    get_success_data(api_client.schedule_harvest_order(ho["id"], HO))
    get_success_data(api_client.start_harvest_order(ho["id"], HO))
    get_success_data(
        api_client.complete_harvest_order(
            ho["id"], {"harvested_fish_count": 500, "harvested_live_weight_kg": 200.0}, HO
        )
    )
    pb = get_success_data(api_client.create_processing_batch({"harvest_order_id": ho["id"]}, HO))
    get_success_data(api_client.start_processing_batch(pb["id"], HO))
    resp = api_client.complete_processing_batch(
        pb["id"], {"actual_processed_weight_kg": 300.0, "price_per_kg": 12.0}, HO
    )
    validate_error(resp, ApiErrorId.ERR_PROCESSING_WEIGHT_EXCEEDS.value)


# ===========================================================================
# validations :: posture_override_invalid_value
# ===========================================================================
def test_posture_override_invalid_value_rejected():
    """PRD §2.7: "The posture_override is set only by a FarmManager and may be
    RESTRICTED, FROZEN, or null ... Any posture_override value other than
    RESTRICTED, FROZEN, or null is rejected with ERR_POSTURE_OVERRIDE_INVALID (HTTP
    400)."

    Design: Corner/validations/posture_override_invalid_value
    """
    tank = create_tank()
    resp = api_client.set_posture_override(tank["id"], {"posture_override": "OPEN"}, FM)
    validate_error(resp, ApiErrorId.ERR_POSTURE_OVERRIDE_INVALID.value)


# ===========================================================================
# validations :: grading_empty_splits_rejected
# ===========================================================================
def test_grading_empty_splits_rejected():
    """PRD §3.5: "The planned_splits must be non-empty and no split may carry a
    non-positive fish_count; an empty array or a split with fish_count of zero or
    less is rejected with ERR_GRADING_SPLIT_EMPTY (HTTP 422)."

    Design: Corner/validations/grading_empty_splits_rejected
    """
    species = create_species()
    tank = create_tank()
    cohort = create_cohort(species["id"], tank["id"], fish_count=100)
    resp = api_client.create_grading_event(
        create_grading_event_payload(cohort["id"], []), FT
    )
    validate_error(resp, ApiErrorId.ERR_GRADING_SPLIT_EMPTY.value)


# ===========================================================================
# validations :: lot_depleted_blocks_confirm
# ===========================================================================
def test_lot_depleted_blocks_second_confirm():
    """PRD §3.10: "Every referenced lot must be AVAILABLE at confirm time; a
    referenced lot that is DEPLETED is rejected with ERR_LOT_DEPLETED (HTTP 409)."

    Design: Corner/validations/lot_depleted_blocks_confirm
    """
    lot, _species, _tank = create_product_lot(50.0, price_per_kg=10.0)
    o1 = create_sales_order(customer_name="Acme", discount_tier="NONE")
    add_line(o1["id"], lot["id"], 50.0)
    lot_v1 = get_lot(lot["id"])["version"]
    get_success_data(
        api_client.confirm_sales_order(o1["id"], {"expected_lot_version": lot_v1}, SA)
    )
    o2 = create_sales_order(customer_name="Beta", discount_tier="NONE")
    add_line(o2["id"], lot["id"], 10.0)
    lot_v2 = get_lot(lot["id"])["version"]
    resp = api_client.confirm_sales_order(o2["id"], {"expected_lot_version": lot_v2}, SA)
    validate_error(resp, ApiErrorId.ERR_LOT_DEPLETED.value)
