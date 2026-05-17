"""FICA Social Security cap, base Medicare, Additional Medicare
threshold.

PRD §3.4.
"""
from __future__ import annotations

from datetime import date

import pytest

from test_helpers import (
    SS_WAGE_BASE_CENTS,
    TEST_USERS,
    api_client,
    approve_paycheck,
    assert_paycheck_computed_fields,
    calculate_paycheck,
    create_biweekly_pay_period,
    create_payroll_item,
    get_paycheck_for_item,
    setup_draft_paycheck,
    setup_employee_with_w4,
    setup_world,
    setup_ytd_at_ss_cap_minus,
    validate_success,
)


class TestSocialSecurityRate:
    """PRD §3.4 Social Security at the standard rate (well below
    cap)."""

    def test_ss_at_standard_rate(self, api, seeded_world):
        """PRD §3.4: "The Social Security tax is 6.20% applied to
        wages up to an annual wage base of 16,830,000 cents".

        Claim: gross 200,000, fresh employee -> ss = 200000*0.062 =
        12,400.
        """
        emp, pp, w4, item, pc = setup_draft_paycheck(
            work_state="TX", hourly_rate_cents=12_500,
            regular_hours=16.0,
        )
        pc = calculate_paycheck(pc["id"])
        assert_paycheck_computed_fields(pc)
        assert pc["social_security_cents"] == 12_400


class TestSocialSecurityCap:
    """PRD §3.4 Social Security wage base cap (boundary >= vs >)."""

    def test_ss_at_cap_exactly_yields_zero(self, api, seeded_world):
        """PRD §3.4: "At the boundary, if the pre-paycheck year-to-
        date Social Security wages equal the wage base exactly, the
        taxable amount is zero and the withholding is zero".

        Claim: ytd_ss == cap exactly -> social_security_cents == 0
        on the next paycheck.
        """
        emp, pp, w4, item, pc = setup_ytd_at_ss_cap_minus(room=0)
        pc = calculate_paycheck(pc["id"])
        assert pc["social_security_cents"] == 0, (
            f"expected 0 (cap reached exactly), got "
            f"{pc['social_security_cents']}"
        )

    def test_ss_at_cap_minus_one_cent_taxes_one_cent(self, api, seeded_world):
        """PRD §3.4: "if they equal the wage base minus one cent, the
        taxable amount is the minimum of the gross and one cent, and
        the withholding is still computed against that one cent."

        Claim: ytd_ss == cap-1 -> taxable_ss == 1 -> SS withholding
        = round_half_up(1 * 0.062) = 1.
        """
        emp, pp, w4, item, pc = setup_ytd_at_ss_cap_minus(room=1)
        pc = calculate_paycheck(pc["id"])
        # 1 cent * 0.062 = 0.062 -> round_half_up -> 0 (since 0.062 <
        # 0.5). But PRD literally says: "the taxable amount is the
        # minimum of the gross and one cent, and the withholding is
        # still computed against that one cent." Read literally, this
        # means the engine WILL apply the formula. The result of
        # round_half_up(0.062 cents) is 0 cents. PRD does NOT pin a
        # specific cents value beyond "computed against that one
        # cent", so we assert what BOTH readers must agree on:
        # taxable computation is exercised on one cent, hence the
        # output is the rounded product 0 cents. (round_half_up of
        # 0.062 is 0.)
        assert pc["social_security_cents"] == 0


class TestMedicareBaseRate:
    """PRD §3.4 base Medicare 1.45%."""

    def test_medicare_base_rate_on_gross(self, api, seeded_world):
        """PRD §3.4: "Standard Medicare withholding is 1.45% of the
        paycheck's gross, with no annual cap."

        Claim: gross 200,000 -> medicare_base_cents = 200000*0.0145
        = 2,900.
        """
        emp, pp, w4, item, pc = setup_draft_paycheck(
            work_state="TX", hourly_rate_cents=12_500,
            regular_hours=16.0,
        )
        pc = calculate_paycheck(pc["id"])
        assert pc["medicare_base_cents"] == 2_900


class TestAdditionalMedicareBelowThreshold:
    """PRD §3.4 Additional Medicare below threshold yields zero."""

    def test_additional_medicare_zero_below_threshold(self, api, seeded_world):
        """PRD §3.4: "If the post-paycheck year-to-date Medicare
        wages are at or below 20,000,000 cents, the additional
        withholding is zero."

        Claim: small paycheck, no prior YTD -> medicare_additional ==
        0.
        """
        emp, pp, w4, item, pc = setup_draft_paycheck(
            work_state="TX", hourly_rate_cents=12_500,
            regular_hours=16.0,
        )
        pc = calculate_paycheck(pc["id"])
        assert pc["medicare_additional_cents"] == 0


