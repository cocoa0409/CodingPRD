"""The arithmetic layer: the stick-built fork, the weather-tight aggregation, the
per-day labour constants, the posture fixed point, both ends of the surcharge
ladder, the clock-dependent risk score and the signed hour ledger."""
import pytest
from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_crew_hour_ledger, assert_earned_value_consistency
from test_helpers.constants import CLOCK_FIELD_TEST_DAY, CLOCK_HANG_DAY, CLOCK_T0, USER_IDS
from test_helpers.test_users import TEST_USERS

PM = TEST_USERS["cw_project_manager_headers"]
DETAILER = TEST_USERS["cw_detailer_headers"]
PROCUREMENT = TEST_USERS["glazing_procurement_headers"]
SUPERINTENDENT = TEST_USERS["field_superintendent_headers"]
QC = TEST_USERS["qc_inspector_headers"]


class TestStickBuiltFork:
    """The second branch of the fork is not a scaled copy of the first."""

    def test_the_stick_built_branch_prices_and_geometries_differently_in_all_four_outputs(self):
        """Nine thousand square metres priced stick-built yield 1620.00 shop hours
        against a field crew of 8, and the same 3200 mm slotted zone at 18.0 m
        picks up the 1.25 system factor for 7.30 mm and the L/175 divisor for
        18.29 mm — where the unitized fork on an identical package yields
        4950.00, 4, 5.84 and 13.33 instead.

        PRD: "Choosing `STICK_BUILT` moves labour into the field: `planned_shop_hours` becomes the contracted `total_area_sqm` multiplied by 0.18 shop hours per square metre, rounded half up to two decimals, and `planned_field_crew_size` becomes 8 glaziers."

        Design: Corner/calculations/stick_built_decision_reprices_labor_thermal_and_deflection
        """
        stick = fx.new_project(clock=CLOCK_T0, system_type=None)
        stick_zone = fx.add_zone_a(stick, height_m=18.0)
        assert stick_zone["thermal_movement_allowance_mm"] is None
        assert stick_zone["deflection_limit_mm"] is None

        decided = fx.decide_system(stick, "STICK_BUILT")
        assert decided["system_type"] == "STICK_BUILT"
        assert decided["planned_shop_hours"] == pytest.approx(1620.00, abs=0.01)
        assert decided["planned_field_crew_size"] == 8

        stick_geometry = get_success_data(
            api_client.get_installation_zone(stick_zone["id"], PM)
        )
        assert stick_geometry["thermal_movement_allowance_mm"] == pytest.approx(7.30, abs=0.01)
        assert stick_geometry["deflection_limit_mm"] == pytest.approx(18.29, abs=0.01)

        unitized = fx.new_project(clock=CLOCK_T0, system_type=None)
        unitized_zone = fx.add_zone_a(unitized, height_m=18.0)
        unitized_decided = fx.decide_system(unitized, "UNITIZED")
        assert unitized_decided["planned_shop_hours"] == pytest.approx(4950.00, abs=0.01)
        assert unitized_decided["planned_field_crew_size"] == 4

        unitized_geometry = get_success_data(
            api_client.get_installation_zone(unitized_zone["id"], PM)
        )
        assert unitized_geometry["thermal_movement_allowance_mm"] == pytest.approx(
            5.84, abs=0.01
        )
        assert unitized_geometry["deflection_limit_mm"] == pytest.approx(13.33, abs=0.01)

    def test_a_deflection_measured_at_the_stick_built_limit_fails_while_one_hundredth_under_passes(self):
        """The L/175 divisor puts the pass line at 18.29 mm, and because equality
        fails a measurement of exactly 18.29 is refused while 18.28 passes.

        PRD: "A `STRUCTURAL_DEFLECTION` test reaches `PASSED` when `measured_deflection_mm` is strictly less than the zone's computed `deflection_limit_mm`."

        Design: Corner/calculations/stick_built_decision_reprices_labor_thermal_and_deflection
        """
        ctx = fx.setup_hung_zone(system_type="STICK_BUILT")
        zone_id = ctx["zone_ids"][0]
        zone = get_success_data(api_client.get_installation_zone(zone_id, PM))
        assert zone["deflection_limit_mm"] == pytest.approx(18.29, abs=0.01)
        assert zone["thermal_movement_allowance_mm"] == pytest.approx(8.80, abs=0.01)

        fx.set_clock(CLOCK_FIELD_TEST_DAY)
        at_limit = fx.schedule_field_test(
            ctx, zone_id, "STRUCTURAL_DEFLECTION", CLOCK_FIELD_TEST_DAY
        )
        failed = fx.record_field_test(
            ctx, at_limit["id"], f.deflection_result_payload(18.29), USER_IDS["QC_2"]
        )
        assert failed["state"] == "FAILED"
        assert failed["outcome_reason"] == "DEFLECTION_EXCEEDED"

        retest = fx.schedule_field_test(
            ctx, zone_id, "STRUCTURAL_DEFLECTION", CLOCK_FIELD_TEST_DAY, attempt_no=2
        )
        passed = fx.record_field_test(
            ctx, retest["id"], f.deflection_result_payload(18.28), USER_IDS["QC_2"]
        )
        assert passed["state"] == "PASSED"
        assert passed["outcome_reason"] == "WITHIN_TOLERANCE"


