"""Fleet utilization aggregation (PRD §3.12)."""
from test_helpers import (
    TEST_USERS,
    create_railcar,
    setup_active_lease_scenario,
    validate_success,
)

PLANNER = TEST_USERS["fleet_planner_headers"]


class TestFleetUtilization:
    def test_utilization_empty_fleet_returns_zero(self, api):
        """PRD §3.12: "The utilization percentage is 100 times on-lease
        car-days divided by eligible car-days, rounded half-up to two decimal
        places; when there are no eligible car-days at all (an empty fleet),
        the percentage is 0.0 rather than a division error. The response
        carries `month`, `on_lease_car_days`, `eligible_car_days`, and
        `utilization_pct`."

        Design: Corner/calculations/utilization_empty_fleet_returns_zero
        """
        view = validate_success(api.get_fleet_utilization("2026-08", PLANNER))
        assert view["month"] == "2026-08"
        assert view["on_lease_car_days"] == 0
        assert view["eligible_car_days"] == 0
        assert view["utilization_pct"] == 0.0

    def test_utilization_partial_month_mixed_fleet(self, api):
        """PRD §3.12: "Eligible car-days sum, over all railcars, the days of
        the month on which each car was part of the fleet: a car never
        retired during the month contributes all of the month's calendar
        days; a `RETIRED` car contributes the days before the date of its
        `retired_at`; a car created mid-month contributes from the date of
        its `created_at`. On-lease car-days sum, over assignments in
        `ON_LEASE`, `RETURNED`, or `SETTLED`, the overlap in days between the
        assignment's on-lease span — from `actual_on_lease_date` inclusive to
        `actual_off_lease_date` exclusive (or to the end of the month when
        still on lease) — and the month."

        Design: Corner/calculations/utilization_partial_month_mixed_fleet
        """
        # Car A: on lease the whole of August (delivered 2026-08-01 at the
        # default clock, no return). Car B: idle all month.
        setup_active_lease_scenario(car_mark="GATX1301", built_year=2015,
                                    deliver=True)
        create_railcar(car_mark="GATX1302", built_year=2016)
        view = validate_success(api.get_fleet_utilization("2026-08", PLANNER))
        assert view["on_lease_car_days"] == 31
        assert view["eligible_car_days"] == 62
        assert view["utilization_pct"] == 50.0
