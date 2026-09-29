"""The two costing engines that each expose two variants over one data set."""

from test_helpers import (
    PAYROLL,
    MANAGER,
    get_success_data,
    setup_f1,
    validate_paginated,
)


def _f1_completed():
    """The canonical trip, closed out on 340 drive and 560 duty minutes."""
    return setup_f1(stage="completed", actual_drive_minutes=340, actual_duty_minutes=560)


def test_planned_accrual_preview_reports_a_structurally_zero_hourly_component(api):
    """PRD §3.8: "Note the structural consequence: under `PLANNED_ACCRUAL` the duty
    basis *is* the planned duty figure, so detention is always zero and the hourly
    component is always zero."

    Design: Difficulty/dual_variant_calc/trip_pay_planned_accrual_vs_final_settlement_diverge_by_detention
    """
    ctx = _f1_completed()
    preview = get_success_data(
        api.get_pay_preview(ctx["trip"]["id"], PAYROLL, {"variant": "PLANNED_ACCRUAL"})
    )
    assert preview["variant"] == "PLANNED_ACCRUAL"
    assert preview["hourly_cents"] == 0
    assert preview["mileage_cents"] == 21294
    assert preview["activity_cents"] == 5900
    assert preview["bonus_cents"] == 0
    assert preview["subtotal_cents"] == 27194
    assert preview["guarantee_makeup_cents"] == 0
    assert preview["gross_cents"] == 27194
    assert ctx["trip"]["planned_pay_cents"] == 27194


def test_final_settlement_preview_prices_the_detention_the_accrual_cannot_see(api):
    """PRD §3.8: "Take the duty basis — under `FINAL_SETTLEMENT` that is the trip's
    `actual_duty_minutes`, and under `PLANNED_ACCRUAL` it is the trip's
    `planned_duty_minutes` — subtract the trip's `planned_duty_minutes`, and subtract
    a further thirty minutes of grace."

    Design: Difficulty/dual_variant_calc/trip_pay_planned_accrual_vs_final_settlement_diverge_by_detention
    """
    ctx = _f1_completed()
    trip_id = ctx["trip"]["id"]
    assert ctx["trip"]["planned_duty_minutes"] == 505
    assert ctx["trip"]["actual_duty_minutes"] == 560

    planned = get_success_data(
        api.get_pay_preview(trip_id, PAYROLL, {"variant": "PLANNED_ACCRUAL"})
    )
    final = get_success_data(
        api.get_pay_preview(trip_id, PAYROLL, {"variant": "FINAL_SETTLEMENT"})
    )
    assert final["variant"] == "FINAL_SETTLEMENT"
    assert final["hourly_cents"] == 1050
    assert final["gross_cents"] == 28244
    assert final["gross_cents"] - planned["gross_cents"] == 1050
    assert ctx["trip"]["driver_pay_cents"] == 28244


def test_only_the_final_settlement_variant_is_ever_persisted_on_a_statement(api):
    """PRD §3.8: "`FINAL_SETTLEMENT` runs at close-out and at re-accrual, writes the
    trip's `driver_pay_cents`, and is the only variant ever persisted on a pay
    statement."

    Design: Difficulty/dual_variant_calc/trip_pay_planned_accrual_vs_final_settlement_diverge_by_detention
    """
    ctx = _f1_completed()
    rows, meta = validate_paginated(
        api.list_pay_statements(PAYROLL, {"trip_id": ctx["trip"]["id"]})
    )
    assert meta["total_count"] == 1
    statement = rows[0]
    assert statement["variant"] == "FINAL_SETTLEMENT"
    assert statement["mileage_cents"] == 21294
    assert statement["activity_cents"] == 5900
    assert statement["hourly_cents"] == 1050
    assert statement["bonus_cents"] == 0
    assert statement["guarantee_makeup_cents"] == 0
    assert statement["gross_cents"] == 28244

    accrual_rows, accrual_meta = validate_paginated(
        api.list_pay_statements(PAYROLL, {"variant": "PLANNED_ACCRUAL"})
    )
    assert accrual_meta["total_count"] == 0
    assert accrual_rows == []


