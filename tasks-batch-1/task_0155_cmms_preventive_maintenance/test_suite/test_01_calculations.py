"""Calculation rules: PM next-due (meter vs calendar), priority score,
warranty payable (replacement vs repair, cap ordering), MTBF/MTTR, boundary
precision on the meter threshold and stock availability.

Covers Difficulty queue rules dual_variant_calc, combinatorial_formula,
boundary_precision_check, plus the Corner calculations section.
"""
import pytest

from test_helpers import (
    fixtures as fx,
    validate_success,
    validate_paginated,
    TEST_USERS,
)

PLANNER = TEST_USERS["planner_headers"]
MANAGER = TEST_USERS["manager_headers"]
CLERK = TEST_USERS["inventory_clerk_headers"]
TECH = TEST_USERS["technician_headers"]


# =========================================================================
# Rule 1 — dual_variant_calc
# =========================================================================

class TestPmNextDueVariant:
    def test_meter_schedule_populates_next_due_meter_only(self, api):
        """PRD §3.3: "For a meter schedule, next_due_meter is the anchor meter
        plus the meter interval, and next_due_date is null".

        Design: Difficulty/dual_variant_calc/pm_next_due_meter_vs_calendar_variant
        """
        fx.set_clock("2026-01-01T00:00:00Z")
        site, asset = fx.setup_site_and_asset(
            asset_overrides={"criticality": "HIGH", "meter_unit": "HOURS",
                             "acquisition_cost_cents": 5_000_000}
        )
        sched = fx.create_pm_schedule(
            asset["id"], "METER", meter_interval=500, estimated_labor_hours=4, severity="MAJOR"
        )
        data = validate_success(api.get_pm_schedule(sched["id"], PLANNER))
        assert data["next_due_meter"] == 500, "meter next_due = anchor 0 + interval 500"
        assert data["next_due_date"] is None, "meter schedule leaves next_due_date null"

    def test_calendar_schedule_populates_next_due_date_only(self, api):
        """PRD §3.3: "For a calendar schedule, next_due_date is the anchor date
        plus the calendar interval expressed in whole days, and next_due_meter
        is null".

        Design: Difficulty/dual_variant_calc/pm_next_due_meter_vs_calendar_variant
        """
        fx.set_clock("2026-01-01T00:00:00Z")
        site, asset = fx.setup_site_and_asset(
            asset_overrides={"criticality": "HIGH", "acquisition_cost_cents": 5_000_000}
        )
        sched = fx.create_pm_schedule(
            asset["id"], "CALENDAR", calendar_interval_days=30,
            estimated_labor_hours=2, severity="ROUTINE",
        )
        data = validate_success(api.get_pm_schedule(sched["id"], PLANNER))
        assert data["next_due_meter"] is None, "calendar schedule leaves next_due_meter null"
        assert data["next_due_date"] is not None, "calendar schedule populates next_due_date"
        assert data["next_due_date"].startswith("2026-01-31"), (
            f"anchor 2026-01-01 + 30 days == 2026-01-31, got {data['next_due_date']}"
        )


class TestWarrantyPayableVariant:
    def test_replacement_basis_is_acquisition_cost(self, api):
        """PRD §3.9: "The basis, claimed_cost_cents, is the asset's
        acquisition_cost_cents when the claim type is REPLACEMENT and the work
        order's actual_cost_cents when the claim type is REPAIR."
        PRD §3.9: "when the cap is null the payable_cost_cents equals the claimed
        amount".

        Design: Difficulty/dual_variant_calc/warranty_payable_replacement_vs_repair_variant
        """
        site, asset, tech, closed, claim = fx.setup_warranted_closed_wo_with_claim(
            claim_type="REPLACEMENT",
            actual_cost_cents=250_000,
            acquisition_cost_cents=5_000_000,
            warranty_cost_cap_cents=None,
        )
        data = validate_success(
            api.approve_claim(claim["id"], {"decision_reason": "covered"},
                              TEST_USERS["warranty_admin_headers"])
        )
        assert data["claimed_cost_cents"] == 5_000_000
        assert data["payable_cost_cents"] == 5_000_000

    def test_repair_basis_is_work_order_actual_cost(self, api):
        """PRD §3.9: "The basis, claimed_cost_cents, is the asset's
        acquisition_cost_cents when the claim type is REPLACEMENT and the work
        order's actual_cost_cents when the claim type is REPAIR."

        Design: Difficulty/dual_variant_calc/warranty_payable_replacement_vs_repair_variant
        """
        site, asset, tech, closed, claim = fx.setup_warranted_closed_wo_with_claim(
            claim_type="REPAIR",
            actual_cost_cents=250_000,
            acquisition_cost_cents=5_000_000,
            warranty_cost_cap_cents=None,
        )
        data = validate_success(
            api.approve_claim(claim["id"], {"decision_reason": "covered"},
                              TEST_USERS["warranty_admin_headers"])
        )
        assert data["claimed_cost_cents"] == 250_000
        assert data["payable_cost_cents"] == 250_000