class TestEarnedValueInputSet:
    """The aggregation input set is exactly the weather-tight zones."""

    def test_the_untight_zone_contributes_nothing_to_area_subtotal_or_earned_value(self):
        """Zone A certified and zone B never hung give a one-zone ledger of 412.37
        sqm, 58266376 subtotal, 2913319 retention and 55353057 earned, the read
        mutates nothing, and the package stays in installation because zone B is
        still not tight.

        PRD: "Zones in `NOT_TIGHT` or `REMEDIATION` contribute nothing, which is why a revert cascade simply removes the reverted zone's line from the sum and re-runs all three stages."

        Design: Corner/calculations/earned_value_counts_only_weather_tight_zones
        """
        ctx = fx.setup_certified_zone(zone_count=2)
        zone_a, zone_b = ctx["zone_ids"][0], ctx["zone_ids"][1]
        before = fx.refresh_package(ctx)

        read = validate_success(
            api_client.get_earned_value(ctx["package_id"], PM), expected_status=200
        )
        assert read["certified_area_sqm"] == pytest.approx(412.37, abs=0.01)
        assert read["weather_tight_zone_count"] == 1
        assert read["certified_subtotal_cents"] == 58266376
        assert read["retention_held_cents"] == 2913319
        assert read["earned_value_certified_cents"] == 55353057
        assert read["contract_value_cents"] == 1450000000
        assert_earned_value_consistency(read)

        after = fx.refresh_package(ctx)
        assert after["version"] == before["version"]
        assert after["earned_value_certified_cents"] == 55353057
        assert after["state"] == "IN_INSTALLATION"

        tight = get_success_data(api_client.get_installation_zone(zone_a, PM))
        untight = get_success_data(api_client.get_installation_zone(zone_b, PM))
        assert tight["weather_status"] == "WEATHER_TIGHT"
        assert tight["certified_line_cents"] == 58266376
        assert untight["weather_status"] == "NOT_TIGHT"
        assert untight["certified_line_cents"] is None
        assert untight["area_sqm"] == pytest.approx(388.63, abs=0.01)