def test_fully_allocated_benchmark_adds_the_fixed_pool_to_the_variable_base(api):
    """PRD §3.8: "Under the `FULLY_ALLOCATED` variant — the comparison to make against
    a dedicated-carriage quote, since a carrier's quote embeds its own equipment and
    overhead — `total_cost_cents` is `variable_cost_cents` plus `fixed_cost_cents`."

    Design: Difficulty/dual_variant_calc/domicile_benchmark_fully_allocated_vs_incremental_variable_diverge
    """
    ctx = _f1_completed()
    report = get_success_data(
        api.get_cost_benchmark(
            ctx["domicile"]["id"],
            MANAGER,
            {
                "variant": "FULLY_ALLOCATED",
                "window_start": "2026-08-01T00:00:00Z",
                "window_end": "2026-08-08T00:00:00Z",
            },
        )
    )
    assert report["variant"] == "FULLY_ALLOCATED"
    assert report["window_days"] == 7
    assert report["fixed_cost_cents"] == 112000
    assert report["variable_cost_cents"] == 50357
    assert report["total_cost_cents"] == 162357
    assert report["cost_per_case_cents"] == 180
    assert report["cost_per_mile_cents"] == 595
    assert report["advantage_cents_per_case"] == 30
    assert report["dedicated_equivalent_cents_per_case"] == 210


def test_incremental_variable_benchmark_excludes_the_fixed_pool_from_the_total(api):
    """PRD §3.8: "Under the `INCREMENTAL_VARIABLE` variant — the comparison to make
    when deciding whether to take one more load on equipment already owned —
    `total_cost_cents` is `variable_cost_cents` alone, with all fixed and overhead
    cost excluded."

    Design: Difficulty/dual_variant_calc/domicile_benchmark_fully_allocated_vs_incremental_variable_diverge
    """
    ctx = _f1_completed()
    report = get_success_data(
        api.get_cost_benchmark(
            ctx["domicile"]["id"],
            MANAGER,
            {
                "variant": "INCREMENTAL_VARIABLE",
                "window_start": "2026-08-01T00:00:00Z",
                "window_end": "2026-08-08T00:00:00Z",
            },
        )
    )
    assert report["variant"] == "INCREMENTAL_VARIABLE"
    assert report["window_days"] == 7
    assert report["fixed_cost_cents"] == 112000
    assert report["total_cost_cents"] == 50357
    assert report["cost_per_case_cents"] == 56
    assert report["cost_per_mile_cents"] == 184
    assert report["advantage_cents_per_case"] == 154


def test_both_benchmark_variants_read_the_identical_volume_and_variable_base(api):
    """PRD §3.8: "`variable_cost_cents` is driver pay plus fuel plus maintenance,
    **less** the backhaul credit — the backhaul earns its keep by reducing the cost
    base."

    Design: Difficulty/dual_variant_calc/domicile_benchmark_fully_allocated_vs_incremental_variable_diverge
    """
    ctx = _f1_completed()
    window = {
        "window_start": "2026-08-01T00:00:00Z",
        "window_end": "2026-08-08T00:00:00Z",
    }
    reports = [
        get_success_data(
            api.get_cost_benchmark(
                ctx["domicile"]["id"], MANAGER, dict(window, variant=variant)
            )
        )
        for variant in ("FULLY_ALLOCATED", "INCREMENTAL_VARIABLE")
    ]
    for report in reports:
        assert report["trip_count"] == 1
        assert report["total_miles"] == 273
        assert report["total_cases"] == 900
        assert report["driver_pay_cents"] == 28244
        assert report["fuel_cents"] == 16926
        assert report["maintenance_cents"] == 5187
        assert report["backhaul_credit_cents"] == 0
        assert report["variable_cost_cents"] == 50357
    assert reports[0]["total_cost_cents"] - reports[1]["total_cost_cents"] == 112000