# =========================================================================
# Rule 2 — combinatorial_formula
# =========================================================================

class TestPriorityScoreNonlinear:
    def test_meter_pm_priority_score_multiplicative_with_overrun(self, api):
        """PRD §3.4: "The base is the product of the criticality weight, the
        severity weight, and the overrun multiplier. To this base, add 10 when
        the work order is CORRECTIVE and 0 otherwise."
        PRD §3.4: "the raw overrun is the asset's meter_reading divided by the
        larger of the schedule's next_due_meter and 1, then clamped to lie
        between 1.0 and 3.0 inclusive".

        Design: Difficulty/combinatorial_formula/priority_score_nonlinear_multiplicative_mode_a
        """
        fx.set_clock("2026-03-01T00:00:00Z")
        site, asset = fx.setup_site_and_asset(
            asset_overrides={"criticality": "CRITICAL", "meter_unit": "HOURS",
                             "acquisition_cost_cents": 1_000_000}
        )
        sched = fx.create_pm_schedule(
            asset["id"], "METER", meter_interval=500, estimated_labor_hours=4, severity="MAJOR"
        )
        reading = fx.create_meter_reading(asset["id"], 600, "2026-03-01T01:00:00Z")
        assert reading["triggered_pm"] is True
        data, meta = validate_paginated(
            api.list_work_orders(PLANNER, params={"asset_id": asset["id"],
                                                  "pm_schedule_id": sched["id"]})
        )
        assert meta["total_count"] == 1
        wo = data[0]
        assert wo["wo_type"] == "PREVENTIVE"
        assert wo["severity"] == "MAJOR"
        # CRITICAL(8) * MAJOR(3) * clamp(600/500=1.2) = 28.8, no corrective bump.
        assert wo["priority_score"] == pytest.approx(28.8, abs=0.01)

    def test_meter_pm_priority_score_overrun_clamped_at_ceiling(self, api):
        """PRD §3.4: "the raw overrun is the asset's meter_reading divided by the
        larger of the schedule's next_due_meter and 1, then clamped to lie
        between 1.0 and 3.0 inclusive".
        PRD §3.4: "The base is the product of the criticality weight, the
        severity weight, and the overrun multiplier."

        Design: Difficulty/combinatorial_formula/priority_score_nonlinear_multiplicative_mode_a
        """
        fx.set_clock("2026-03-01T00:00:00Z")
        site, asset = fx.setup_site_and_asset(
            asset_overrides={"criticality": "CRITICAL", "meter_unit": "HOURS",
                             "acquisition_cost_cents": 1_000_000}
        )
        sched = fx.create_pm_schedule(
            asset["id"], "METER", meter_interval=500, estimated_labor_hours=4, severity="MAJOR"
        )
        # raw overrun = 2000/500 = 4.0 -> clamped to 3.0 (the inclusive ceiling).
        reading = fx.create_meter_reading(asset["id"], 2000, "2026-03-01T01:00:00Z")
        assert reading["triggered_pm"] is True
        data, meta = validate_paginated(
            api.list_work_orders(PLANNER, params={"pm_schedule_id": sched["id"]})
        )
        assert meta["total_count"] == 1
        # CRITICAL(8) * MAJOR(3) * clamp(4.0)=3.0 = 72.0, no corrective bump.
        assert data[0]["priority_score"] == pytest.approx(72.0, abs=0.01)

    def test_corrective_low_routine_priority_score_with_bump(self, api):
        """PRD §3.4: "in every other case the overrun multiplier is exactly 1.0.
        The base is the product of the criticality weight, the severity weight,
        and the overrun multiplier. To this base, add 10 when the work order is
        CORRECTIVE and 0 otherwise."

        Design: Corner/entities/work_order_priority_score_is_computed_input_ignored
        """
        site, asset = fx.setup_site_and_asset(
            asset_overrides={"criticality": "LOW", "acquisition_cost_cents": 10_000}
        )
        wo = fx.create_corrective_work_order(
            asset["id"], wo_type="CORRECTIVE", severity="ROUTINE", estimated_labor_hours=1
        )
        # LOW(1) * ROUTINE(1) * 1.0 + 10 (corrective) = 11.
        assert wo["priority_score"] == pytest.approx(11, abs=0.01)