class TestPerDayLabourConstants:
    """Three constants visible in single posted days."""

    def test_overtime_and_elevation_are_applied_per_day_and_indexed_per_zone(self):
        """A four-glazier ten-hour shift splits 32.0 straight against 8.0
        overtime and prices at 495880 on a 24.0 m zone but at 431200 on an 18.0 m
        zone, both logs carry index 1 within their own zone, and a plain
        eight-hour day on the high zone prices at 360640 with no overtime.

        PRD: "That base is then multiplied by an elevation factor of 1.15 when the zone's `height_m` is strictly greater than 20.0 metres, and by 1.00 otherwise."

        Design: Corner/calculations/overtime_multiplier_and_elevation_factor_applied_per_day
        """
        ctx = fx.new_project(clock=CLOCK_HANG_DAY)
        high = fx.add_zone_a(ctx)
        low = fx.add_zone_b(ctx, height_m=18.0)
        assert high["height_m"] == pytest.approx(24.0, abs=0.01)
        assert low["height_m"] == pytest.approx(18.0, abs=0.01)

        high_day = fx.post_crew_day(
            ctx, high["id"], work_date="2026-08-10", crew_size=4, shift_hours=10.0,
            panels_installed=10,
        )
        low_day = fx.post_crew_day(
            ctx, low["id"], work_date="2026-08-10", crew_size=4, shift_hours=10.0,
            panels_installed=10,
        )
        assert high_day["straight_person_hours"] == pytest.approx(32.0, abs=0.01)
        assert high_day["overtime_person_hours"] == pytest.approx(8.0, abs=0.01)
        assert high_day["day_cost_cents"] == 495880
        assert low_day["day_cost_cents"] == 431200
        assert high_day["day_index"] == 1
        assert low_day["day_index"] == 1

        high_zone = get_success_data(api_client.get_installation_zone(high["id"], PM))
        assert high_zone["consumed_crew_hours"] == pytest.approx(40.0, abs=0.01)
        assert high_zone["remaining_crew_hours"] == pytest.approx(280.0, abs=0.01)

        straight_day = fx.post_crew_day(
            ctx, high["id"], work_date="2026-08-11", crew_size=4, shift_hours=8.0,
            panels_installed=10,
        )
        assert straight_day["overtime_person_hours"] == pytest.approx(0.0, abs=0.01)
        assert straight_day["day_cost_cents"] == 360640
        assert straight_day["day_index"] == 2


class TestPostureFixedPoint:
    """The gate is re-derived from scratch on every contributing write."""

    def test_the_posture_walks_up_to_frozen_and_all_the_way_back_down_to_open(self):
        """One open critical item restricts the package, a second freezes it,
        remediation of the second leaves it frozen because a submitted remediation
        still counts as open, closing the second returns it to restricted, and
        closing the first returns it to open with both counters at zero.

        PRD: "The posture is `FROZEN` when any submittal of the package is in state `ESCALATED`, or when `open_critical_defect_count` is 2 or more."

        Design: Corner/calculations/engineering_posture_reaches_a_fixed_point_in_one_pass
        """
        ctx = fx.new_project(clock=CLOCK_T0)
        mockup = fx.add_failed_mockup(ctx)
        first = get_success_data(
            api_client.list_defect_items(
                QC, params={"package_id": ctx["package_id"], "origin": "MOCKUP_TEST"}
            )
        )[0]
        restricted = fx.refresh_package(ctx)
        assert restricted["open_critical_defect_count"] == 1
        assert restricted["engineering_posture"] == "RESTRICTED"

        second = fx.raise_defect(
            ctx,
            user_id=USER_IDS["QC_1"],
            origin="MOCKUP_TEST",
            severity="CRITICAL",
            mockup_test_id=mockup["id"],
            description="second critical finding at the mullion splice",
        )
        frozen = fx.refresh_package(ctx)
        assert frozen["open_critical_defect_count"] == 2
        assert frozen["engineering_posture"] == "FROZEN"

        fx.submit_remediation(ctx, second["id"], "splice re-detailed")
        still_frozen = fx.refresh_package(ctx)
        assert still_frozen["open_critical_defect_count"] == 2
        assert still_frozen["engineering_posture"] == "FROZEN"

        fx.reinspect_defect(ctx, second["id"], "PASS", USER_IDS["QC_2"])
        back_to_restricted = fx.refresh_package(ctx)
        assert back_to_restricted["open_critical_defect_count"] == 1
        assert back_to_restricted["engineering_posture"] == "RESTRICTED"

        fx.submit_remediation(ctx, first["id"], "gasket re-tooled")
        fx.reinspect_defect(ctx, first["id"], "PASS", USER_IDS["QC_2"])
        reopened = fx.refresh_package(ctx)
        assert reopened["open_critical_defect_count"] == 0
        assert reopened["blocking_submittal_count"] == 0
        assert reopened["engineering_posture"] == "OPEN"

    def test_one_escalated_submittal_freezes_a_package_with_no_defects_at_all(self):
        """The two posture inputs are independent: an escalated submittal forces
        the frozen value while the critical-defect counter is still zero.

        PRD: "A fresh package therefore opens at `OPEN` with both counters at 0; one submittal sitting in `REVISION_REQUIRED` with no defects yields `RESTRICTED`; one open critical defect yields `RESTRICTED`; two open critical defects yield `FROZEN`; and a single `ESCALATED` submittal yields `FROZEN` even when the package has no defects at all."

        Design: Corner/calculations/engineering_posture_reaches_a_fixed_point_in_one_pass
        """
        ctx = fx.setup_escalated_submittal()
        assert (
            get_success_data(api_client.get_submittal(ctx["submittal_id"], DETAILER))["state"]
            == "ESCALATED"
        )
        package = fx.refresh_package(ctx)
        assert package["open_critical_defect_count"] == 0
        assert package["blocking_submittal_count"] == 1
        assert package["engineering_posture"] == "FROZEN"


