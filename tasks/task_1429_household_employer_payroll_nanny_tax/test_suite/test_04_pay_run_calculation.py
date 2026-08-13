"""Pay run calculation: gross variants, overtime extraction, withholding lines."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_cost_precision,
    create_approved_timesheet,
    create_pay_run,
    create_rule_pack,
    line_amount,
    make_payroll_admin_headers,
    make_work_entries,
    setup_active_worker,
    setup_calculated_pay_run,
    setup_finalized_pay_run,
    setup_registered_employer,
    validate_error,
    validate_paginated,
    validate_success,
)


def _single_paycheck(api, pay_run_id):
    resp = api.list_pay_run_paychecks(pay_run_id, make_payroll_admin_headers())
    data, _meta = validate_paginated(resp)
    assert len(data) == 1, f"expected exactly one paycheck, got {len(data)}"
    return data[0]


class TestProvisionalVsFinalGross:
    def _setup_timesheet_basis_paycheck(self, api):
        """Worker with a 2400-min/week guarantee whose approved timesheet
        reports 2700 minutes (45h) for the pay-run period."""
        employer, worker, _a = setup_active_worker(
            "AA",
            worker_overrides={"ssn": "123456789"},
            agreement_overrides={"guaranteed_minutes_per_week": 2400},
            agencies=("NEW_HIRE_DIRECTORY", "SIT_WITHHOLDING", "SUTA"),
        )
        create_approved_timesheet(
            employer["id"], worker["id"], "2026-01-05", "2026-01-12",
            make_work_entries("2026-01-05", [540, 540, 540, 540, 540]),
        )
        run = setup_calculated_pay_run(employer["id"])
        return employer, worker, run

    def test_timesheet_basis_gross_includes_weekly_overtime(self, api):
        """PRD §3.6: "Each paycheck's `basis` is determined by whether an `APPROVED`-or-`LOCKED` timesheet exactly covers the pay-run period for the worker: `TIMESHEET` when one does, `GUARANTEE_FALLBACK` when none does."
        PRD §3.6: "Second, **weekly extraction**: the weekly overtime portion is the number of regular-time minutes remaining after daily extraction that exceeds the pack's `weekly_ot_threshold_minutes`, floored at zero; those minutes are moved from regular into overtime."

        Design: Difficulty/dual_variant_calc/paycheck_gross_provisional_vs_final
        """
        _e, _w, run = self._setup_timesheet_basis_paycheck(api)
        pc = _single_paycheck(api, run["id"])
        assert pc["basis"] == "TIMESHEET"
        # 2400 regular x 50 + 300 OT x 75 (1.5x rate, exact) = 142500.
        assert pc["regular_minutes"] == 2400
        assert pc["overtime_minutes"] == 300
        assert pc["guarantee_top_up_minutes"] == 0
        assert pc["gross_cents"] == 142500

    def test_provisional_gross_is_always_guarantee_basis(self, api):
        """PRD §3.6: "The provisional figure `provisional_gross_cents` is always computed on the guarantee basis — guaranteed minutes for the period multiplied by the straight-time per-minute rate, with no overtime and no timesheet data — regardless of which `basis` the paycheck ultimately uses."
        PRD §3.6: "Every line is rounded half-up to integer cents **before** any summation, and `net_pay_cents` is `gross_cents` minus the sum of the rounded withholding lines."

        Design: Difficulty/dual_variant_calc/paycheck_gross_provisional_vs_final
        """
        _e, _w, run = self._setup_timesheet_basis_paycheck(api)
        pc = _single_paycheck(api, run["id"])
        assert pc["provisional_gross_cents"] == 120000, (
            f"provisional must be guarantee basis 2400 x 50, got {pc['provisional_gross_cents']}"
        )
        # SIT line: round_half_up(142500 x 0.05) = 7125; no FICA (142500 < 280000).
        assert line_amount(pc["withholding_lines"], "SIT_EE") == 7125
        assert pc["net_pay_cents"] == 135375


class TestDailyAndWeeklyOvertimeExtraction:
    def test_daily_carveouts_precede_weekly_threshold(self, api):
        """PRD §3.6: "First, **daily extraction**: for each timesheet entry, when the pack's `daily_dt_threshold_minutes` is greater than 0, the double-time portion is the number of worked minutes above that threshold, floored at zero; when `daily_ot_threshold_minutes` is greater than 0, the daily-overtime portion is the portion of worked minutes between the daily OT threshold and the daily DT threshold (treating the DT threshold as unbounded when it is 0); the remainder of the entry's minutes accumulate into regular time."
        PRD §3.6: "Second, **weekly extraction**: the weekly overtime portion is the number of regular-time minutes remaining after daily extraction that exceeds the pack's `weekly_ot_threshold_minutes`, floored at zero; those minutes are moved from regular into overtime."

        Design: Difficulty/combinatorial_formula/gross_pay_multi_input_overtime
        """
        create_rule_pack("CC", daily_ot_threshold_minutes=480, daily_dt_threshold_minutes=720,
                         sit_rate=0.0)
        employer, worker, _a = setup_active_worker(
            "CC",
            worker_overrides={"ssn": "123456789"},
            agreement_overrides={"guaranteed_minutes_per_week": 2400},
            agencies=("NEW_HIRE_DIRECTORY", "SIT_WITHHOLDING", "SUTA"),
        )
        create_approved_timesheet(
            employer["id"], worker["id"], "2026-01-05", "2026-01-12",
            make_work_entries("2026-01-05", [660, 780, 480, 480, 300]),
        )
        run = setup_calculated_pay_run(employer["id"])
        pc = _single_paycheck(api, run["id"])
        # Daily: (660->180 OT), (780->240 OT + 60 DT); regular after daily 2220.
        # Weekly: max(0, 2220 - 2400) = 0.
        assert pc["regular_minutes"] == 2220
        assert pc["overtime_minutes"] == 420
        assert pc["double_minutes"] == 60

    def test_gross_combines_straight_ot_and_dt_rates(self, api):
        """PRD §3.6: "Final gross for a `TIMESHEET`-basis paycheck is the per-minute rate multiplied by the sum of `regular_minutes` and `guarantee_top_up_minutes`, plus the 1.5x per-minute rate — itself rounded half-up to cents per minute **before** being multiplied by the overtime minutes — multiplied by `overtime_minutes`, plus twice the per-minute rate multiplied by `double_minutes`."

        Design: Difficulty/combinatorial_formula/gross_pay_multi_input_overtime
        """
        create_rule_pack("CC", daily_ot_threshold_minutes=480, daily_dt_threshold_minutes=720,
                         sit_rate=0.0)
        employer, worker, _a = setup_active_worker(
            "CC",
            worker_overrides={"ssn": "123456789"},
            agreement_overrides={"guaranteed_minutes_per_week": 2400},
            agencies=("NEW_HIRE_DIRECTORY", "SIT_WITHHOLDING", "SUTA"),
        )
        create_approved_timesheet(
            employer["id"], worker["id"], "2026-01-05", "2026-01-12",
            make_work_entries("2026-01-05", [660, 780, 480, 480, 300]),
        )
        run = setup_calculated_pay_run(employer["id"])
        pc = _single_paycheck(api, run["id"])
        # 2220x50 + 420x75 + 60x100 = 111000 + 31500 + 6000 = 148500.
        assert pc["gross_cents"] == 148500
        # sit_rate 0.0 and gross below the FICA threshold -> no withholding lines.
        assert pc["net_pay_cents"] == 148500


class TestWithholdingPerLineRounding:
    def _setup_large_guarantee_paycheck(self, api):
        """Guarantee 6002 min/week at 50 cents/min -> GUARANTEE_FALLBACK gross 300100,
        which crosses the FICA coverage threshold at calculate time."""
        employer, worker, _a = setup_active_worker(
            "AA",
            worker_overrides={"ssn": "123456789"},
            agreement_overrides={"guaranteed_minutes_per_week": 6002},
            agencies=("NEW_HIRE_DIRECTORY", "SIT_WITHHOLDING", "SUTA"),
        )
        run = setup_calculated_pay_run(employer["id"])
        return employer, worker, run

    def test_each_withholding_line_rounded_half_up(self, api):
        """PRD §3.6: "The employee lines are: `SS_EE` at 6.2% of the SS base; `MEDICARE_EE` at 1.45% of all FICA wages including catch-up, uncapped; `ADDL_MEDICARE_EE` at 0.9% applied only to the portion of FICA wages that pushes year-to-date FICA wages above 20000000 cents ($200,000); `SIT_EE` at the pack's `sit_rate` times `gross_cents`; and `FIT_EE` as the flat `fit_withholding_cents_per_period` from the agreement."

        Design: Difficulty/combinatorial_formula/withholding_per_line_rounding
        """
        _e, _w, run = self._setup_large_guarantee_paycheck(api)
        pc = _single_paycheck(api, run["id"])
        assert pc["basis"] == "GUARANTEE_FALLBACK"
        assert pc["gross_cents"] == 300100
        # Per-line half-up: round(300100 x 0.062) = 18606, round(300100 x 0.0145) = 4351,
        # round(300100 x 0.05) = 15005.
        assert line_amount(pc["withholding_lines"], "SS_EE") == 18606
        assert line_amount(pc["withholding_lines"], "MEDICARE_EE") == 4351
        assert line_amount(pc["withholding_lines"], "SIT_EE") == 15005

    def test_zero_lines_omitted_and_net_uses_per_line_sum(self, api):
        """PRD §3.6: "Every line is rounded half-up to integer cents **before** any summation, and `net_pay_cents` is `gross_cents` minus the sum of the rounded withholding lines. Lines whose computed amount is 0 are omitted from the lines arrays."

        Design: Difficulty/combinatorial_formula/withholding_per_line_rounding
        """
        _e, _w, run = self._setup_large_guarantee_paycheck(api)
        pc = _single_paycheck(api, run["id"])
        assert line_amount(pc["withholding_lines"], "ADDL_MEDICARE_EE") is None
        assert line_amount(pc["withholding_lines"], "FIT_EE") is None
        # 300100 - (18606 + 4351 + 15005) = 262138; sum-then-round would give 262137.
        assert pc["net_pay_cents"] == 262138


class TestFluctuatingWorkweek:
    def _setup_fww_paycheck(self, api):
        create_rule_pack("DD", daily_ot_threshold_minutes=480, daily_dt_threshold_minutes=720,
                         live_in_weekly_ot_eligible=True, sit_rate=0.0)
        employer, worker, _a = setup_active_worker(
            "DD",
            worker_overrides={"ssn": "123456789", "work_arrangement": "LIVE_IN"},
            agreement_overrides={
                "pay_method": "GUARANTEED_SALARY_FWW",
                "guaranteed_minutes_per_week": 2400,
            },
            agencies=("NEW_HIRE_DIRECTORY", "SIT_WITHHOLDING", "SUTA"),
        )
        create_approved_timesheet(
            employer["id"], worker["id"], "2026-01-05", "2026-01-12",
            make_work_entries("2026-01-05", [602, 602, 602, 602, 602]),
        )
        run = setup_calculated_pay_run(employer["id"])
        return employer, worker, run

    def test_fww_effective_rate_at_four_decimals(self, api):
        """PRD §3.6: "Third, `fww_effective_rate_cents_per_minute` is the weekly guarantee pay (`guaranteed_minutes_per_week` times the per-minute straight rate) multiplied by the number of weeks in the period, divided by total worked minutes, and rounded half-up to exactly four decimal places."
        PRD §3.6: "Second, overtime minutes are the portion of total worked minutes above the pack's `weekly_ot_threshold_minutes`, floored at zero, when overtime is eligible for the worker's arrangement — daily thresholds never apply under FWW — and zero otherwise."

        Design: Difficulty/combinatorial_formula/fluctuating_workweek_circular_rate
        """
        _e, _w, run = self._setup_fww_paycheck(api)
        pc = _single_paycheck(api, run["id"])
        assert pc["pay_method"] == "GUARANTEED_SALARY_FWW"
        # round_half_up(120000 x 1 / 3010, 4) = 39.8671
        assert pc["fww_effective_rate_cents_per_minute"] == pytest.approx(39.8671, abs=1e-6)
        assert_cost_precision(pc["fww_effective_rate_cents_per_minute"], 4)
        assert pc["overtime_minutes"] == 610

    def test_fww_gross_adds_half_rate_premium(self, api):
        """PRD §3.6: "Fourth, the premium is half of `fww_effective_rate_cents_per_minute` multiplied by overtime minutes, rounded half-up to cents. Final gross is the weekly guarantee pay times weeks-in-period plus the premium; `provisional_gross_cents` is the weekly guarantee pay times weeks-in-period with no premium."

        Design: Difficulty/combinatorial_formula/fluctuating_workweek_circular_rate
        """
        _e, _w, run = self._setup_fww_paycheck(api)
        pc = _single_paycheck(api, run["id"])
        assert pc["provisional_gross_cents"] == 120000
        # 120000 + round_half_up(0.5 x 39.8671 x 610) = 120000 + 12159 = 132159.
        assert pc["gross_cents"] == 132159
        assert pc["net_pay_cents"] == 132159


class TestGuaranteeTopUp:
    def test_top_up_pays_shortfall_at_straight_time(self, api):
        """PRD §3.6: "Third, **guarantee top-up**: the period's guaranteed minutes equal `guaranteed_minutes_per_week` multiplied by the number of weeks in the period (1 for `WEEKLY`, 2 for `BIWEEKLY`, 2 for `SEMIMONTHLY`, 4 for `MONTHLY`); `guarantee_top_up_minutes` is the excess of that guarantee over total worked minutes, floored at zero, paid at straight time and excluded from overtime bases."

        Design: Corner/calculations/guarantee_top_up_pays_shortfall_at_straight_time
        """
        employer, worker, _a = setup_active_worker(
            "AA",
            worker_overrides={"ssn": "123456789"},
            agreement_overrides={"guaranteed_minutes_per_week": 2400},
            agencies=("NEW_HIRE_DIRECTORY", "SIT_WITHHOLDING", "SUTA"),
        )
        create_approved_timesheet(
            employer["id"], worker["id"], "2026-01-05", "2026-01-12",
            make_work_entries("2026-01-05", [500, 500, 500, 500]),
        )
        run = setup_calculated_pay_run(employer["id"])
        pc = _single_paycheck(api, run["id"])
        assert pc["guarantee_top_up_minutes"] == 400
        assert pc["regular_minutes"] == 2000
        assert pc["overtime_minutes"] == 0
        assert pc["gross_cents"] == 120000
        assert pc["provisional_gross_cents"] == 120000
        # SIT round_half_up(120000 x 0.05) = 6000; no FICA below 280000.
        assert pc["net_pay_cents"] == 114000


class TestAdditionalMedicareAndSsWageBase:
    def test_large_check_caps_ss_base_and_applies_additional_medicare(self, api):
        """PRD §3.6: "Within coverage, Social Security is further capped: the SS base is the lesser of `gross_cents` and the room remaining under the SS wage base of 17610000 cents ($176,100) after `ss_wages_paid_ytd_cents`, with the catch-up portion included in that base."
        PRD §3.6: "`ADDL_MEDICARE_EE` at 0.9% applied only to the portion of FICA wages that pushes year-to-date FICA wages above 20000000 cents ($200,000);"

        Design: Corner/calculations/additional_medicare_over_200k
        """
        employer, worker, _a = setup_active_worker(
            "AA",
            worker_overrides={"ssn": "123456789"},
            agreement_overrides={"guaranteed_minutes_per_week": 402000},
            agencies=("NEW_HIRE_DIRECTORY", "SIT_WITHHOLDING", "SUTA"),
        )
        run = setup_calculated_pay_run(employer["id"])
        pc = _single_paycheck(api, run["id"])
        assert pc["gross_cents"] == 20100000
        # SS base capped at 17610000: round(17610000 x 0.062) = 1091820.
        assert line_amount(pc["withholding_lines"], "SS_EE") == 1091820
        # Medicare uncapped: round(20100000 x 0.0145) = 291450.
        assert line_amount(pc["withholding_lines"], "MEDICARE_EE") == 291450
        # Additional Medicare on the 100000 cents above 20000000: round(100000 x 0.009) = 900.
        assert line_amount(pc["withholding_lines"], "ADDL_MEDICARE_EE") == 900
        assert line_amount(pc["withholding_lines"], "SIT_EE") == 1005000
        assert pc["net_pay_cents"] == 17710830


class TestSutaWageBaseCap:
    def test_suta_base_exhausted_across_runs(self, api):
        """PRD §3.8: "SUTA follows the same shape per worker per year against the pack's `suta_wage_base_cents` and `suta_rate`, with the per-worker `suta_wages_paid_ytd` accumulator tracked inside the `TaxLiabilityAccount` accrual."
        PRD §3.6: "Lines whose computed amount is 0 are omitted from the lines arrays."

        Design: Corner/calculations/suta_wage_base_cap_across_runs
        """
        create_rule_pack("HH", sit_rate=0.0, suta_wage_base_cents=150000)
        employer, worker, _a = setup_active_worker(
            "HH",
            worker_overrides={"ssn": "123456789"},
            agreement_overrides={"guaranteed_minutes_per_week": 4000},
            agencies=("NEW_HIRE_DIRECTORY", "SIT_WITHHOLDING", "SUTA"),
        )
        run1 = setup_finalized_pay_run(employer["id"], "2026-01-05", "2026-01-12", "2026-01-12")
        run2 = setup_finalized_pay_run(employer["id"], "2026-01-12", "2026-01-19", "2026-01-19")

        pc1 = _single_paycheck(api, run1["id"])
        # Gross 200000; SUTA base min(200000, 150000) -> round(150000 x 0.02) = 3000.
        assert line_amount(pc1["employer_tax_lines"], "SUTA_ER") == 3000
        assert line_amount(pc1["employer_tax_lines"], "FUTA_ER") == 1200

        pc2 = _single_paycheck(api, run2["id"])
        # Wage base exhausted: the zero SUTA line is omitted entirely.
        assert line_amount(pc2["employer_tax_lines"], "SUTA_ER") is None
        assert line_amount(pc2["employer_tax_lines"], "FUTA_ER") == 1200


class TestPayRunDerivedTotalsAndGuards:
    def test_calculate_response_reconciles_totals(self, api):
        """PRD §3.6: "After computation, `recalc_status` is set to `CURRENT` and the pay run's `total_gross_cents`, `total_net_cents`, and `total_employer_tax_cents` are recomputed as sums over member paychecks whose `status` is not `VOIDED`."

        Design: Corner/cross_cutting_layers/derived_field_payrun_totals_at_calculate
        """
        employer, worker, _a = setup_active_worker(
            "AA",
            agreement_overrides={"guaranteed_minutes_per_week": 2400},
            agencies=("NEW_HIRE_DIRECTORY", "SIT_WITHHOLDING", "SUTA"),
        )
        run = create_pay_run(employer["id"], "2026-01-05", "2026-01-12", "2026-01-12")
        resp = api.calculate_pay_run(run["id"], make_payroll_admin_headers())
        data = validate_success(resp, 200)
        assert data["status"] == "CALCULATED"
        assert data["recalc_status"] == "CURRENT"
        # Guarantee 2400 x 50 = 120000 gross; SIT 6000; net 114000.
        assert data["total_gross_cents"] == 120000
        assert data["total_net_cents"] == 114000
        # FUTA applies (120000 >= 100000): 720; SUTA round(120000 x 0.02) = 2400.
        assert data["total_employer_tax_cents"] == 3120

    def test_calculate_when_current_returns_invalid_state(self, api):
        """PRD §3.6: "A `PayrollAdmin` runs calculation against an `OPEN` pay run, or against a `CALCULATED` pay run whose `recalc_status` is `STALE`; any other from-state is rejected with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/payrun_calculate_when_current_returns_invalid_state
        """
        employer, worker, _a = setup_active_worker(
            "AA", agreement_overrides={"guaranteed_minutes_per_week": 2400}
        )
        run = setup_calculated_pay_run(employer["id"])
        assert run["recalc_status"] == "CURRENT"
        resp = api.calculate_pay_run(run["id"], make_payroll_admin_headers())
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_payrun_period_span_mismatch_returns_422(self, api):
        """PRD §3.6: "the period's span must match the employer's `pay_frequency` exactly: 7 days for `WEEKLY`, 14 days for `BIWEEKLY`, the `[1, 16)` or `[16, 1st-of-next-month)` half-months for `SEMIMONTHLY`, or a calendar month for `MONTHLY`. A mismatched span is rejected with `ERR_PERIOD_LENGTH_MISMATCH` (HTTP 422)."

        Design: Corner/validations/payrun_period_length_mismatch_returns_422
        """
        employer = setup_registered_employer("AA", agencies=("NEW_HIRE_DIRECTORY",))
        resp = api.create_pay_run(
            employer["id"],
            {"period_start": "2026-01-05", "period_end": "2026-01-13", "pay_date": "2026-01-13"},
            make_payroll_admin_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_PERIOD_LENGTH_MISMATCH)

    def test_payrun_overlap_returns_409(self, api):
        """PRD §3.6: "The half-open period must not overlap any other non-terminal pay run of the same employer (otherwise `ERR_PAYRUN_OVERLAP`, HTTP 409), and the period's span must match the employer's `pay_frequency` exactly: 7 days for `WEEKLY`, 14 days for `BIWEEKLY`, the `[1, 16)` or `[16, 1st-of-next-month)` half-months for `SEMIMONTHLY`, or a calendar month for `MONTHLY`."

        Design: Corner/validations/payrun_overlap_returns_409
        """
        employer = setup_registered_employer("AA", agencies=("NEW_HIRE_DIRECTORY",))
        create_pay_run(employer["id"], "2026-01-05", "2026-01-12", "2026-01-12")
        resp = api.create_pay_run(
            employer["id"],
            {"period_start": "2026-01-07", "period_end": "2026-01-14", "pay_date": "2026-01-14"},
            make_payroll_admin_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_PAYRUN_OVERLAP)
