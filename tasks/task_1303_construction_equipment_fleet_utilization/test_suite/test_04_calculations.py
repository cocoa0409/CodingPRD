"""Calculation rules: rental_allocation, own_vs_rent, utilization_rate,
fuel_burn_rate, residual_value, damage_chargeback, redeployment_scan."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_assignment_charge,
    close_assignment,
    confirm_damage,
    dispute_damage,
    assess_damage,
    get_success_data,
    make_active_assignment,
    make_class,
    make_damage_report,
    make_equipment,
    make_fleet_bundle,
    make_project,
    make_reading,
    make_reserved_assignment,
    reassess_damage,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

_ADMIN = TEST_USERS["fleet_admin_headers"]


# ============================================================================
# Difficulty / dual_variant_calc
# ============================================================================

class TestOwnVsRentVariantsDiverge:
    def _setup_and_close(self, api):
        """Shared chain: Mon 2026-08-03 .. Wed 2026-08-05 chargeable window with
        one idle day, then close on 2026-08-06."""
        set_clock("2026-08-03T09:00:00Z")
        cls = make_class(
            class_code="EXC-320", daily_rate_cents=10000, external_daily_rate_cents=12000,
            weekend_multiplier_bp=5000, idle_day_multiplier_bp=5000,
            service_interval_hours=10000,
        )
        project = make_project(project_code="PRJ-A")
        equip = make_equipment(cls["id"], unit_tag="UNIT-1")
        asg = make_active_assignment(equip, project, start_date="2026-08-03", end_date="2026-08-09")
        make_reading(equip["id"], recorded_date="2026-08-03",
                     engine_hours_delta_milli=8000, fuel_used_milliliters=4000)
        make_reading(equip["id"], recorded_date="2026-08-04",
                     engine_hours_delta_milli=0, fuel_used_milliliters=0)
        make_reading(equip["id"], recorded_date="2026-08-05",
                     engine_hours_delta_milli=8000, fuel_used_milliliters=4000)
        set_clock("2026-08-06T09:00:00Z")
        close_assignment(asg["id"])
        return cls, project, equip, asg

    def test_own_rent_variants_diverge_and_cheaper_is_rent(self, api):
        """PRD section 3.6: "The `RENT` variant, `rent_cost_cents`, ignores
        usage entirely: `billable_days` times the class
        `external_daily_rate_cents`, plus `billable_days` times an
        external-rental admin fee of 1500 cents per day. ... `cheaper_variant`
        records `OWN` when the own cost is strictly less, `RENT` when the rent
        cost is strictly less, and `TIE` when they are equal."

        Design: Difficulty/dual_variant_calc/own_vs_rent_variants_diverge_on_mixed_idle_window
        """
        _, project, _, asg = self._setup_and_close(api)
        rows, _ = validate_paginated(api.list_assignment_charges(asg["id"], _ADMIN))
        assert len(rows) == 1
        charge = rows[0]
        assert_assignment_charge(charge)
        assert charge["allocated_cents"] == 25000
        assert charge["own_cost_cents"] == 52000
        assert charge["rent_cost_cents"] == 40500
        assert charge["own_cost_cents"] != charge["rent_cost_cents"]
        assert charge["cheaper_variant"] == "RENT"

    def test_close_posts_allocated_to_project_ledger(self, api):
        """PRD section 3.6: "`allocated_cents` posts to the project's
        `billed_total_cents`." Window: 08-03 active 8000 milli (10000),
        08-04 idle (round(10000*5000/10000)=5000), 08-05 active 8000
        (10000) -> allocated 25000.

        Design: Difficulty/dual_variant_calc/own_vs_rent_variants_diverge_on_mixed_idle_window
        """
        _, project, _, asg = self._setup_and_close(api)
        asg_after = validate_success(api.get_assignment(asg["id"], _ADMIN))
        assert asg_after["billable_days"] == 3
        assert asg_after["idle_days"] == 1
        assert asg_after["engine_hours_billed_milli"] == 16000
        proj_after = validate_success(api.get_project(project["id"], _ADMIN))
        assert proj_after["billed_total_cents"] == 25000


class TestResidualValueVariants:
    def test_sale_straight_line_residual(self, api):
        """PRD section 3.9: "A `SALE` uses the **straight-line** variant: the
        unit's age is measured in whole calendar months between
        `acquisition_date` and the disposal date ... the residual is the
        acquisition cost minus the depreciation rounded half-up to whole
        cents." For acquisition_cost 5800000, salvage 100000, age 12 of 24
        months: residual = 5800000 - round(5700000*12/24) = 2950000.

        Design: Difficulty/dual_variant_calc/residual_value_sale_vs_scrap_variants_diverge
        """
        set_clock("2026-08-01T00:00:00Z")
        cls = make_class(class_code="DOZ-D6", expected_life_hours=480,
                         salvage_value_cents=100000, service_interval_hours=10000)
        ea = make_equipment(cls["id"], unit_tag="UNIT-A",
                            acquisition_cost_cents=5800000,
                            acquisition_date="2025-08-01", useful_life_months=24)
        disposed = validate_success(
            api.dispose_equipment(ea["id"], {"disposal_method": "SALE"}, _ADMIN)
        )
        assert disposed["availability_status"] == "DISPOSED"
        assert disposed["residual_value_cents"] == 2950000

    def test_scrap_hour_based_residual_diverges_from_sale(self, api):
        """PRD section 3.9: "A `SCRAP` uses the **hour-based** variant: the
        meter is read as exact hours ... depreciation is the same depreciable
        base multiplied by the lesser of the hours used and the class
        `expected_life_hours` ... Both variants then floor at the class
        `salvage_value_cents`." For 5800000 cost, 100000 salvage, 120 of 480
        hours: residual = 5800000 - round(5700000*120/480) = 4375000.

        Design: Difficulty/dual_variant_calc/residual_value_sale_vs_scrap_variants_diverge
        """
        set_clock("2026-08-01T00:00:00Z")
        cls = make_class(class_code="DOZ-D6", expected_life_hours=480,
                         salvage_value_cents=100000, service_interval_hours=10000)
        ea = make_equipment(cls["id"], unit_tag="UNIT-A",
                            acquisition_cost_cents=5800000,
                            acquisition_date="2025-08-01", useful_life_months=24)
        eb = make_equipment(cls["id"], unit_tag="UNIT-B",
                            acquisition_cost_cents=5800000,
                            acquisition_date="2025-08-01", useful_life_months=24)
        for day in ("2026-07-20", "2026-07-21", "2026-07-22", "2026-07-23", "2026-07-24"):
            make_reading(eb["id"], recorded_date=day,
                         engine_hours_delta_milli=24000, fuel_used_milliliters=12000)

        sale = validate_success(api.dispose_equipment(ea["id"], {"disposal_method": "SALE"}, _ADMIN))
        scrap = validate_success(api.dispose_equipment(eb["id"], {"disposal_method": "SCRAP"}, _ADMIN))
        assert sale["residual_value_cents"] == 2950000
        assert scrap["residual_value_cents"] == 4375000
        assert sale["residual_value_cents"] != scrap["residual_value_cents"]
        assert sale["residual_value_cents"] >= 100000
        assert scrap["residual_value_cents"] >= 100000


class TestUtilizationVariantsDiverge:
    def _setup_suspended_window(self, api):
        """Build the 7-calendar-day window with one fully suspended day."""
        set_clock("2026-08-03T09:00:00Z")
        cls = make_class(class_code="EXC-330", daily_rate_cents=10000,
                         weekend_multiplier_bp=5000, idle_day_multiplier_bp=5000,
                         service_interval_hours=10000)
        project = make_project(project_code="PRJ-C")
        equip = make_equipment(cls["id"], unit_tag="UNIT-3")
        asg = make_active_assignment(equip, project, start_date="2026-08-03", end_date="2026-08-10")
        make_reading(equip["id"], recorded_date="2026-08-03",
                     engine_hours_delta_milli=8000, fuel_used_milliliters=4000)
        make_reading(equip["id"], recorded_date="2026-08-04",
                     engine_hours_delta_milli=4000, fuel_used_milliliters=2000)

        # Mark down at 2026-08-04T12:00Z -> assignment SUSPENDED
        set_clock("2026-08-04T12:00:00Z")
        validate_success(api.mark_down_equipment(equip["id"], _ADMIN))

        # Mechanic + REPAIR work order, dispatch
        from test_helpers import make_mechanic, make_work_order, dispatch_work_order, start_work_order_as_mechanic, complete_work_order_as_mechanic
        mech = make_mechanic(project["id"], mechanic_code="MECH-1", name="Mac One")
        wo = make_work_order(equip["id"], kind="REPAIR", notes="hydraulic leak")
        dispatch_work_order(wo["id"], mech["id"])

        # Repair completes 2026-08-06T09:00 -> assignment reactivated
        set_clock("2026-08-06T09:00:00Z")
        start_work_order_as_mechanic(wo["id"], mech["id"])
        complete_work_order_as_mechanic(wo["id"], mech["id"])

        # Post-repair readings
        make_reading(equip["id"], recorded_date="2026-08-06",
                     engine_hours_delta_milli=4000, fuel_used_milliliters=2000)
        make_reading(equip["id"], recorded_date="2026-08-07",
                     engine_hours_delta_milli=8000, fuel_used_milliliters=4000)
        make_reading(equip["id"], recorded_date="2026-08-08",
                     engine_hours_delta_milli=0, fuel_used_milliliters=0)
        make_reading(equip["id"], recorded_date="2026-08-09",
                     engine_hours_delta_milli=0, fuel_used_milliliters=0)

        set_clock("2026-08-10T09:00:00Z")
        close_assignment(asg["id"])
        return asg

    def test_elapsed_counts_suspended_day_billing_does_not(self, api):
        """PRD section 3.6: "The `ELAPSED` variant, `utilization_elapsed_bp`,
        divides by every calendar day in the window from `start_date` to the
        close date, including suspended days and weekends ... The `BILLING`
        variant, `utilization_billing_bp`, divides instead by `billable_days`
        times 8000 — only chargeable days count". Window has 24000 milli over
        7 elapsed days vs 6 billable days -> 4286 vs 5000.

        Design: Difficulty/dual_variant_calc/utilization_elapsed_vs_billing_diverge_over_suspended_window
        """
        asg = self._setup_suspended_window(api)
        after = validate_success(api.get_assignment(asg["id"], _ADMIN))
        assert after["status"] == "CLOSED"
        assert after["engine_hours_billed_milli"] == 24000
        assert after["utilization_elapsed_bp"] == 4286
        assert after["utilization_billing_bp"] == 5000
        assert after["utilization_elapsed_bp"] != after["utilization_billing_bp"]

    def test_billable_days_excludes_suspended(self, api):
        """PRD section 3.6: "a calendar day inside it is chargeable whenever
        the assignment was `ACTIVE` for any part of that day; days spent
        `SUSPENDED` drop out. The count of chargeable days becomes
        `billable_days`."

        Design: Difficulty/dual_variant_calc/utilization_elapsed_vs_billing_diverge_over_suspended_window
        """
        asg = self._setup_suspended_window(api)
        after = validate_success(api.get_assignment(asg["id"], _ADMIN))
        assert after["billable_days"] == 6
        assert after["engine_hours_billed_milli"] == 24000


# ============================================================================
# Difficulty / combinatorial_formula
# ============================================================================

class TestRentalAllocationStacking:
    def _setup_and_close(self, api):
        set_clock("2026-08-07T09:00:00Z")
        cls = make_class(
            class_code="GRD-140", daily_rate_cents=9999, external_daily_rate_cents=12000,
            weekend_multiplier_bp=6667, idle_day_multiplier_bp=5000,
            service_interval_hours=10000,
        )
        project = make_project(project_code="PRJ-D")
        equip = make_equipment(cls["id"], unit_tag="UNIT-4")
        asg = make_active_assignment(equip, project, start_date="2026-08-07", end_date="2026-08-11")
        make_reading(equip["id"], recorded_date="2026-08-07",
                     engine_hours_delta_milli=8000, fuel_used_milliliters=4000)
        make_reading(equip["id"], recorded_date="2026-08-08",
                     engine_hours_delta_milli=0, fuel_used_milliliters=0)
        make_reading(equip["id"], recorded_date="2026-08-09",
                     engine_hours_delta_milli=0, fuel_used_milliliters=0)
        make_reading(equip["id"], recorded_date="2026-08-10",
                     engine_hours_delta_milli=8000, fuel_used_milliliters=4000)
        set_clock("2026-08-11T09:00:00Z")
        close_assignment(asg["id"])
        return asg

    def test_allocated_cents_uses_weekend_then_idle_order(self, api):
        """PRD section 3.6: "If the day is a Saturday or Sunday, the base is
        replaced by the base multiplied by `weekend_multiplier_bp` and divided
        by 10000, rounded half-up to whole cents. Then, if the day is idle ...
        multiplied by `idle_day_multiplier_bp` and divided by 10000, again
        rounded half-up to whole cents." For 9999 daily, weekend 6667, idle
        5000: Sat = round(round(9999*6667/10000)*5000/10000) = round(6666*0.5)
        = 3333.

        Design: Difficulty/combinatorial_formula/rental_allocation_weekend_then_idle_multiplier_stacking
        """
        asg = self._setup_and_close(api)
        rows, _ = validate_paginated(api.list_assignment_charges(asg["id"], _ADMIN))
        assert len(rows) == 1
        # Fri 9999 + Sat 3333 + Sun 3333 + Mon 9999 = 26664
        assert rows[0]["allocated_cents"] == 26664

    def test_billable_and_idle_days_counted(self, api):
        """PRD section 3.6: "The count of chargeable days becomes
        `billable_days`. ... the chargeable days on which the accepted delta
        is zero are counted as `idle_days`."

        Design: Difficulty/combinatorial_formula/rental_allocation_weekend_then_idle_multiplier_stacking
        """
        asg = self._setup_and_close(api)
        after = validate_success(api.get_assignment(asg["id"], _ADMIN))
        assert after["billable_days"] == 4
        assert after["idle_days"] == 2


class TestDamagePerLineRounding:
    def _file_two_line_abuse_report(self, api):
        set_clock("2026-08-03T09:00:00Z")
        cls, project, equip = make_fleet_bundle()
        make_active_assignment(equip, project, start_date="2026-08-03", end_date="2026-08-10")
        d = make_damage_report(
            equip["id"], project["id"],
            description="bucket teeth bent", abuse_flag=True,
            line_items=[{"description": "tooth A", "amount_cents": 3},
                        {"description": "tooth B", "amount_cents": 3}],
        )
        return d

    def test_per_line_rounding_beats_sum_then_round(self, api):
        """PRD section 3.8: "For each line item, the amount is multiplied by
        the applicable multiplier — 15000 basis points (1.5×) when
        `abuse_flag` is true, 10000 (no uplift) when false — and divided by
        10000, rounded half-up to whole cents per line. The per-line results
        are then summed". Two 3-cent lines at 15000 bp: round(3*15000/10000)=5
        per line, sum = 10 (sum-then-round would give 9 and is FORBIDDEN).

        Design: Difficulty/combinatorial_formula/damage_chargeback_per_line_rounding_beats_sum_then_round
        """
        d = self._file_two_line_abuse_report(api)
        assessed = assess_damage(d["id"])
        assert assessed["status"] == "ASSESSED"
        assert assessed["assessed_charge_cents"] == 10

    def test_assessed_report_status_is_assessed(self, api):
        """PRD section 3.8: "Assessment moves the report `FILED` → `ASSESSED`
        and stores the figure."

        Design: Difficulty/combinatorial_formula/damage_chargeback_per_line_rounding_beats_sum_then_round
        """
        d = self._file_two_line_abuse_report(api)
        assessed = assess_damage(d["id"])
        assert assessed["status"] == "ASSESSED"
        assert assessed["assessed_charge_cents"] == 10
        assert assessed["assessed_charge_cents"] != 9


class TestOwnVsRentPinnedEvaluationOrder:
    def _setup_and_close(self, api):
        set_clock("2026-08-03T09:00:00Z")
        cls = make_class(
            class_code="CRN-250", daily_rate_cents=8000, external_daily_rate_cents=9000,
            weekend_multiplier_bp=10000, idle_day_multiplier_bp=2500,
            service_interval_hours=10000,
        )
        project = make_project(project_code="PRJ-F")
        equip = make_equipment(cls["id"], unit_tag="UNIT-6")
        asg = make_active_assignment(equip, project, start_date="2026-08-03", end_date="2026-08-07")
        make_reading(equip["id"], recorded_date="2026-08-03",
                     engine_hours_delta_milli=8000, fuel_used_milliliters=4000)
        make_reading(equip["id"], recorded_date="2026-08-04",
                     engine_hours_delta_milli=8000, fuel_used_milliliters=4000)
        make_reading(equip["id"], recorded_date="2026-08-05",
                     engine_hours_delta_milli=0, fuel_used_milliliters=0)
        make_reading(equip["id"], recorded_date="2026-08-06",
                     engine_hours_delta_milli=4000, fuel_used_milliliters=2000)
        set_clock("2026-08-07T09:00:00Z")
        close_assignment(asg["id"])
        return asg

    def test_own_cost_decomposes_from_allocation(self, api):
        """PRD section 3.6: "The `OWN` variant, `own_cost_cents`, is the
        allocated amount plus two ownership burdens: the billed engine hours
        (the milli-hour total divided by 1000) multiplied by a wear rate of
        900 cents per hour, rounded half-up to whole cents; plus
        `billable_days` times a fixed ownership cost of 4200 cents per day."
        allocated 26000 + wear round(20*900)=18000 + fixed 4*4200=16800 =
        60800.

        Design: Difficulty/combinatorial_formula/own_vs_rent_pinned_evaluation_order_from_allocation
        """
        asg = self._setup_and_close(api)
        rows, _ = validate_paginated(api.list_assignment_charges(asg["id"], _ADMIN))
        charge = rows[0]
        assert charge["allocated_cents"] == 26000
        assert charge["own_cost_cents"] == 60800

    def test_rent_variant_flat_per_day(self, api):
        """PRD section 3.6: "The `RENT` variant, `rent_cost_cents`, ignores
        usage entirely: `billable_days` times the class
        `external_daily_rate_cents`, plus `billable_days` times an
        external-rental admin fee of 1500 cents per day." 4*(9000+1500)=42000,
        and since 42000 < 60800 cheaper_variant == RENT.

        Design: Difficulty/combinatorial_formula/own_vs_rent_pinned_evaluation_order_from_allocation
        """
        asg = self._setup_and_close(api)
        rows, _ = validate_paginated(api.list_assignment_charges(asg["id"], _ADMIN))
        charge = rows[0]
        assert charge["rent_cost_cents"] == 42000
        assert charge["cheaper_variant"] == "RENT"


# ============================================================================
# Corner / calculations
# ============================================================================

class TestFuelBurnRate:
    def _setup_readings(self, api):
        cls = make_class(class_code="EXC-300", service_interval_hours=10000)
        equip = make_equipment(cls["id"], unit_tag="UNIT-300")
        make_reading(equip["id"], recorded_date="2026-08-03",
                     engine_hours_delta_milli=8000, fuel_used_milliliters=5000)
        make_reading(equip["id"], recorded_date="2026-08-04",
                     engine_hours_delta_milli=4000, fuel_used_milliliters=7000)
        make_reading(equip["id"], recorded_date="2026-08-05",
                     engine_hours_delta_milli=8000, fuel_used_milliliters=9000)
        return equip

    def test_inclusive_window_counts_both_endpoints(self, api):
        """PRD section 3.3: "A fuel summary over an inclusive date window —
        `from_date` and `to_date` both count, in contrast to the half-open
        assignment windows — sums `fuel_used_milliliters` into `total_fuel_ml`
        and `engine_hours_delta_milli` into `total_hours_milli` across the
        `ACCEPTED` readings whose `recorded_date` falls within the window."

        Design: Corner/calculations/fuel_burn_rate_inclusive_window_both_ends
        """
        equip = self._setup_readings(api)
        data = validate_success(api.get_fuel_summary(
            equip["id"], _ADMIN, params={"from_date": "2026-08-03", "to_date": "2026-08-04"}
        ))
        assert data["total_fuel_ml"] == 12000
        assert data["total_hours_milli"] == 12000
        assert data["burn_ml_per_hour"] == 1000

    def test_single_day_window_and_full_window(self, api):
        """PRD section 3.3: "The burn rate `burn_ml_per_hour` is the total
        milliliters multiplied by 1000 and divided by the total milli-hours,
        rounded half-up to a whole milliliter per hour". [08-04, 08-04]:
        7000 ml / 4000 milli h -> 1750 ml/h. [08-03, 08-05]: 21000/20000
        -> 1050.

        Design: Corner/calculations/fuel_burn_rate_inclusive_window_both_ends
        """
        equip = self._setup_readings(api)
        single = validate_success(api.get_fuel_summary(
            equip["id"], _ADMIN, params={"from_date": "2026-08-04", "to_date": "2026-08-04"}
        ))
        assert single["total_fuel_ml"] == 7000
        assert single["total_hours_milli"] == 4000
        assert single["burn_ml_per_hour"] == 1750

        full = validate_success(api.get_fuel_summary(
            equip["id"], _ADMIN, params={"from_date": "2026-08-03", "to_date": "2026-08-05"}
        ))
        assert full["total_fuel_ml"] == 21000
        assert full["total_hours_milli"] == 20000
        assert full["burn_ml_per_hour"] == 1050

    def test_zero_hours_returns_null_burn(self, api):
        """PRD section 3.3: "when no accepted hours exist in the window,
        `burn_ml_per_hour` is null rather than zero."

        Design: Corner/calculations/fuel_burn_rate_zero_hours_returns_null
        """
        cls = make_class(class_code="EXC-301", service_interval_hours=10000)
        equip = make_equipment(cls["id"], unit_tag="UNIT-301")
        make_reading(equip["id"], recorded_date="2026-08-03",
                     engine_hours_delta_milli=0, fuel_used_milliliters=500)
        data = validate_success(api.get_fuel_summary(
            equip["id"], _ADMIN, params={"from_date": "2026-08-03", "to_date": "2026-08-03"}
        ))
        assert data["total_fuel_ml"] == 500
        assert data["total_hours_milli"] == 0
        assert data["burn_ml_per_hour"] is None


class TestRedeploymentScore:
    def test_bonuses_compose_and_recommendation_picks_highest(self, api):
        """PRD section 3.7: "Each candidate's score, in basis points, starts
        from the `utilization_billing_bp` of this unit's most recent `CLOSED`
        assignment on that project — zero if the unit was never assigned there
        — adds 1000 if the project currently has no unit of this class on
        rent, and adds a further 100 if the project's remaining budget covers
        at least 30 days at the class `daily_rate_cents`. Candidates rank by
        score descending".

        Design: Corner/calculations/redeployment_score_bonuses_and_ranking
        """
        set_clock("2026-08-03T09:00:00Z")
        cls = make_class(class_code="EXC-302", daily_rate_cents=10000,
                         weekend_multiplier_bp=5000, idle_day_multiplier_bp=5000,
                         service_interval_hours=10000)
        pra = make_project(project_code="PRJ-RA", equipment_budget_cents=10000000)
        prb = make_project(project_code="PRJ-RB", equipment_budget_cents=10000000)
        e302 = make_equipment(cls["id"], unit_tag="UNIT-302")
        asg = make_active_assignment(e302, pra, start_date="2026-08-03", end_date="2026-08-07")
        make_reading(e302["id"], recorded_date="2026-08-03",
                     engine_hours_delta_milli=8000, fuel_used_milliliters=4000)
        make_reading(e302["id"], recorded_date="2026-08-04",
                     engine_hours_delta_milli=8000, fuel_used_milliliters=4000)
        make_reading(e302["id"], recorded_date="2026-08-05",
                     engine_hours_delta_milli=0, fuel_used_milliliters=0)
        make_reading(e302["id"], recorded_date="2026-08-06",
                     engine_hours_delta_milli=0, fuel_used_milliliters=0)
        set_clock("2026-08-07T09:00:00Z")
        close_assignment(asg["id"])

        # Class-mate currently ON_RENT at P_A -> kills the +1000 absence bonus there
        e302b = make_equipment(cls["id"], unit_tag="UNIT-302B")
        asg_b = make_reserved_assignment(e302b, pra, start_date="2026-08-10", end_date="2026-08-20")
        set_clock("2026-08-10T09:00:00Z")
        validate_success(api.activate_assignment(asg_b["id"], _ADMIN))

        data = validate_success(api.get_redeployment_score(e302["id"], _ADMIN))
        assert data["recommended_project_id"] == pra["id"]
        assert len(data["candidates"]) == 2
        assert data["idle_alert"] is False

    def test_tie_breaks_by_created_at_then_project_code(self, api):
        """PRD section 3.7: "Candidates rank by score descending; ties break
        by project `created_at` ascending, then by `project_code` ascending."

        Design: Corner/calculations/redeployment_score_tie_break_created_at_then_project_code
        """
        set_clock("2026-08-01T00:00:00Z")
        cls = make_class(class_code="EXC-303", daily_rate_cents=10000, service_interval_hours=10000)
        # Created in this order but PRJ-TB1 sorts before PRJ-TB2 lexicographically.
        ptb2 = make_project(project_code="PRJ-TB2", name="Tie Two", equipment_budget_cents=10000000)
        ptb1 = make_project(project_code="PRJ-TB1", name="Tie One", equipment_budget_cents=10000000)
        e303 = make_equipment(cls["id"], unit_tag="UNIT-303")
        data = validate_success(api.get_redeployment_score(e303["id"], _ADMIN))
        # Both candidates score 0 + 1000 + 100 = 1100 with equal created_at;
        # project_code ASC picks PRJ-TB1.
        assert data["recommended_project_id"] == ptb1["id"]

    def test_empty_pool_returns_null_recommendation(self, api):
        """PRD section 3.7: "When the pool is empty the read returns an empty
        candidate list with `recommended_project_id` set to null — an
        exhausted pool is a normal result, not an error."

        Design: Corner/calculations/redeployment_score_empty_pool_returns_null_recommendation
        """
        cls = make_class(class_code="EXC-304", daily_rate_cents=10000)
        make_project(project_code="PRJ-304", equipment_budget_cents=0)
        equip = make_equipment(cls["id"], unit_tag="UNIT-304")
        data = validate_success(api.get_redeployment_score(equip["id"], _ADMIN))
        assert data["candidates"] == []
        assert data["recommended_project_id"] is None


class TestUtilizationClamp:
    def test_utilization_clamped_at_10000(self, api):
        """PRD section 2.6: "Utilization figures are integer basis points in
        the range 0 to 10000, rounded half-up; any computed value above 10000
        is clamped to 10000."

        Design: Corner/calculations/utilization_rate_clamped_at_10000
        """
        set_clock("2026-08-03T09:00:00Z")
        cls = make_class(class_code="EXC-305", service_interval_hours=10000)
        project = make_project(project_code="PRJ-305")
        equip = make_equipment(cls["id"], unit_tag="UNIT-305")
        asg = make_active_assignment(equip, project, start_date="2026-08-03", end_date="2026-08-04")
        make_reading(equip["id"], recorded_date="2026-08-03",
                     engine_hours_delta_milli=24000, fuel_used_milliliters=12000)
        set_clock("2026-08-04T09:00:00Z")
        close_assignment(asg["id"])
        after = validate_success(api.get_assignment(asg["id"], _ADMIN))
        assert after["utilization_elapsed_bp"] == 10000
        assert after["utilization_billing_bp"] == 10000


class TestOwnVsRentTie:
    def test_tie_when_variants_equal(self, api):
        """PRD section 3.6: "`cheaper_variant` records `OWN` when the own cost
        is strictly less, `RENT` when the rent cost is strictly less, and
        `TIE` when they are equal." With daily 10000, external 12700, admin
        1500, fixed 4200, idle 10000, 0-hour day: own = 10000 + 0 + 4200 =
        14200; rent = 12700 + 1500 = 14200 -> TIE.

        Design: Corner/calculations/own_vs_rent_tie_when_variants_equal
        """
        set_clock("2026-08-03T09:00:00Z")
        cls = make_class(
            class_code="EXC-306", daily_rate_cents=10000, external_daily_rate_cents=12700,
            weekend_multiplier_bp=10000, idle_day_multiplier_bp=10000,
            service_interval_hours=10000,
        )
        project = make_project(project_code="PRJ-306")
        equip = make_equipment(cls["id"], unit_tag="UNIT-306")
        asg = make_active_assignment(equip, project, start_date="2026-08-03", end_date="2026-08-04")
        make_reading(equip["id"], recorded_date="2026-08-03",
                     engine_hours_delta_milli=0, fuel_used_milliliters=0)
        set_clock("2026-08-04T09:00:00Z")
        close_assignment(asg["id"])
        rows, _ = validate_paginated(api.list_assignment_charges(asg["id"], _ADMIN))
        charge = rows[0]
        assert charge["own_cost_cents"] == 14200
        assert charge["rent_cost_cents"] == 14200
        assert charge["cheaper_variant"] == "TIE"


class TestResidualFloor:
    def test_residual_floors_at_salvage(self, api):
        """PRD section 3.9: "Both variants then floor at the class
        `salvage_value_cents`: if the computed residual falls below it, the
        salvage floor stands." acquisition_cost 1000000, salvage 900000,
        useful_life 12 months, age 19 months -> depreciation saturates at
        (1000000-900000)*12/12 = 100000 -> residual 900000 == floor.

        Design: Corner/calculations/residual_value_floors_at_salvage_when_over_depreciated
        """
        set_clock("2026-08-01T00:00:00Z")
        cls = make_class(class_code="EXC-307", expected_life_hours=12000,
                         salvage_value_cents=900000, service_interval_hours=10000)
        equip = make_equipment(cls["id"], unit_tag="UNIT-307",
                               acquisition_cost_cents=1000000,
                               acquisition_date="2025-01-01",
                               useful_life_months=12)
        disposed = validate_success(
            api.dispose_equipment(equip["id"], {"disposal_method": "SALE"}, _ADMIN)
        )
        assert disposed["residual_value_cents"] == 900000