class TestMockupSurchargeLadder:
    """Both ends of the tier ladder, selected from the subtotal alone."""

    def test_a_five_hour_retest_pays_two_percent_and_a_seventy_two_chamber_hour_retest_pays_ten(self):
        """A five chamber-hour retest subtotals 587500, sits at or under the first
        ceiling and pays 11750; a seventy-two chamber-hour retest subtotals
        2028000, sits above the last ceiling and pays 202800; and the same
        five-hour window booked as a first attempt pays nothing.

        PRD: "Third, `surcharge_cents` is zero whenever `retest_of_test_id` is null; otherwise it is `invoice_subtotal_cents` multiplied by a tier rate and rounded half up to whole cents, where the tier rate is 0.02 when the subtotal is 600,000 cents or less, 0.04 when the subtotal is 800,000 cents or less, 0.06 when the subtotal is 2,000,000 cents or less, and 0.10 above that."

        Design: Corner/calculations/mockup_invoice_tier_1_and_tier_4_rates
        """
        ctx = fx.setup_qualified_package()
        passed = ctx["mockup"]
        assert passed["state"] == "PASSED"

        tier_one = validate_success(
            api_client.create_mockup_test(
                f.create_mockup_test_payload(
                    ctx["package_id"],
                    ctx["lab_id"],
                    window_start="2026-08-06T06:00:00Z",
                    window_end="2026-08-06T11:00:00Z",
                    chambers_required=1,
                    retest_of_test_id=passed["id"],
                    attempt_no=2,
                ),
                PM,
            ),
            expected_status=201,
        )
        assert tier_one["chamber_hours"] == 5
        assert tier_one["invoice_subtotal_cents"] == 587500
        assert tier_one["surcharge_cents"] == 11750
        assert tier_one["invoice_cents"] == 599250
        assert tier_one["retest_of_test_id"] == passed["id"]

        tier_four = validate_success(
            api_client.create_mockup_test(
                f.create_mockup_test_payload(
                    ctx["package_id"],
                    ctx["lab_id"],
                    window_start="2026-08-08T06:00:00Z",
                    window_end="2026-08-09T18:00:00Z",
                    chambers_required=2,
                    retest_of_test_id=passed["id"],
                    attempt_no=3,
                ),
                PM,
            ),
            expected_status=201,
        )
        assert tier_four["chamber_hours"] == 72
        assert tier_four["invoice_subtotal_cents"] == 2028000
        assert tier_four["surcharge_cents"] == 202800
        assert tier_four["invoice_cents"] == 2230800
        assert tier_four["retest_of_test_id"] == passed["id"]

        first_attempt = validate_success(
            api_client.create_mockup_test(
                f.create_mockup_test_payload(
                    ctx["package_id"],
                    ctx["lab_id"],
                    window_start="2026-08-06T06:00:00Z",
                    window_end="2026-08-06T11:00:00Z",
                    chambers_required=1,
                ),
                PM,
            ),
            expected_status=201,
        )
        assert first_attempt["retest_of_test_id"] is None
        assert first_attempt["attempt_no"] == 1
        assert first_attempt["invoice_subtotal_cents"] == 587500
        assert first_attempt["surcharge_cents"] == 0
        assert first_attempt["invoice_cents"] == 587500