class TestWarrantyPayableCapOrdering:
    def test_cap_binds_after_basis_fixed(self, api):
        """PRD §3.9: "On approval the payout is computed in a fixed order: first
        the cost basis, then the cap."
        PRD §3.9: "otherwise it is the smaller of the claimed amount and the cap".

        Design: Difficulty/combinatorial_formula/warranty_payable_pinned_eval_order_mode_c
        """
        site, asset, tech, closed, claim = fx.setup_warranted_closed_wo_with_claim(
            claim_type="REPLACEMENT",
            actual_cost_cents=250_000,
            acquisition_cost_cents=5_000_000,
            warranty_cost_cap_cents=3_000_000,
        )
        data = validate_success(
            api.approve_claim(claim["id"], {"decision_reason": "capped"},
                              TEST_USERS["warranty_admin_headers"])
        )
        assert data["claimed_cost_cents"] == 5_000_000, "basis fixed first from acquisition cost"
        assert data["payable_cost_cents"] == 3_000_000, "then capped at 3,000,000"

    def test_uncapped_replacement_pays_full_basis(self, api):
        """PRD §3.9: "The cap is the asset's warranty_cost_cap_cents: when the cap
        is null the payable_cost_cents equals the claimed amount".

        Design: Difficulty/combinatorial_formula/warranty_payable_pinned_eval_order_mode_c
        """
        site, asset, tech, closed, claim = fx.setup_warranted_closed_wo_with_claim(
            claim_type="REPLACEMENT",
            actual_cost_cents=250_000,
            acquisition_cost_cents=5_000_000,
            warranty_cost_cap_cents=None,
        )
        data = validate_success(
            api.approve_claim(claim["id"], {"decision_reason": "uncapped"},
                              TEST_USERS["warranty_admin_headers"])
        )
        assert data["claimed_cost_cents"] == 5_000_000
        assert data["payable_cost_cents"] == 5_000_000, "no cap -> payable equals claimed"


# =========================================================================
# Rule 6 — boundary_precision_check
# =========================================================================

class TestMeterThresholdBoundary:
    def test_reading_exactly_at_next_due_meter_triggers_pm(self, api):
        """PRD §3.3: "the asset's meter_reading is greater than or equal to
        next_due_meter (the boundary value itself counts as due)."
        PRD §3.3: "for every active meter schedule on the asset that has become
        due, the server auto-creates a preventive work order and marks the
        reading's triggered_pm true."

        Design: Difficulty/boundary_precision_check/meter_pm_due_at_exact_threshold_inclusive
        """
        fx.set_clock("2026-06-01T00:00:00Z")
        site, asset = fx.setup_site_and_asset(
            asset_overrides={"criticality": "MEDIUM", "acquisition_cost_cents": 200_000}
        )
        sched = fx.create_pm_schedule(
            asset["id"], "METER", meter_interval=500, estimated_labor_hours=3, severity="ROUTINE"
        )
        reading = fx.create_meter_reading(asset["id"], 500, "2026-06-01T02:00:00Z")
        assert reading["triggered_pm"] is True, "reading of exactly 500 (>=) is due"
        data, meta = validate_paginated(
            api.list_work_orders(PLANNER, params={"pm_schedule_id": sched["id"]})
        )
        assert meta["total_count"] == 1, "exactly one PREVENTIVE work order generated"
        assert data[0]["wo_type"] == "PREVENTIVE"

    def test_reading_below_next_due_meter_does_not_trigger(self, api):
        """PRD §3.3: "the asset's meter_reading is greater than or equal to
        next_due_meter (the boundary value itself counts as due)."

        Design: Difficulty/boundary_precision_check/meter_pm_due_at_exact_threshold_inclusive
        """
        fx.set_clock("2026-06-01T00:00:00Z")
        site, asset = fx.setup_site_and_asset(
            asset_overrides={"criticality": "MEDIUM", "acquisition_cost_cents": 200_000}
        )
        sched = fx.create_pm_schedule(
            asset["id"], "METER", meter_interval=500, estimated_labor_hours=3, severity="ROUTINE"
        )
        reading = fx.create_meter_reading(asset["id"], 499, "2026-06-01T02:00:00Z")
        assert reading["triggered_pm"] is False, "499 < 500 is not yet due"
        data, meta = validate_paginated(
            api.list_work_orders(PLANNER, params={"pm_schedule_id": sched["id"]})
        )
        assert meta["total_count"] == 0, "no work order generated below threshold"


