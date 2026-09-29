"""Corner cases of the derived numbers: setback geometry, the phosphorus index,
budget rate flooring, the records-basis nutrient summary, the annual mass
balance and the swine constant table.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_budget_ledger,
    assert_budget_rates,
    assert_operation_sizing,
    assert_quantity,
    assert_state,
    assert_storage_balance,
)
from test_helpers.factories import (
    annual_report_payload,
    application_event_payload,
)
from test_helpers.fixtures import (
    acknowledge_transfer,
    add_budget,
    file_soil_test,
    initiate_transfer,
    open_annual_report,
    record_application,
    register_field,
    register_hauler,
    register_operation,
    setup_scenario,
)
from test_helpers.test_users import ADMIN_HEADERS, PLANNER_HEADERS, REVIEWER_HEADERS

SWINE_OPERATION = {
    "name": "Blue Stem Finishing",
    "county": "Sac",
    "animal_type": "SWINE_FINISHING",
    "head_count": 1000,
    "manure_handling": "LIQUID",
    "open_lot_area_sqft": 0,
    "discharge_potential": "CONTINUOUS",
    "has_conservation_plan": True,
}


def _assert_instant(actual, prefix, label="instant"):
    """The instant echoed by the server carries the expected UTC calendar time."""
    assert actual is not None, f"{label} is missing"
    assert str(actual).startswith(prefix), (
        f"{label}: expected an instant at {prefix}, got {actual}"
    )


# ---------------------------------------------------------------------------
# Field setback geometry
# ---------------------------------------------------------------------------
def test_setback_base_precedence_and_the_slope_adder():
    """A tile inlet wins outright, exactly 200 ft to water still counts as near
    water, and the slope adder fires only strictly above 6 percent.

    PRD: "A base setback is selected by a strict precedence: a field with a tile inlet takes 300 feet regardless of anything else, because a tile inlet is a direct conduit to surface water; a field with no tile inlet whose `distance_to_water_ft` is 200 feet or less takes 200 feet; and every other field takes 100 feet."
    PRD: "A slope adder of 100 feet is then added when `slope_pct` is strictly greater than 6, so a field at exactly 6 percent slope adds nothing."
    PRD: "`net_applicable_acres` is `total_acres` less `excluded_acres`, rounded half up to 2 decimal places."
    Design: Corner/calculations/field_setback_thresholds_pick_tile_inlet_water_and_slope_terms
    """
    operation = register_operation()
    operation_id = operation["id"]

    tile = register_field(
        operation_id,
        PLANNER_HEADERS,
        field_name="Tile A",
        total_acres=30.0,
        distance_to_water_ft=900,
        has_tile_inlet=True,
        slope_pct=3.0,
        water_frontage_ft=1000,
    )
    edge = register_field(
        operation_id,
        PLANNER_HEADERS,
        field_name="Edge B",
        total_acres=40.0,
        distance_to_water_ft=200,
        has_tile_inlet=False,
        slope_pct=6.0,
        water_frontage_ft=500,
    )
    steep = register_field(
        operation_id,
        PLANNER_HEADERS,
        field_name="Steep C",
        total_acres=25.0,
        distance_to_water_ft=201,
        has_tile_inlet=False,
        slope_pct=6.1,
        water_frontage_ft=300,
    )

    # Tile inlet: 300 ft base, no slope adder; 300 * 1000 / 43560 = 6.89 acres.
    assert_quantity(tile["required_setback_ft"], 200 + 100, "tile required_setback_ft")
    assert_quantity(tile["excluded_acres"], 6.89, "tile excluded_acres")
    assert_quantity(tile["net_applicable_acres"], 23.11, "tile net_applicable_acres")
    assert tile["last_application_on"] is None

    # Exactly 200 ft to water and exactly 6 % slope: 200 ft, 100000 / 43560 = 2.30.
    assert_quantity(edge["required_setback_ft"], 200, "edge required_setback_ft")
    assert_quantity(edge["excluded_acres"], 2.30, "edge excluded_acres")
    assert_quantity(edge["net_applicable_acres"], 37.70, "edge net_applicable_acres")
    assert edge["last_application_on"] is None

    # 201 ft is beyond the near-water band, so base 100 plus the 6.1 % adder 100.
    assert_quantity(steep["required_setback_ft"], 200, "steep required_setback_ft")
    assert_quantity(steep["excluded_acres"], 1.38, "steep excluded_acres")
    assert_quantity(steep["net_applicable_acres"], 23.62, "steep net_applicable_acres")
    assert steep["last_application_on"] is None


def test_zero_water_frontage_excludes_no_acres():
    """An inland field with no boundary on surface water keeps all of its acres.

    PRD: "The setback strip is then converted to acreage: `excluded_acres` is `required_setback_ft` multiplied by `water_frontage_ft`, divided by 43,560 square feet per acre, rounded half up to 2 decimal places."
    Design: Corner/calculations/field_setback_thresholds_pick_tile_inlet_water_and_slope_terms
    """
    operation = register_operation()

    inland = register_field(
        operation["id"],
        PLANNER_HEADERS,
        field_name="Inland D",
        total_acres=12.0,
        distance_to_water_ft=500,
        has_tile_inlet=False,
        slope_pct=2.0,
        water_frontage_ft=0,
    )

    assert_quantity(inland["required_setback_ft"], 100, "required_setback_ft")
    assert_quantity(inland["excluded_acres"], 0.00, "excluded_acres")
    assert_quantity(inland["net_applicable_acres"], 12.00, "net_applicable_acres")
    assert inland["last_application_on"] is None


# ---------------------------------------------------------------------------
# Soil test phosphorus index
# ---------------------------------------------------------------------------
def test_p_index_is_rounded_before_the_very_high_comparison():
    """96.15 ppm on a 4 % slope computes 99.996, which rounds to 100.00 and lands
    in VERY_HIGH, while 96.1 ppm stays HIGH at 99.94.

    PRD: "`p_index` is `soil_test_p_ppm` multiplied by one plus the parent field's `slope_pct` divided by 100, rounded half up to 2 decimal places — so steeper ground converts the same measured concentration into a higher runoff risk index."
    PRD: "`p_index_category` follows from inclusive lower bounds: `VERY_HIGH` when `p_index` is at least 100; `HIGH` when it is at least 50 but below 100; `MEDIUM` when it is at least 20 but below 50; and `LOW` otherwise."
    Design: Corner/calculations/p_index_rounds_to_two_decimals_before_the_category_compare
    """
    operation = register_operation()
    field = register_field(operation["id"], PLANNER_HEADERS)

    very_high = file_soil_test(field["id"], PLANNER_HEADERS, soil_test_p_ppm=96.15)
    high = file_soil_test(field["id"], PLANNER_HEADERS, soil_test_p_ppm=96.1)

    assert_quantity(very_high["p_index"], 100.00, "p_index")
    assert_state(very_high, "p_index_category", "VERY_HIGH")
    assert very_high["is_valid"] is True

    assert_quantity(high["p_index"], 99.94, "p_index")
    assert_state(high, "p_index_category", "HIGH")
    assert high["is_valid"] is True


def test_p_index_category_floors_are_inclusive_lower_bounds():
    """A p_index of exactly 50.00 is HIGH and 49.99 is MEDIUM; 19.97 is LOW.

    PRD: "A `p_index` of exactly 50.00 is therefore `HIGH`, not `MEDIUM`."
    PRD: "`p_index_category` follows from inclusive lower bounds: `VERY_HIGH` when `p_index` is at least 100; `HIGH` when it is at least 50 but below 100; `MEDIUM` when it is at least 20 but below 50; and `LOW` otherwise."
    Design: Corner/calculations/p_index_rounds_to_two_decimals_before_the_category_compare
    """
    operation = register_operation()
    field = register_field(operation["id"], PLANNER_HEADERS)

    # 48.08 * 1.04 = 50.0032, which rounds to exactly the HIGH floor.
    at_floor = file_soil_test(field["id"], PLANNER_HEADERS, soil_test_p_ppm=48.08)
    below_floor = file_soil_test(field["id"], PLANNER_HEADERS, soil_test_p_ppm=48.07)
    low = file_soil_test(field["id"], PLANNER_HEADERS, soil_test_p_ppm=19.2)

    assert_quantity(at_floor["p_index"], 50.00, "p_index")
    assert_state(at_floor, "p_index_category", "HIGH")

    assert_quantity(below_floor["p_index"], 49.99, "p_index")
    assert_state(below_floor, "p_index_category", "MEDIUM")

    assert_quantity(low["p_index"], 19.97, "p_index")
    assert_state(low, "p_index_category", "LOW")

    for record in (at_floor, below_floor, low):
        assert record["is_valid"] is True


# ---------------------------------------------------------------------------
# Budget allowable rate
# ---------------------------------------------------------------------------
def test_injected_budget_floors_the_nitrogen_rate_and_binds_on_nitrogen():
    """At 0.65 availability the nitrogen limit computes 13397.44 and floors to
    13300, which is below the 14000 phosphorus limit.

    PRD: "`allowable_n_rate_gal_per_acre` is `adjusted_n_need_lbs` divided by that available-nitrogen figure and multiplied by 1,000, then floored to the nearest whole multiple of 100."
    PRD: "`binding_basis` records which limit bound: it is `NITROGEN` when `allowable_n_rate_gal_per_acre` is less than or equal to `allowable_p_rate_gal_per_acre`, and `PHOSPHORUS` otherwise — so a tie is attributed to nitrogen."
    PRD: "`allowable_total_gallons` is `allowable_rate_gal_per_acre` multiplied by the field's `net_applicable_acres`, floored to a whole gallon."
    Design: Corner/calculations/budget_rates_floor_to_hundred_gallons_and_binding_basis_follows_method
    """
    ctx = setup_scenario(
        "DRAFT_PLAN",
        plan={"allowed_application_methods": ["INJECTION", "SURFACE_BROADCAST"]},
    )

    budget = add_budget(
        ctx["plan"]["id"],
        ctx["field"]["id"],
        ctx["soil_test"]["id"],
        PLANNER_HEADERS,
        previous_crop="NONE",
        planned_application_method="INJECTION",
    )

    assert_budget_rates(
        budget,
        crop_n_need=209.00,
        legume_credit=0.00,
        adjusted_n_need=209.00,
        crop_p_removal=70.30,
        p_allowance=140.60,
        allowable_n_rate=13300,
        allowable_p_rate=14000,
        binding_basis="NITROGEN",
        allowable_rate=13300,
    )
    # 13300 * 38.37 acres = 510321 gallons.
    assert_budget_ledger(budget, applied=0.00, remaining=510321, total=510321)
    assert_state(budget, "budget_status", "LOCKED")


def test_surface_broadcast_raises_the_nitrogen_rate_so_phosphorus_binds():
    """The same agronomy at 0.40 availability computes 21770.83, floors to 21700
    and lets the 14000 phosphorus limit bind instead.

    PRD: "`allowable_rate_gal_per_acre` is whichever of the two limits is smaller."
    PRD: "`allowable_p_rate_gal_per_acre` is `p_allowance_lbs` divided by the manure phosphate concentration for the animal group — 10 pounds per thousand gallons for dairy, 16 for beef, 28 for swine, 45 for layer — multiplied by 1,000, then floored to the nearest whole multiple of 100."
    PRD: "Every budget is born with `budget_status` of `LOCKED`, and that is true even when it is filed against a plan that is already `APPROVED`."
    Design: Corner/calculations/budget_rates_floor_to_hundred_gallons_and_binding_basis_follows_method
    """
    ctx = setup_scenario(
        "DRAFT_PLAN",
        plan={"allowed_application_methods": ["INJECTION", "SURFACE_BROADCAST"]},
    )

    budget = add_budget(
        ctx["plan"]["id"],
        ctx["field"]["id"],
        ctx["soil_test"]["id"],
        PLANNER_HEADERS,
        previous_crop="NONE",
        planned_application_method="SURFACE_BROADCAST",
    )

    assert_budget_rates(
        budget,
        adjusted_n_need=209.00,
        p_allowance=140.60,
        allowable_n_rate=21700,
        allowable_p_rate=14000,
        binding_basis="PHOSPHORUS",
        allowable_rate=14000,
    )
    # 14000 * 38.37 acres = 537180 gallons.
    assert_budget_ledger(budget, applied=0.00, remaining=537180, total=537180)
    assert_state(budget, "budget_status", "LOCKED")


# ---------------------------------------------------------------------------
# Records-basis nutrient summary
# ---------------------------------------------------------------------------
def test_records_basis_ignores_initiated_transfers_and_voided_events():
    """The same rows are polled three times: an INITIATED transfer contributes
    nothing, the acknowledged transfer contributes once, and voiding the
    application removes its gallons and its nitrogen.

    PRD: "The records figure, `recorded_annual_manure_gallons`, is the sum of `gallons_applied` across land application records whose owning plan belongs to this operation, whose `event_status` is `RECORDED` or `VERIFIED`, and whose `applied_on` falls in the selected UTC calendar year, plus the sum of `gallons_transferred` across transfers of this operation whose `transfer_status` is `ACKNOWLEDGED` or `COMPLETED` and whose `transferred_on` falls in that same year."
    PRD: "The design basis derives volume purely from `head_count`, the per-head coefficient, the dilution factor and lot precipitation, and ignores every record ever filed; the records basis derives volume purely from persisted records and ignores `head_count` entirely, so changing the herd does not move it while voiding an application record does."
    Design: Corner/calculations/records_basis_summary_skips_voided_events_and_uncommitted_transfers
    """
    ctx = setup_scenario("APPROVED", intake_gallons=1000000)
    operation_id = ctx["operation"]["id"]
    operator_headers = ctx["operator_headers"]

    event = record_application(
        operation_id,
        ctx["plan"]["id"],
        ctx["budget"]["id"],
        ctx["storage"]["id"],
        operator_headers,
        applied_on="2026-07-20T00:00:00Z",
        gallons_applied=300000,
        acres_treated=30,
    )
    assert_quantity(event["n_applied_lbs"], 4680.00, "n_applied_lbs")
    assert_quantity(event["p2o5_applied_lbs"], 3000.00, "p2o5_applied_lbs")

    hauler = register_hauler()
    transfer = initiate_transfer(
        operation_id,
        ctx["storage"]["id"],
        hauler["id"],
        operator_headers,
        transferred_on="2026-07-28T00:00:00Z",
        gallons_transferred=200000,
    )

    params = {"basis": "RECORDS_BASIS", "year": 2026}

    first = validate_success(
        api_client.get_operation_nutrient_summary(
            operation_id, REVIEWER_HEADERS, params
        )
    )
    assert_quantity(first["recorded_land_applied_gallons"], 300000.00, "land applied")
    assert_quantity(first["recorded_transferred_gallons"], 0.00, "transferred")
    assert_quantity(first["recorded_annual_manure_gallons"], 300000.00, "records total")
    assert_quantity(first["total_n_applied_lbs"], 4680.00, "total_n_applied_lbs")
    assert_quantity(first["total_p2o5_applied_lbs"], 3000.00, "total_p2o5_applied_lbs")
    assert_quantity(
        first["design_annual_manure_gallons"], 3374298.00, "design_annual_manure_gallons"
    )

    acknowledge_transfer(hauler["id"], transfer["id"])

    second = validate_success(
        api_client.get_operation_nutrient_summary(
            operation_id, REVIEWER_HEADERS, params
        )
    )
    assert_quantity(second["recorded_transferred_gallons"], 200000.00, "transferred")
    assert_quantity(second["recorded_annual_manure_gallons"], 500000.00, "records total")
    # The transfer reports total rather than plant-available nitrogen, so its
    # 4800 lb never enters the land-application roll-up.
    assert_quantity(second["total_n_applied_lbs"], 4680.00, "total_n_applied_lbs")

    validate_success(
        api_client.void_application_event(event["id"], ADMIN_HEADERS)
    )

    third = validate_success(
        api_client.get_operation_nutrient_summary(
            operation_id, REVIEWER_HEADERS, params
        )
    )
    assert_quantity(third["recorded_land_applied_gallons"], 0.00, "land applied")
    assert_quantity(third["recorded_transferred_gallons"], 200000.00, "transferred")
    assert_quantity(third["recorded_annual_manure_gallons"], 200000.00, "records total")
    assert_quantity(third["total_n_applied_lbs"], 0.00, "total_n_applied_lbs")

    operation = validate_success(
        api_client.get_operation(operation_id, ADMIN_HEADERS)
    )
    assert_quantity(
        operation["recorded_annual_manure_gallons"], 200000.00, "records total"
    )
    assert_quantity(
        operation["design_annual_manure_gallons"],
        3374298.00,
        "design_annual_manure_gallons",
    )


# ---------------------------------------------------------------------------
# Annual report mass balance
# ---------------------------------------------------------------------------
def test_variance_of_exactly_minus_fifteen_percent_is_within_tolerance():
    """With no records at all the balance reduces to the storage delta, pinning
    the variance to exactly -15.00, which submits without an explanation.

    PRD: "`variance_pct` is `recorded_total_gallons` less `mass_balance_expected_gallons`, divided by `mass_balance_expected_gallons`, multiplied by 100, rounded half up to 2 decimal places."
    PRD: "The comparison is inclusive, so a `variance_pct` of exactly 15.00 or exactly -15.00 is `WITHIN_TOLERANCE`."
    Design: Corner/calculations/annual_report_variance_tolerance_is_inclusive_at_minus_fifteen
    """
    ctx = setup_scenario("DRAFT_PLAN")
    operation_id = ctx["operation"]["id"]

    # 3374298.00 less 15 % of itself is 2868153.30.
    report = open_annual_report(
        operation_id,
        ctx["plan"]["id"],
        ctx["operator_headers"],
        report_year=2026,
        beginning_storage_gallons=0,
        ending_storage_gallons=2868153.3,
    )

    assert_quantity(report["recorded_land_applied_gallons"], 0.00, "land applied")
    assert_quantity(report["recorded_transferred_gallons"], 0.00, "transferred")
    assert_quantity(report["recorded_total_gallons"], 2868153.30, "recorded_total")
    assert_quantity(
        report["mass_balance_expected_gallons"], 3374298.00, "expected gallons"
    )
    assert_quantity(report["variance_pct"], -15.00, "variance_pct")
    assert_state(report, "variance_classification", "WITHIN_TOLERANCE")
    assert_quantity(report["total_n_applied_lbs"], 0.00, "total_n_applied_lbs")
    assert_quantity(report["total_p2o5_applied_lbs"], 0.00, "total_p2o5_applied_lbs")
    assert_state(report, "report_status", "DRAFT")

    submitted = validate_success(
        api_client.submit_annual_report(report["id"], ctx["operator_headers"])
    )
    assert_state(submitted, "report_status", "SUBMITTED")
    _assert_instant(submitted["submitted_at"], "2026-08-01T00:00:00", "submitted_at")


def test_out_of_tolerance_report_submits_only_with_an_explanation():
    """A -15.09 variance is one step outside the inclusive band, so submission
    needs a non-empty explanation.

    PRD: "`variance_classification` is `WITHIN_TOLERANCE` when the absolute value of `variance_pct` is at most 15.00, and `EXCEEDS_TOLERANCE` otherwise."
    PRD: "Submission is admissible only when `variance_classification` is `WITHIN_TOLERANCE` **or** `variance_explanation` is a non-empty string; an unexplained out-of-tolerance report is refused with `ERR_VARIANCE_EXPLANATION_REQUIRED`."
    Design: Corner/calculations/annual_report_variance_tolerance_is_inclusive_at_minus_fifteen
    """
    ctx = setup_scenario("DRAFT_PLAN")
    operation_id = ctx["operation"]["id"]
    operator_headers = ctx["operator_headers"]

    unexplained = open_annual_report(
        operation_id,
        ctx["plan"]["id"],
        operator_headers,
        report_year=2025,
        beginning_storage_gallons=0,
        ending_storage_gallons=2865000,
    )
    explained = open_annual_report(
        operation_id,
        ctx["plan"]["id"],
        operator_headers,
        report_year=2024,
        beginning_storage_gallons=0,
        ending_storage_gallons=2865000,
        variance_explanation=(
            "Herd depopulated in March after a barn fire; production ran below "
            "design all year."
        ),
    )

    assert_quantity(unexplained["recorded_total_gallons"], 2865000.00, "recorded_total")
    assert_quantity(unexplained["variance_pct"], -15.09, "variance_pct")
    assert_state(unexplained, "variance_classification", "EXCEEDS_TOLERANCE")

    validate_error(
        api_client.submit_annual_report(unexplained["id"], operator_headers),
        ApiErrorId.ERR_VARIANCE_EXPLANATION_REQUIRED,
    )
    still_draft = validate_success(
        api_client.get_annual_report(unexplained["id"], operator_headers)
    )
    assert_state(still_draft, "report_status", "DRAFT")

    assert_quantity(explained["variance_pct"], -15.09, "variance_pct")
    submitted = validate_success(
        api_client.submit_annual_report(explained["id"], operator_headers)
    )
    assert_state(submitted, "report_status", "SUBMITTED")


def test_a_second_report_for_the_same_year_is_a_duplicate_period():
    """One report per operation and report_year; the second is refused and no
    extra row is written.

    PRD: "Only one report may exist per operation and `report_year`; a second is refused with `ERR_REPORT_PERIOD_DUPLICATE`."
    Design: Corner/calculations/annual_report_variance_tolerance_is_inclusive_at_minus_fifteen
    """
    ctx = setup_scenario("DRAFT_PLAN")
    operation_id = ctx["operation"]["id"]
    operator_headers = ctx["operator_headers"]

    open_annual_report(
        operation_id,
        ctx["plan"]["id"],
        operator_headers,
        report_year=2026,
        beginning_storage_gallons=0,
        ending_storage_gallons=2868153.3,
    )

    validate_error(
        api_client.create_annual_report(
            annual_report_payload(
                operation_id,
                ctx["plan"]["id"],
                report_year=2026,
                beginning_storage_gallons=0,
                ending_storage_gallons=3374298,
            ),
            operator_headers,
        ),
        ApiErrorId.ERR_REPORT_PERIOD_DUPLICATE,
    )

    reports, meta = validate_paginated(
        api_client.list_annual_reports(
            operator_headers, {"operation_id": operation_id}
        )
    )
    assert meta["total_count"] == 1, f"expected one report, got {meta['total_count']}"
    assert len(reports) == 1


# ---------------------------------------------------------------------------
# The swine constant table
# ---------------------------------------------------------------------------
def test_swine_constants_size_the_operation_and_its_storage_days():
    """0.4 animal units and 1,400 gallons per head, diluted 1.15, give 400.00
    animal units and 1610000.00 design gallons.

    PRD: "Each animal type carries an animal-unit factor: 1.4 for a `DAIRY_COW`, 1.0 for a `BEEF_FEEDER`, and 0.4 for a `SWINE_FINISHING` animal."
    PRD: "Each animal type has an annual per-head volume: 9,000 gallons for a `DAIRY_COW`, 3,600 for a `BEEF_FEEDER`, 1,400 for a `SWINE_FINISHING` animal and 30 for a `LAYER_HEN`."
    PRD: "`daily_production_gallons` is `design_annual_manure_gallons` divided by 365, rounded half up to 2 decimal places."
    Design: Corner/calculations/swine_manure_constants_move_the_binding_limit_and_the_event_load
    """
    ctx = setup_scenario("STORAGE", operation=SWINE_OPERATION)

    operation = validate_success(
        api_client.get_operation(ctx["operation"]["id"], ADMIN_HEADERS)
    )
    assert_operation_sizing(
        operation,
        animal_units=400.00,
        size_class="MEDIUM",
        permit_required=True,
        design_annual_manure_gallons=1610000.00,
        daily_production_gallons=4410.96,
    )
    # 4488300.00 of operating capacity over 4410.96 gallons a day, floored.
    assert operation["design_storage_days"] == 1017, (
        f"design_storage_days: expected 1017, got {operation['design_storage_days']}"
    )


def test_swine_phosphate_concentration_makes_phosphorus_the_binding_basis():
    """On identical agronomy the richer swine manure floors the phosphorus limit
    to 5000 gal per acre, below the 8000 nitrogen limit.

    PRD: "`allowable_p_rate_gal_per_acre` is `p_allowance_lbs` divided by the manure phosphate concentration for the animal group — 10 pounds per thousand gallons for dairy, 16 for beef, 28 for swine, 45 for layer — multiplied by 1,000, then floored to the nearest whole multiple of 100."
    PRD: "`allowable_rate_gal_per_acre` is whichever of the two limits is smaller."
    Design: Corner/calculations/swine_manure_constants_move_the_binding_limit_and_the_event_load
    """
    ctx = setup_scenario(
        "BUDGET",
        operation=SWINE_OPERATION,
        plan={"allowed_application_methods": ["INJECTION"]},
        budget={"previous_crop": "NONE"},
    )

    budget = ctx["budget"]
    # 40 lb of nitrogen per 1,000 gal at 0.65 availability is 26.00 lb available.
    assert_budget_rates(
        budget,
        adjusted_n_need=209.00,
        p_allowance=140.60,
        allowable_n_rate=8000,
        allowable_p_rate=5000,
        binding_basis="PHOSPHORUS",
        allowable_rate=5000,
    )
    # 5000 * 38.37 acres = 191850 gallons.
    assert_budget_ledger(budget, applied=0.00, remaining=191850, total=191850)


def test_swine_event_load_inverts_the_dairy_nutrient_ratio():
    """An event at exactly the 5000 gal per acre limit is accepted and carries
    more phosphate than nitrogen; 6000 gal per acre is refused.

    PRD: "`p2o5_applied_lbs` is `gallons_applied` divided by 1,000, multiplied by the manure phosphate concentration for the group — 10 pounds per thousand gallons for dairy, 16 for beef, 28 for swine, 45 for layer — rounded half up to 2 decimal places; no availability factor applies to phosphate."
    PRD: "The per-acre rate, `rate_gal_per_acre`, computed as `gallons_applied` divided by `acres_treated` and rounded half up to 2 decimal places, may not exceed the budget's `allowable_rate_gal_per_acre`, or the record is refused with `ERR_RATE_EXCEEDS_LIMIT`."
    Design: Corner/calculations/swine_manure_constants_move_the_binding_limit_and_the_event_load
    """
    ctx = setup_scenario(
        "APPROVED",
        operation=SWINE_OPERATION,
        plan={"allowed_application_methods": ["INJECTION"]},
        budget={"previous_crop": "NONE"},
        intake_gallons=1000000,
    )
    operator_headers = ctx["operator_headers"]

    event = record_application(
        ctx["operation"]["id"],
        ctx["plan"]["id"],
        ctx["budget"]["id"],
        ctx["storage"]["id"],
        operator_headers,
        applied_on="2026-07-01T00:00:00Z",
        gallons_applied=100000,
        acres_treated=20,
        applicator_name="R. Haan",
    )
    assert_quantity(event["rate_gal_per_acre"], 5000.00, "rate_gal_per_acre")
    assert_state(event, "event_status", "RECORDED")
    # 100 thousand gallons at 40 lb N x 0.65 and 28 lb P2O5.
    assert_quantity(event["n_applied_lbs"], 2600.00, "n_applied_lbs")
    assert_quantity(event["p2o5_applied_lbs"], 2800.00, "p2o5_applied_lbs")

    ledger = validate_success(
        api_client.get_field_budget(ctx["budget"]["id"], operator_headers)
    )
    assert_budget_ledger(ledger, applied=100000.00, remaining=91850, total=191850)

    validate_error(
        api_client.create_application_event(
            application_event_payload(
                ctx["plan"]["id"],
                ctx["budget"]["id"],
                ctx["storage"]["id"],
                applied_on="2026-07-25T00:00:00Z",
                gallons_applied=60000,
                acres_treated=10,
                applicator_name="R. Haan",
            ),
            operator_headers,
        ),
        ApiErrorId.ERR_RATE_EXCEEDS_LIMIT,
    )

    unchanged = validate_success(
        api_client.get_field_budget(ctx["budget"]["id"], operator_headers)
    )
    assert_budget_ledger(unchanged, applied=100000.00, remaining=91850, total=191850)

    storage = validate_success(
        api_client.get_manure_storage(ctx["storage"]["id"], operator_headers)
    )
    assert_storage_balance(
        storage,
        intake=1000000.00,
        outflow=100000.00,
        current=900000.00,
        committed=0.00,
    )
