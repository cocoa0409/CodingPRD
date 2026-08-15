"""PM policy validation, due-status boundaries, projection variants, and the
PM nesting reset on close."""
from test_helpers import (
    ApiErrorId,
    add_labor,
    create_in_progress_wo,
    create_pm_policy_payload,
    get_success_data,
    make_mechanic_headers,
    new_bus,
    new_mechanic_with_certs,
    new_pm_policy,
    new_qa_mechanic,
    new_work_order,
    post_log,
    schedule_wo,
    start_wo,
    validate_error,
    validate_success,
    wo_event,
)
from test_helpers import fixtures as fx


def test_pm_policy_non_nested_intervals_rejected(api, fleet_manager_headers):
    """PRD §3.2: "The three mileage intervals must nest as positive multiples —
    `level_b_interval_miles` must be a positive multiple of
    `level_a_interval_miles`, and `level_c_interval_miles` a positive multiple
    of `level_b_interval_miles` — and `tolerance_miles` must be strictly less
    than `level_a_interval_miles`. A policy failing any of these is rejected
    with `ERR_PM_POLICY_INVALID`."

    Design: Corner/validations/pm_policy_non_nested_intervals_rejected
    """
    res = api.create_pm_policy(
        create_pm_policy_payload(level_b_interval_miles=7_000),
        fleet_manager_headers,
    )
    validate_error(res, ApiErrorId.ERR_PM_POLICY_INVALID)
    policies = get_success_data(api.list_pm_policies(fleet_manager_headers))
    assert policies == [], "an invalid policy must not be persisted"


class TestPmIntervalBoundary:
    """miles_remaining == 0 maps to DUE, not OVERDUE (policy A=6000 tol=500)."""

    def _setup(self):
        new_pm_policy()
        bus = new_bus(fleet_number="M1", vin="VINM1", model_year=2024,
                      in_service_date="2026-07-01", initial_odometer_miles=0)
        return bus

    def test_due_soon_then_due_at_exact_interval(self, api):
        """PRD §3.2: "The **mileage status** for level L is: `CURRENT` when the
        remaining miles (I minus `miles_since_L`) are strictly greater than
        `tolerance_miles`; `DUE_SOON` when remaining miles are between 1 and
        `tolerance_miles` inclusive; `DUE` when remaining miles are exactly
        zero; and `OVERDUE` when remaining miles are negative."

        Design: Difficulty/boundary_precision_check/pm_interval_exact_boundary_due_not_overdue
        """
        bus = self._setup()
        post_log(bus["id"], "2026-08-01", 5_999, 60)
        status = get_success_data(api.get_bus_pm_status(bus["id"], fx.FM))
        assert status["miles_remaining_a"] == 1
        assert status["pm_due_status"] == "DUE_SOON", "remaining 1 is within tol 500"

        post_log(bus["id"], "2026-08-01", 6_000, 60)
        status = get_success_data(api.get_bus_pm_status(bus["id"], fx.FM))
        assert status["miles_remaining_a"] == 0
        assert status["pm_due_status"] == "DUE", (
            "exactly at the interval maps to DUE, not OVERDUE"
        )

    def test_one_mile_past_interval_is_overdue(self, api):
        """PRD §3.2: "The **mileage status** for level L is: `CURRENT` when the
        remaining miles (I minus `miles_since_L`) are strictly greater than
        `tolerance_miles`; `DUE_SOON` when remaining miles are between 1 and
        `tolerance_miles` inclusive; `DUE` when remaining miles are exactly
        zero; and `OVERDUE` when remaining miles are negative."

        Design: Difficulty/boundary_precision_check/pm_interval_exact_boundary_due_not_overdue
        """
        bus = self._setup()
        post_log(bus["id"], "2026-08-01", 6_000, 60)
        status = get_success_data(api.get_bus_pm_status(bus["id"], fx.FM))
        assert status["pm_due_status"] == "DUE"
        assert status["miles_remaining_a"] == 0

        post_log(bus["id"], "2026-08-01", 6_001, 60)
        status = get_success_data(api.get_bus_pm_status(bus["id"], fx.FM))
        assert status["miles_remaining_a"] == -1
        assert status["pm_due_status"] == "OVERDUE", "negative remaining is OVERDUE"


