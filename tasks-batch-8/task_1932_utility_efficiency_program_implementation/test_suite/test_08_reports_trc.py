"""Cost-effectiveness reporting: aggregate inputs, the 12-year discounted
benefit series, the trc_ratio, and the threshold flag bands."""
import pytest

from test_helpers import (
    TEST_USERS,
    create_completed_project,
    create_report_payload,
    set_clock,
    validate_success,
)

PM = TEST_USERS["program_manager_headers"]


def _program_with_one_paid_project(api):
    """One COMPLETED project (3,000 kWh savings, 400,000-cent installed cost,
    incentive 62,000 provisional == final) with its payment disbursed.

    Returns (program, payment, report context dict).
    """
    set_clock("2026-08-01T00:00:00Z")
    ctx = create_completed_project(
        pass_score_bps=9000,
        program_overrides={"budget_cents": 10000000, "trc_threshold": 1.0},
        lead_overrides={"estimated_annual_kwh_savings": 3000},
        project_overrides={"measure_cost_cents": 400000,
                           "estimated_annual_kwh_savings": 3000,
                           "incentive_recipient": "CUSTOMER"},
        install_date="2026-08-02T00:00:00Z",
    )
    payment = ctx["payment"]
    assert payment["amount_cents"] == 62000  # 2000*25 + 1000*12, no cost adj.
    validate_success(api.disburse_payment(payment["id"], PM), 200)
    return ctx


def _create_report(api, program_id):
    resp = api.create_report(create_report_payload(program_id), PM)
    return validate_success(resp, expected_status=201)


class TestTrcRatioThresholdFlagVariants:
    def test_report_aggregates_completed_project_population(self, api, pm_headers):
        """PRD 3.9: "From this population, `total_avoided_kwh` sums the
        projects' `estimated_annual_kwh_savings`, and
        `total_incentive_paid_cents` sums the payments' `amount_cents`."

        Design: Difficulty/dual_variant_calc/trc_ratio_threshold_flag_variants
        """
        ctx = _program_with_one_paid_project(api)
        report = _create_report(api, ctx["program"]["id"])
        assert report["status"] == "DRAFT"
        assert report["total_avoided_kwh"] == 3000
        assert report["total_incentive_paid_cents"] == 62000

    def test_trc_flag_derived_from_threshold_breakpoints(self, api, pm_headers):
        """PRD 3.9: "`PASS` when the ratio meets or exceeds the threshold;
        `MARGINAL` when the ratio falls below the threshold by no more than
        0.10 — a ratio exactly 0.10 under the threshold still earns `MARGINAL`;
        and `FAIL` when the ratio falls more than 0.10 below the threshold."
        Here the ratio is ~0.6882 against a threshold of 1.00: more than 0.10
        below, so the flag is FAIL.

        Design: Difficulty/dual_variant_calc/trc_ratio_threshold_flag_variants
        """
        ctx = _program_with_one_paid_project(api)
        report = _create_report(api, ctx["program"]["id"])
        assert report["trc_ratio"] == pytest.approx(0.6882, abs=0.00005)
        assert report["trc_flag"] == "FAIL"


class TestTrcNpvMultiYearDiscount:
    def test_denominator_terms_visible_on_report(self, api, pm_headers):
        """PRD 3.9: "The denominator adds three terms:
        `total_incentive_paid_cents`, `total_admin_cost_cents`, and the
        aggregate customer incremental cost, where each completed project in
        the window contributes the positive part of its `measure_cost_cents`
        minus its incentive amount".
        Denominator here: 62,000 + 50,000 + (400,000 - 62,000) = 450,000; the
        two report-visible terms are 62,000 and 50,000.

        Design: Difficulty/combinatorial_formula/trc_npv_multi_year_discount
        """
        ctx = _program_with_one_paid_project(api)
        report = _create_report(api, ctx["program"]["id"])
        assert report["total_incentive_paid_cents"] == 62000
        assert report["total_admin_cost_cents"] == 50000
        assert report["total_avoided_kwh"] == 3000

    def test_trc_ratio_is_discounted_benefit_over_denominator(self, api, pm_headers):
        """PRD 3.9: "for each year from the first through the twelfth, that
        year's avoided-cost value — the report's `total_avoided_kwh` multiplied
        by 11 cents — is divided by 1.04 raised to the power of the year
        number, and the twelve discounted terms are summed" and "The
        `trc_ratio` is the discounted benefit divided by this denominator,
        which must be greater than zero, and is rounded half up to four decimal
        places."
        Benefit = sum_{t=1..12} 33,000 / 1.04^t = 309,707.4341 cents;
        denominator = 450,000; ratio = 0.6882.

        Design: Difficulty/combinatorial_formula/trc_npv_multi_year_discount
        """
        ctx = _program_with_one_paid_project(api)
        report = _create_report(api, ctx["program"]["id"])
        assert report["trc_ratio"] == pytest.approx(0.6882, abs=0.00005)