class TestStockAvailabilityBoundary:
    def test_reserve_exactly_available_units_succeeds(self, api):
        """PRD §3.7: "the part's on_hand_qty minus its reserved_qty must be at
        least the requested qty, otherwise the reservation is rejected with
        ERR_INSUFFICIENT_STOCK."

        Design: Difficulty/boundary_precision_check/stock_reservation_at_exact_available_units_boundary
        """
        site, asset, part, wo = fx.setup_unassigned_wo_with_part(
            on_hand_qty=4, unit_cost_cents=1000, sku="FLT-009"
        )
        resv = validate_success(
            api.create_reservation(
                wo["id"],
                {"spare_part_id": part["id"], "qty": 4,
                 "expected_spare_part_version": part["version"]},
                CLERK,
            ),
            expected_status=201,
        )
        assert resv["status"] == "RESERVED", "reserving exactly 4 of 4 available succeeds"
        refreshed = fx.get_spare_part(part["id"])
        assert refreshed["reserved_qty"] == 4

    def test_reserve_one_over_available_units_rejected(self, api):
        """PRD §3.7: "the part's on_hand_qty minus its reserved_qty must be at
        least the requested qty, otherwise the reservation is rejected with
        ERR_INSUFFICIENT_STOCK."

        Design: Difficulty/boundary_precision_check/stock_reservation_at_exact_available_units_boundary
        """
        from test_helpers import validate_error
        site, asset, part, wo = fx.setup_unassigned_wo_with_part(
            on_hand_qty=4, unit_cost_cents=1000, sku="FLT-010"
        )
        validate_error(
            api.create_reservation(
                wo["id"],
                {"spare_part_id": part["id"], "qty": 5,
                 "expected_spare_part_version": part["version"]},
                CLERK,
            ),
            "ERR_INSUFFICIENT_STOCK",
        )
        refreshed = fx.get_spare_part(part["id"])
        assert refreshed["reserved_qty"] == 0, "rejected reservation leaves reserved_qty unchanged"


# =========================================================================
# Corner — calculations section (MTBF / MTTR / calendar generate-due)
# =========================================================================