class TestPmProjectionVariants:
    """MILEAGE_RATE vs CALENDAR on identical odometer history."""

    def _setup(self):
        new_pm_policy()
        bus = new_bus(fleet_number="B1", vin="VIN1", model_year=2023,
                      in_service_date="2026-06-01", initial_odometer_miles=0,
                      base_warranty_expiry_miles=150_000,
                      base_warranty_expiry_date="2028-06-01")
        post_log(bus["id"], "2026-07-29", 1_000, 50)
        post_log(bus["id"], "2026-07-30", 2_000, 50)
        post_log(bus["id"], "2026-07-31", 3_000, 50)
        return bus

    def test_mileage_rate_projects_from_observed_utilization(self, api):
        """PRD §3.2: "If fewer than 3 such logs exist, `avg_daily_miles` falls
        back to 200; otherwise it is the sum of `miles_driven` over the
        baseline logs divided by the number of days between the first and last
        baseline `log_date` (guarded to at least 1), rounded half-up. The
        projected `days_to_due` is the greater of zero and the ceiling of
        `miles_remaining_a` divided by `avg_daily_miles`, and
        `projected_due_date` is the logical clock date plus that many days."

        3000 miles over 2 days -> avg 1500; remaining 3000 -> 2 days ->
        due 2026-08-03 (clock 2026-08-01).

        Design: Difficulty/dual_variant_calc/pm_projection_mileage_rate_vs_calendar_divergence
        """
        bus = self._setup()
        status = get_success_data(
            api.get_bus_pm_status(bus["id"], fx.SUP,
                                  params={"variant": "MILEAGE_RATE"})
        )
        assert status["projection_variant"] == "MILEAGE_RATE"
        assert status["avg_daily_miles"] == 1_500
        assert status["miles_remaining_a"] == 3_000
        assert status["projected_due_date"] == "2026-08-03"
        assert status["pm_due_status"] == "CURRENT", (
            "3000 remaining > 500 tolerance; 61 days elapsed < 166 remaining"
        )

    def test_calendar_variant_ignores_odometer_history(self, api):
        """PRD §3.2: "Under `CALENDAR`, the projection ignores odometer history
        entirely and reports `projected_due_date` as `last_pm_a_date` plus
        `calendar_interval_days`."

        last_pm_a_date seeds from in_service_date 2026-06-01; +180 days ->
        2026-11-28, diverging from the MILEAGE_RATE projection.

        Design: Difficulty/dual_variant_calc/pm_projection_mileage_rate_vs_calendar_divergence
        """
        bus = self._setup()
        cal = get_success_data(
            api.get_bus_pm_status(bus["id"], fx.SUP, params={"variant": "CALENDAR"})
        )
        assert cal["projection_variant"] == "CALENDAR"
        assert cal["projected_due_date"] == "2026-11-28"
        assert cal["pm_due_status"] == "CURRENT"

        mr = get_success_data(
            api.get_bus_pm_status(bus["id"], fx.SUP,
                                  params={"variant": "MILEAGE_RATE"})
        )
        assert mr["projected_due_date"] != cal["projected_due_date"], (
            "same bus data, two valid algorithms, different dates"
        )


def test_pm_c_close_resets_nested_counters(api):
    """PRD §3.2: "When a PM work order closes, the closing odometer and
    `closed_date` reset a nested subset of fields: a `PM_C` close resets all
    three levels; a `PM_B` close resets A and B; a `PM_A` close resets A only.
    In each case the reset writes `last_pm_<level>_miles` to the bus's odometer
    at close and `last_pm_<level>_date` to the work order's `closed_date`."

    Design: Corner/calculations/pm_c_close_resets_nested_counters
    """
    new_pm_policy()
    bus = new_bus(fleet_number="PM1", vin="VINPM1", model_year=2023,
                  in_service_date="2026-07-01", initial_odometer_miles=0)
    post_log(bus["id"], "2026-08-01", 36_000, 300)
    lead = new_mechanic_with_certs("PM_INSPECTION", name="Lead")
    qa = new_qa_mechanic()

    wo = new_work_order(bus["id"], wo_type="PM_C", lead_mechanic_id=lead["id"],
                        estimated_labor_hours=8, estimated_cost_cents=52_000)
    schedule_wo(wo["id"])
    start_wo(wo["id"])
    add_labor(wo["id"], lead, hours=8)
    wo_event(wo["id"], "SUBMIT_QA", headers=make_mechanic_headers(lead["id"]))
    validate_success(
        wo_event(wo["id"], "QA_CERTIFY", headers=make_mechanic_headers(qa["id"]))
    )

    bus_after = get_success_data(api.get_bus(bus["id"], fx.FM))
    assert bus_after["last_pm_a_miles"] == 36_000
    assert bus_after["last_pm_b_miles"] == 36_000
    assert bus_after["last_pm_c_miles"] == 36_000, (
        "a PM_C close resets all three levels to the close odometer"
    )

    status = get_success_data(api.get_bus_pm_status(bus["id"], fx.FM))
    assert status["miles_since_pm_a"] == 0
    assert status["miles_since_pm_b"] == 0
    assert status["miles_since_pm_c"] == 0
    assert status["pm_due_status"] == "CURRENT"