class TestRiskAgainstTheLogicalClock:
    """The same untouched order scores differently on a different date."""

    def test_moving_the_clock_clamps_both_components_and_flips_the_release_gate(self):
        """An order quoting ninety days scores 48.11 in August; on the first of
        October the seventy-five surviving days clamp both the lead and the
        calendar component to one, the score reaches 80.00 with the flag set, the
        order never leaves its ordered state, and a release naming it is refused.

        PRD: "The **lead component** is `effective_lead_days` divided by `days_to_deadline` — or divided by 1 when `days_to_deadline` is below 1 — clamped into the range 0 to 1 inclusive."

        Design: Corner/calculations/risk_score_reevaluated_against_the_moved_logical_clock
        """
        ctx = fx.setup_qualified_package(weather_tightness_deadline_date="2026-12-15")
        fx.add_approved_submittal(ctx)
        fx.add_zone_a(ctx)
        order = fx.create_glass_order(ctx, quoted_lead_time_days=90, ordered_lites=240)
        assert order["risk_score"] == pytest.approx(48.11, abs=0.01)
        assert order["effective_lead_days"] == 90
        assert order["risk_variant"] == "NOMINAL"
        assert order["risk_flag"] is False

        fx.set_clock("2026-10-01T08:00:00Z")
        rescored = validate_success(
            api_client.recompute_glass_risk(
                order["id"], f.recompute_risk_payload(), PROCUREMENT
            ),
            expected_status=200,
        )
        assert rescored["risk_score"] == pytest.approx(80.00, abs=0.01)
        assert rescored["risk_flag"] is True
        assert rescored["risk_variant"] == "NOMINAL"
        assert rescored["effective_lead_days"] == 90
        assert rescored["state"] == "ORDERED"
        assert rescored["last_risk_computed_at"] == "2026-10-01T08:00:00.000Z"

        refused = api_client.create_fabrication_release(
            f.create_fabrication_release_payload(
                ctx["package_id"],
                ctx["submittal_id"],
                order["id"],
                list(ctx["zone_ids"]),
                fx.package_version(ctx),
            ),
            PM,
        )
        validate_error(
            refused,
            ApiErrorId.ERR_GLASS_RISK_THRESHOLD_EXCEEDED.value,
            expected_status=422,
        )


class TestCrewHourOverrun:
    """The remaining figure is a signed report, not a clamped balance."""

    def test_two_sixteen_hour_days_drive_the_remaining_hours_deeply_negative(self):
        """A zone budgeted at forty hours absorbs sixty-four hours on the first day
        and one hundred and twenty-eight over two, reporting minus twenty-four and
        then minus eighty-eight while the budget identity still holds and nothing
        is refused.

        PRD: "`remaining_crew_hours` is the budget less the consumed figure and may go negative; an overrun is reported, not clamped."

        Design: Corner/calculations/crew_hour_ledger_reports_overrun_without_clamping
        """
        ctx = fx.new_project(clock=CLOCK_HANG_DAY)
        zone = fx.add_zone_a(ctx, budget_crew_hours=40.0)

        first = fx.post_crew_day(
            ctx, zone["id"], work_date="2026-08-10", crew_size=4, shift_hours=16.0,
            panels_installed=12,
        )
        assert first["straight_person_hours"] == pytest.approx(32.0, abs=0.01)
        assert first["overtime_person_hours"] == pytest.approx(32.0, abs=0.01)
        assert first["day_cost_cents"] == 901600
        assert first["day_index"] == 1
        assert first["status"] == "POSTED"

        after_one = get_success_data(api_client.get_installation_zone(zone["id"], PM))
        assert after_one["consumed_crew_hours"] == pytest.approx(64.0, abs=0.01)
        assert after_one["remaining_crew_hours"] == pytest.approx(-24.0, abs=0.01)
        assert_crew_hour_ledger(after_one)

        second = fx.post_crew_day(
            ctx, zone["id"], work_date="2026-08-11", crew_size=4, shift_hours=16.0,
            panels_installed=12,
        )
        assert second["day_index"] == 2
        assert second["status"] == "POSTED"

        after_two = get_success_data(api_client.get_installation_zone(zone["id"], PM))
        assert after_two["consumed_crew_hours"] == pytest.approx(128.0, abs=0.01)
        assert after_two["remaining_crew_hours"] == pytest.approx(-88.0, abs=0.01)
        assert after_two["budget_crew_hours"] == pytest.approx(40.0, abs=0.01)
        assert_crew_hour_ledger(after_two)
