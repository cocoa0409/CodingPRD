"""The building KPI dashboard: pinned empty-set semantics, and the containment and
meter-type filters that decide which readings feed the energy figures.
"""

import pytest

from test_helpers import (
    TEST_USERS,
    assert_building_kpi,
    create_building,
    create_space,
    create_utility_reading,
    set_clock,
    validate_success,
)

SA = TEST_USERS["sustainability_analyst_headers"]

MAY_START = "2026-05-01T00:00:00Z"
MAY_END = "2026-05-31T23:59:59Z"


def test_kpi_empty_sets_report_full_compliance_not_zero(api):
    """PRD §3.9: "The empty-set behaviour of each figure is pinned, because a building
    with nothing in it must not report a division by zero. With no completed dispatches,
    `sla_compliance_pct` is 100.00. With no active plans, `pm_compliance_pct` is 100.00.
    With no readings inside the window, `energy_intensity_kwh_per_sqm` is 0.0 and
    `total_utility_cost` is 0.00. With no occupied spaces, `occupancy_pct` is 0.00."

    Design: Difficulty/boundary_precision_check/kpi_empty_sets_return_full_compliance_not_zero
    """
    set_clock("2026-05-04T09:00:00Z")
    building = create_building(gross_area_sqm=1000)
    create_space(building["id"], space_code="S1", area_sqm=200, space_type="OFFICE")

    data = validate_success(
        api.get_building_kpi(
            building["id"], SA,
            params={"window_start": MAY_START, "window_end": MAY_END},
        )
    )
    assert_building_kpi(data)

    assert data["sla_compliance_pct"] == pytest.approx(100.00, abs=0.01), (
        "an empty set of completed dispatches is full compliance, not zero"
    )
    assert data["pm_compliance_pct"] == pytest.approx(100.00, abs=0.01), (
        "an empty set of active plans is full compliance, not zero"
    )


def test_kpi_empty_sums_report_zero(api):
    """PRD §3.9: "The empty-set behaviour of each figure is pinned, because a building
    with nothing in it must not report a division by zero. With no completed dispatches,
    `sla_compliance_pct` is 100.00. With no active plans, `pm_compliance_pct` is 100.00.
    With no readings inside the window, `energy_intensity_kwh_per_sqm` is 0.0 and
    `total_utility_cost` is 0.00. With no occupied spaces, `occupancy_pct` is 0.00."
    PRD §3.9: "And `posture` simply echoes the building's current `operating_posture`."
    PRD §3.9: "`open_work_order_count` is the number of the building's work orders whose
    `status` is `NEW`, `DISPATCHED`, `IN_PROGRESS`, or `PENDING_QA`."

    Design: Difficulty/boundary_precision_check/kpi_empty_sets_return_full_compliance_not_zero
    """
    set_clock("2026-05-04T09:00:00Z")
    building = create_building(gross_area_sqm=1000)
    create_space(building["id"], space_code="S1", area_sqm=200, space_type="OFFICE")

    data = validate_success(
        api.get_building_kpi(
            building["id"], SA,
            params={"window_start": MAY_START, "window_end": MAY_END},
        )
    )
    assert_building_kpi(data)

    assert data["occupancy_pct"] == pytest.approx(0.00, abs=0.01), (
        "the one space is VACANT, so nothing is occupied"
    )
    assert data["energy_intensity_kwh_per_sqm"] == pytest.approx(0.0, abs=0.001)
    assert data["total_utility_cost"] == pytest.approx(0.00, abs=0.01)
    assert data["open_work_order_count"] == 0
    assert data["posture"] == "OPEN"


def test_kpi_energy_excludes_water_and_readings_that_straddle_the_window(api):
    """PRD §3.9: "Only the building's utility readings whose own inclusive metered period
    is *fully contained* in the window contribute to the energy figures.
    `energy_intensity_kwh_per_sqm` is the sum of `consumption_kwh` over those contained
    readings whose `meter_type` is `ELECTRIC` or `GAS` — water is deliberately excluded
    from intensity — divided by the building's `gross_area_sqm`, rounded half up to 3
    decimal places. `total_utility_cost` is the sum of `cost` over those same contained
    readings across all three meter types, rounded half up to 2 decimal places."

    Design: Corner/calculations/kpi_energy_excludes_water_and_partially_contained_readings
    """
    set_clock("2026-06-01T09:00:00Z")
    building = create_building(gross_area_sqm=1000)
    create_utility_reading(building["id"], meter_type="ELECTRIC",
                           period_start=MAY_START, period_end=MAY_END,
                           consumption_kwh=3000, cost=600.00)
    create_utility_reading(building["id"], meter_type="WATER",
                           period_start=MAY_START, period_end=MAY_END,
                           consumption_kwh=0, cost=100.00)
    # This GAS reading straddles the window edge and must contribute to neither figure.
    create_utility_reading(building["id"], meter_type="GAS",
                           period_start="2026-04-25T00:00:00Z",
                           period_end="2026-05-05T23:59:59Z",
                           consumption_kwh=5000, cost=900.00)

    data = validate_success(
        api.get_building_kpi(
            building["id"], SA,
            params={"window_start": MAY_START, "window_end": MAY_END},
        )
    )
    assert_building_kpi(data)

    assert data["energy_intensity_kwh_per_sqm"] == pytest.approx(3.0, abs=0.001), (
        "only the contained ELECTRIC reading counts: 3000 kWh over 1000 sqm"
    )
    assert data["total_utility_cost"] == pytest.approx(700.00, abs=0.01), (
        "600.00 ELECTRIC plus 100.00 WATER; the straddling GAS reading is excluded"
    )
    assert data["occupancy_pct"] == pytest.approx(0.00, abs=0.01)
    assert data["posture"] == "OPEN"