class TestReliabilityMetrics:
    def test_mtbf_excludes_non_failure_reason_codes(self, api):
        """PRD §3.8: "Mean time between failures considers the asset's downtime
        rows whose reason code is MECHANICAL_FAILURE or ELECTRICAL_FAILURE,
        regardless of whether they are open or resolved, ordered by started_at
        ascending and breaking ties by created_at ascending."
        PRD §3.8: "it is the mean of the consecutive start-to-start gaps — for
        each adjacent pair, the difference between the later event's started_at
        and the earlier event's started_at divided by 3600 seconds — rounded
        half-up to two decimal places."

        Design: Corner/calculations/mtbf_excludes_non_failure_reason_codes
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        site, asset = fx.setup_site_and_asset()
        d1 = fx.open_downtime(asset["id"], "MECHANICAL_FAILURE", "2026-05-01T00:00:00Z")
        fx.resolve_downtime(d1["id"], "2026-05-01T01:00:00Z")
        d2 = fx.open_downtime(asset["id"], "OPERATOR_ERROR", "2026-05-01T02:00:00Z")
        fx.resolve_downtime(d2["id"], "2026-05-01T02:30:00Z")
        fx.open_downtime(asset["id"], "ELECTRICAL_FAILURE", "2026-05-01T04:00:00Z")
        data = validate_success(api.get_asset(asset["id"], MANAGER))
        # Failures at +0h and +4h -> single 4h start-to-start gap; operator error excluded.
        assert data["mtbf_hours"] == pytest.approx(4, abs=0.01)

    def test_mtbf_single_failure_returns_zero(self, api):
        """PRD §3.8: "If fewer than two such failures exist, mtbf_hours is 0".

        Design: Corner/calculations/mtbf_single_failure_returns_zero
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        site, asset = fx.setup_site_and_asset()
        fx.open_downtime(asset["id"], "MECHANICAL_FAILURE", "2026-05-01T00:00:00Z")
        data = validate_success(api.get_asset(asset["id"], MANAGER))
        assert data["mtbf_hours"] == 0

    def test_mttr_averages_only_resolved_failure_durations(self, api):
        """PRD §3.8: "Mean time to repair considers only resolved failure-class
        downtime rows for the asset; if there are none, mttr_hours is 0,
        otherwise it is the mean of those events' duration_hours rounded half-up
        to two decimal places."

        Design: Corner/calculations/mttr_averages_only_resolved_failure_durations
        """
        fx.set_clock("2026-05-01T00:00:00Z")
        site, asset = fx.setup_site_and_asset()
        d1 = fx.open_downtime(asset["id"], "MECHANICAL_FAILURE", "2026-05-01T00:00:00Z")
        fx.resolve_downtime(d1["id"], "2026-05-01T04:00:00Z")
        d2 = fx.open_downtime(asset["id"], "ELECTRICAL_FAILURE", "2026-05-01T10:00:00Z")
        fx.resolve_downtime(d2["id"], "2026-05-01T16:00:00Z")
        data = validate_success(api.get_asset(asset["id"], MANAGER))
        # (4h + 6h) / 2 = 5h.
        assert data["mttr_hours"] == pytest.approx(5, abs=0.01)


class TestCalendarGenerateDue:
    def test_generate_due_before_due_date_rejected(self, api):
        """PRD §3.3: "Calendar schedules — and any manual sweep — are evaluated
        through an explicit generate-due capability available to a Planner or
        MaintenanceManager: if the schedule is due it creates a preventive work
        order, and if it is not yet due the request is rejected with
        ERR_PM_NOT_DUE."

        Design: Corner/calculations/calendar_pm_generate_due_before_due_returns_not_due
        """
        from test_helpers import validate_error
        fx.set_clock("2026-01-01T00:00:00Z")
        site, asset = fx.setup_site_and_asset()
        sched = fx.create_pm_schedule(
            asset["id"], "CALENDAR", calendar_interval_days=30,
            estimated_labor_hours=2, severity="ROUTINE",
        )
        fx.set_clock("2026-01-15T00:00:00Z")
        validate_error(api.generate_due(sched["id"], PLANNER), "ERR_PM_NOT_DUE")

    def test_generate_due_at_threshold_creates_work_order(self, api):
        """PRD §3.3: "the schedule is due when the current clock instant is
        greater than or equal to next_due_date (again, the boundary instant
        counts as due)."
        PRD §3.4: "in every other case the overrun multiplier is exactly 1.0."

        Design: Corner/calculations/calendar_pm_generate_due_at_threshold_creates_work_order
        """
        fx.set_clock("2026-01-01T00:00:00Z")
        site, asset = fx.setup_site_and_asset(
            asset_overrides={"criticality": "MEDIUM", "acquisition_cost_cents": 100}
        )
        sched = fx.create_pm_schedule(
            asset["id"], "CALENDAR", calendar_interval_days=30,
            estimated_labor_hours=2, severity="ROUTINE",
        )
        fx.set_clock("2026-01-31T00:00:00Z")
        wo = validate_success(api.generate_due(sched["id"], PLANNER), expected_status=201)
        assert wo["wo_type"] == "PREVENTIVE"
        # MEDIUM(2) * ROUTINE(1) * overrun 1.0 (calendar) + 0 = 2.
        assert wo["priority_score"] == pytest.approx(2, abs=0.01)
