"""The two computed reads that expose a design variant and a records variant of
the same quantity side by side.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import api_client
from test_helpers.assertions import (
    assert_four_decimals,
    assert_quantity,
    assert_storage_balance,
    assert_storage_capacities,
)
from test_helpers.fixtures import (
    record_application,
    setup_ready_operation,
    setup_scenario,
)


def _operation_with_one_application():
    """Approved plan, an active budget, a million gallons stored and one
    300,000-gallon injection recorded on 20 July 2026."""
    ctx = setup_ready_operation()
    ctx["event"] = record_application(
        ctx["operation"]["id"],
        ctx["plan"]["id"],
        ctx["budget"]["id"],
        ctx["storage"]["id"],
        ctx["operator_headers"],
        applied_on="2026-07-20T00:00:00Z",
    )
    return ctx


def test_nutrient_summary_design_and_records_bases_diverge_on_one_operation():
    """The design basis reports the herd's design production while the records
    basis reports only what was actually filed, and both figures ride in both
    responses so the gap is readable.

    PRD: "The design basis derives volume purely from `head_count`, the per-head coefficient, the dilution factor and lot precipitation, and ignores every record ever filed; the records basis derives volume purely from persisted records and ignores `head_count` entirely, so changing the herd does not move it while voiding an application record does."
    PRD: "It accepts an optional `basis` selector, which is either `DESIGN_BASIS` or `RECORDS_BASIS` and defaults to `DESIGN_BASIS`, and an optional `year`, which defaults to the calendar year of the logical clock."

    Design: Difficulty/dual_variant_calc/operation_production_design_vs_records_basis
    """
    ctx = _operation_with_one_application()
    operation_id = ctx["operation"]["id"]
    headers = ctx["operator_headers"]

    design = validate_success(
        api_client.get_operation_nutrient_summary(
            operation_id, headers, {"basis": "DESIGN_BASIS"}
        ),
        200,
    )
    records = validate_success(
        api_client.get_operation_nutrient_summary(
            operation_id, headers, {"basis": "RECORDS_BASIS"}
        ),
        200,
    )

    assert_quantity(
        design["design_annual_manure_gallons"],
        3374298.00,
        "design basis design_annual_manure_gallons",
    )
    assert_quantity(
        records["recorded_annual_manure_gallons"],
        300000.00,
        "records basis recorded_annual_manure_gallons",
    )

    # Both variants are reported by both reads, so the divergence is visible.
    assert "recorded_annual_manure_gallons" in design, (
        "the design-basis read must still carry the records figure"
    )
    assert "design_annual_manure_gallons" in records, (
        "the records-basis read must still echo the design figure"
    )
    assert_quantity(
        float(records["design_annual_manure_gallons"])
        - float(records["recorded_annual_manure_gallons"]),
        3074298.00,
        "design figure less records figure",
    )

    assert_quantity(
        records["recorded_land_applied_gallons"],
        300000.00,
        "recorded_land_applied_gallons",
    )
    assert_quantity(
        records["recorded_transferred_gallons"],
        0.00,
        "recorded_transferred_gallons",
    )


def test_nutrient_summary_rolls_up_persisted_nutrient_masses_and_echoes_the_operation():
    """The summary reports the year's nutrient roll-up and echoes the design
    storage days and posture alongside it.

    PRD: "The summary response also breaks those two contributions out as `recorded_land_applied_gallons` and `recorded_transferred_gallons`, reports `total_n_applied_lbs` and `total_p2o5_applied_lbs` for the year, and echoes `design_annual_manure_gallons`, `design_storage_days` and `compliance_posture`."
    PRD: "`daily_production_gallons` is `design_annual_manure_gallons` divided by 365, rounded half up to 2 decimal places."

    Design: Difficulty/dual_variant_calc/operation_production_design_vs_records_basis
    """
    ctx = _operation_with_one_application()
    operation_id = ctx["operation"]["id"]
    headers = ctx["operator_headers"]

    records = validate_success(
        api_client.get_operation_nutrient_summary(
            operation_id, headers, {"basis": "RECORDS_BASIS"}
        ),
        200,
    )

    assert_quantity(records["total_n_applied_lbs"], 4680.00, "total_n_applied_lbs")
    assert_quantity(records["total_p2o5_applied_lbs"], 3000.00, "total_p2o5_applied_lbs")
    assert records["design_storage_days"] == 485, (
        f"design_storage_days: expected 485, got {records['design_storage_days']}"
    )
    assert records["compliance_posture"] == "OPEN", (
        f"compliance_posture: expected OPEN, got {records['compliance_posture']}"
    )

    operation = validate_success(api_client.get_operation(operation_id, headers), 200)
    assert_quantity(
        operation["daily_production_gallons"], 9244.65, "daily_production_gallons"
    )


def test_capacity_projection_available_basis_measures_the_headroom_left():
    """The available basis divides the structure's remaining headroom by
    effective daily production, which is a smaller number of days than the
    design basis reports for the same structure.

    PRD: "A structure's own `days_of_storage_available` is the greater of zero and its `available_capacity_gallons`, divided by that effective daily production and floored to a whole day, so the figure shrinks as the structure fills and grows again when a transfer is suspended or cancelled."
    PRD: "It takes an optional `basis` selector of either `AVAILABLE_BASIS` or `DESIGN_BASIS`, defaulting to `AVAILABLE_BASIS`, and returns the `seasonal_factor` and `effective_daily_gallons` in play, the structure's `operating_capacity_gallons` and `available_capacity_gallons`, the resulting `days_of_storage` for the selected basis, and `min_storage_days_met`, indicating whether the 180-day threshold is satisfied."

    Design: Difficulty/dual_variant_calc/storage_days_available_vs_design_basis
    """
    ctx = setup_scenario("STORAGE", intake_gallons=1000000)
    storage_id = ctx["storage"]["id"]
    headers = ctx["operator_headers"]

    available = validate_success(
        api_client.get_storage_capacity_projection(
            storage_id, headers, {"basis": "AVAILABLE_BASIS"}
        ),
        200,
    )

    assert_quantity(
        available["available_capacity_gallons"],
        3488300.00,
        "available_capacity_gallons",
    )
    assert available["days_of_storage"] == 377, (
        f"available-basis days_of_storage: expected 377, got {available['days_of_storage']}"
    )
    assert_quantity(available["seasonal_factor"], 1.0, "seasonal_factor")
    assert_quantity(
        available["effective_daily_gallons"], 9244.65, "effective_daily_gallons"
    )
    assert_four_decimals(available["effective_daily_gallons"], "effective_daily_gallons")
    assert available["min_storage_days_met"] is True, (
        "377 days of available capacity clears the 180-day minimum"
    )


def test_capacity_projection_design_basis_ignores_current_contents():
    """The design basis divides the whole operating capacity, so it stays at 485
    days even though a million gallons are already in the structure, and the
    operation-wide figure agrees with it.

    PRD: "The operation-wide `design_storage_days` is the sum of `operating_capacity_gallons` across every storage structure of the operation, regardless of each structure's `storage_status`, divided by the same effective daily production and floored to a whole day; because it ignores current contents and commitments entirely, it moves only with herd size, structure geometry and the clock's month — and it is this figure that plan certification tests against the 180-day minimum."
    PRD: "`operating_capacity_gallons` is `design_capacity_gallons` less `freeboard_reserve_gallons` — the volume the structure may lawfully hold."

    Design: Difficulty/dual_variant_calc/storage_days_available_vs_design_basis
    """
    ctx = setup_scenario("STORAGE", intake_gallons=1000000)
    operation_id = ctx["operation"]["id"]
    storage_id = ctx["storage"]["id"]
    headers = ctx["operator_headers"]

    design = validate_success(
        api_client.get_storage_capacity_projection(
            storage_id, headers, {"basis": "DESIGN_BASIS"}
        ),
        200,
    )

    assert_quantity(
        design["operating_capacity_gallons"], 4488300.00, "operating_capacity_gallons"
    )
    assert design["days_of_storage"] == 485, (
        f"design-basis days_of_storage: expected 485, got {design['days_of_storage']}"
    )
    assert_quantity(design["seasonal_factor"], 1.0, "seasonal_factor")
    assert_quantity(
        design["effective_daily_gallons"], 9244.65, "effective_daily_gallons"
    )
    assert design["min_storage_days_met"] is True, (
        "485 design days clears the 180-day minimum"
    )

    storage = validate_success(api_client.get_manure_storage(storage_id, headers), 200)
    assert_storage_capacities(
        storage, design=5385960.00, reserve=897660.00, operating=4488300.00
    )
    assert_storage_balance(
        storage,
        intake=1000000.00,
        outflow=0.00,
        current=1000000.00,
        committed=0.00,
        available=3488300.00,
        days=377,
    )

    operation = validate_success(api_client.get_operation(operation_id, headers), 200)
    assert operation["design_storage_days"] == 485, (
        f"design_storage_days: expected 485, got {operation['design_storage_days']}"
    )