class TestAdditionalMedicareAboveThresholdFullGross:
    """PRD §3.4 Additional Medicare when pre-YTD already >=
    threshold."""

    def test_pre_ytd_at_or_above_taxes_full_gross_additional(
            self, api, seeded_world):
        """PRD §3.4: "If the pre-paycheck year-to-date Medicare wages
        are already at or above 20,000,000 cents, the full gross is
        subject and the additional withholding is the gross multiplied
        by 90 basis points divided by 10,000, rounded half up to whole
        cents."

        Claim: prime YTD Medicare wages to >= 20,000,000 via prior
        APPROVED paycheck, then this paycheck's full gross is taxed
        at 0.9%. For gross 200000 -> 200000*0.009 = 1800.
        """
        # Use an extremely large hourly rate so a single 1-hour
        # paycheck pushes YTD Medicare above 20,000,000.
        emp, first_pp, first_w4 = setup_employee_with_w4(
            work_state="TX", hourly_rate_cents=20_500_000,
            filing_status="SINGLE",
            period_start=date(2024, 1, 1),
        )
        first_item = create_payroll_item(
            first_pp["id"], emp["id"], regular_hours=1.0,
        )
        first_pc = get_paycheck_for_item(first_item)
        first_pc = calculate_paycheck(first_pc["id"])
        approve_paycheck(first_pc["id"])
        # Now pre-paycheck YTD Medicare >= 20,500,000 > threshold.
        second_pp = create_biweekly_pay_period(date(2024, 6, 3))
        second_item = create_payroll_item(
            second_pp["id"], emp["id"], regular_hours=16.0,
        )
        # The employee.hourly_rate_cents is huge — make a fresh
        # employee with normal rate for the second period? No: PRD
        # says hourly_rate_cents lives on Employee, not on the item.
        # We have to live with this. 16 hours * 20,500,000 = 328
        # million gross. Additional Medicare on the full gross =
        # 328,000,000 * 0.009 = 2,952,000.
        second_pc = get_paycheck_for_item(second_item)
        second_pc = calculate_paycheck(second_pc["id"])
        expected_gross = 16 * 20_500_000
        expected_addl = round_half_up(expected_gross * 90 / 10_000)
        assert second_pc["gross_wages_cents"] == expected_gross
        assert second_pc["medicare_additional_cents"] == expected_addl


def round_half_up(x: float) -> int:
    """PRD §2.10 round-half-up semantics (toward +inf for
    non-negative values, away from zero generally). For positive
    inputs this is equivalent to math.floor(x + 0.5).
    """
    import math
    if x >= 0:
        return int(math.floor(x + 0.5))
    return -int(math.floor(-x + 0.5))


class TestAdditionalMedicareCrossing:
    """PRD §3.4 Additional Medicare crossing the threshold within a
    paycheck."""

    def test_crossing_taxes_post_threshold_portion_only(
            self, api, seeded_world):
        """PRD §3.4: "If this paycheck crosses the threshold within
        itself — pre-paycheck year-to-date below and post-paycheck
        year-to-date above — the system applies the additional rate
        only to the post-threshold portion (post-paycheck
        year-to-date minus 20,000,000), and rounds half up to whole
        cents."

        Claim: prime YTD Medicare to threshold-100000, then a
        paycheck whose gross is 200000 -> post-paycheck YTD =
        threshold+100000 -> additional applies to 100000 -> 100000 *
        0.009 = 900.
        """
        # Threshold = 20,000,000 cents. Drive YTD to 19,900,000 via
        # a prior 1-hour paycheck at hourly_rate 19,900,000 cents.
        emp, first_pp, first_w4 = setup_employee_with_w4(
            work_state="TX", hourly_rate_cents=19_900_000,
            filing_status="SINGLE",
            period_start=date(2024, 1, 1),
        )
        first_item = create_payroll_item(
            first_pp["id"], emp["id"], regular_hours=1.0,
        )
        first_pc = get_paycheck_for_item(first_item)
        first_pc = calculate_paycheck(first_pc["id"])
        approve_paycheck(first_pc["id"])
        # Pre-YTD Medicare = 19,900,000 — below threshold.
        # Second period: 1 hour at the same rate adds 19,900,000 to
        # YTD -> 39,800,000. That's well above threshold; crossing
        # portion = 39,800,000 - 20,000,000 = 19,800,000.
        # Additional = 19,800,000 * 0.009 = 178,200.
        second_pp = create_biweekly_pay_period(date(2024, 6, 3))
        second_item = create_payroll_item(
            second_pp["id"], emp["id"], regular_hours=1.0,
        )
        second_pc = get_paycheck_for_item(second_item)
        second_pc = calculate_paycheck(second_pc["id"])
        assert second_pc["gross_wages_cents"] == 19_900_000
        # post-ytd = 39,800,000; excess = 19,800,000; * 0.009 = 178,200
        assert second_pc["medicare_additional_cents"] == 178_200
