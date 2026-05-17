"""Paycheck calculation: gross, federal withholding (default annualized,
supplemental flat-rate retro variant), state, local, and net pay.

PRD §3.4.
"""
from __future__ import annotations

from datetime import date

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_paycheck_computed_fields,
    assert_paycheck_net_pay_invariant,
    calculate_paycheck,
    create_payroll_item,
    create_w4_profile,
    setup_draft_paycheck,
    setup_employee_with_w4,
    setup_world,
    validate_error,
    validate_success,
)


# --- Reference computations against PRD §3.4 -------------------------------
# 16 regular hours × 12500 cents/hour = 200000 cents gross.
# Annualized: 200000 * 26 = 5,200,000 cents.
# SINGLE standard deduction = 1,390,000.
# Taxable annual = 5,200,000 - 1,390,000 = 3,810,000.
# Federal SINGLE bracket walk:
#   tier 1 (0..1,100,000 @10%):    1,100,000 * 0.10 = 110,000
#   tier 2 (1,100,000..3,810,000 @12%): 2,710,000 * 0.12 = 325,200
#   annual_tax = 110,000 + 325,200 = 435,200
#   per_period = 435,200 / 26 = 16,738.4615... -> 16,738 (round_half_up)
# These are the values pinned by SCAFFOLD_DIFFICULTY_DESIGN §1.


class TestGrossWages:
    """PRD §3.4 gross_wages_cents formula."""

    def test_gross_regular_only(self, api, seeded_world):
        """PRD §3.4: "The paycheck's gross_wages_cents is the sum of
        four contributions: the regular hours multiplied by the
        hourly rate, the overtime hours multiplied by one-and-one-
        half times the hourly rate, the double hours multiplied by
        two times the hourly rate, and the retro adjustment."

        Claim: regular_hours=16 at 12500 -> gross=200000.
        """
        emp, pp, w4, item, pc = setup_draft_paycheck(
            work_state="TX",
            hourly_rate_cents=12_500,
            regular_hours=16.0,
        )
        pc = calculate_paycheck(pc["id"])
        assert_paycheck_computed_fields(pc)
        assert pc["gross_wages_cents"] == 200_000

    def test_gross_overtime_doubled_one_and_a_half(self, api, seeded_world):
        """PRD §3.4: "the overtime hours multiplied by one-and-one-
        half times the hourly rate".

        Claim: 10 hours overtime at 12500 -> gross = 10*1.5*12500 =
        187,500.
        """
        emp, pp, w4, item, pc = setup_draft_paycheck(
            work_state="TX",
            hourly_rate_cents=12_500,
            regular_hours=0,
            overtime_hours=10.0,
        )
        pc = calculate_paycheck(pc["id"])
        assert pc["gross_wages_cents"] == 187_500

    def test_gross_double_hours_doubled(self, api, seeded_world):
        """PRD §3.4: "the double hours multiplied by two times the
        hourly rate".

        Claim: 10 hours double at 12500 -> gross = 10*2*12500 =
        250,000.
        """
        emp, pp, w4, item, pc = setup_draft_paycheck(
            work_state="TX",
            hourly_rate_cents=12_500,
            regular_hours=0,
            double_hours=10.0,
        )
        pc = calculate_paycheck(pc["id"])
        assert pc["gross_wages_cents"] == 250_000

    def test_gross_includes_retro_adjustment(self, api, seeded_world):
        """PRD §3.4: "the regular hours multiplied by the hourly
        rate ... and the retro adjustment" all contribute to gross.

        Claim: 16h + 100000 retro -> 200000 + 100000 = 300000.
        """
        emp, pp, w4, item, pc = setup_draft_paycheck(
            work_state="TX",
            hourly_rate_cents=12_500,
            regular_hours=16.0,
            retro_adjustment_cents=100_000,
        )
        pc = calculate_paycheck(pc["id"])
        assert pc["gross_wages_cents"] == 300_000


class TestFederalWithholdingStandard:
    """PRD §3.4 federal income tax — default annualized method."""

    def test_federal_withholding_single_16_hours(self, api, seeded_world):
        """PRD §3.4: "The system first multiplies the paycheck's
        gross by 26 (the number of biweekly pay periods per year) to
        obtain an annualized wage ... subtracts the standard
        deduction corresponding to the filing status — 1,390,000
        cents for SINGLE ... applies the federal piecewise bracket
        table for the filing status ... The result is divided by 26
        to produce the per-paycheck withholding".
        PRD §3.4: "The federal bracket table for SINGLE is four
        tiers: 10.00% on income from 0 up to 1,100,000 cents, 12.00%
        on income from 1,100,000 to 4,475,000 cents".

        Claim: SINGLE, 16h * 12500 -> federal_withholding_cents ==
        16738. (Annualized 5,200,000; less 1,390,000 = 3,810,000;
        tier1 = 110,000; tier2 = 325,200; annual = 435,200; /26 =
        16,738.46... rounds half up to 16,738.)
        """
        emp, pp, w4, item, pc = setup_draft_paycheck(
            work_state="TX",
            hourly_rate_cents=12_500,
            filing_status="SINGLE",
            regular_hours=16.0,
        )
        pc = calculate_paycheck(pc["id"])
        assert pc["federal_withholding_cents"] == 16_738, (
            f"expected 16738, got {pc['federal_withholding_cents']}"
        )


class TestFederalSupplementalRetro:
    """PRD §3.4 federal supplemental flat-rate variant for retro."""

    def test_retro_yields_supplemental_split(self, api, seeded_world):
        """PRD §3.4: "When the retro adjustment is non-zero, the
        system splits the paycheck into two pieces. The non-retro
        portion (regular plus overtime plus double, computed as
        gross minus the retro adjustment) is run through the same
        annualized method described above, ignoring the retro
        contribution. Independently, the retro adjustment itself is
        multiplied by the IRS supplemental flat rate of 22.00% (no
        annualization, no bracket evaluation, no standard
        deduction), and the result is rounded half up to whole cents.
        The two pieces are then summed to produce the federal
        withholding."

        Claim: SINGLE, 16h*12500 + 100000 retro -> fed = 16738 +
        22000 = 38738.
        """
        emp, pp, w4, item, pc = setup_draft_paycheck(
            work_state="TX",
            hourly_rate_cents=12_500,
            filing_status="SINGLE",
            regular_hours=16.0,
            retro_adjustment_cents=100_000,
        )
        pc = calculate_paycheck(pc["id"])
        assert pc["federal_withholding_cents"] == 38_738, (
            f"expected 38738 (=16738 standard + 22000 supplemental on "
            f"retro), got {pc['federal_withholding_cents']}"
        )

    def test_retro_only_produces_supplemental_only(self, api, seeded_world):
        """PRD §3.4: "the retro adjustment itself is multiplied by
        the IRS supplemental flat rate of 22.00% (no annualization,
        no bracket evaluation, no standard deduction)".

        Claim: hours=0, retro=100000 -> non-retro portion zero
        annualized to zero tax + supplemental 22000. Total = 22000.
        """
        emp, pp, w4, item, pc = setup_draft_paycheck(
            work_state="TX",
            hourly_rate_cents=12_500,
            filing_status="SINGLE",
            regular_hours=0,
            retro_adjustment_cents=100_000,
        )
        pc = calculate_paycheck(pc["id"])
        # Non-retro portion = 0; annualized 0; standard deduction
        # floor at 0 -> tax = 0. Supplemental = 100000 * 0.22 = 22000.
        assert pc["federal_withholding_cents"] == 22_000, (
            f"expected 22000 supplemental-only on retro, got "
            f"{pc['federal_withholding_cents']}"
        )


class TestStateWithholdingFlatRates:
    """PRD §3.4 state withholding for flat-rate states."""

    def test_tx_state_withholding_zero(self, api, seeded_world):
        """PRD §3.4: "TX is a single-bracket flat rate of 0% — i.e.,
        Texas produces zero state withholding."

        Claim: TX employee -> state_withholding_cents == 0.
        """
        emp, pp, w4, item, pc = setup_draft_paycheck(
            work_state="TX",
            hourly_rate_cents=12_500,
            regular_hours=16.0,
        )
        pc = calculate_paycheck(pc["id"])
        assert pc["state_withholding_cents"] == 0


class TestLocalWithholding:
    """PRD §3.4 local withholding."""

    def test_locality_none_yields_zero_local(self, api, seeded_world):
        """PRD §3.4: "When work_locality is NONE, the paycheck's
        local_withholding_cents is exactly zero."

        Claim: work_locality=NONE -> local_withholding_cents == 0.
        """
        emp, pp, w4, item, pc = setup_draft_paycheck(
            work_state="TX", work_locality=None,
            hourly_rate_cents=12_500, regular_hours=16.0,
        )
        pc = calculate_paycheck(pc["id"])
        assert pc["local_withholding_cents"] == 0

    def test_nyc_local_flat_rate_on_gross(self, api, seeded_world):
        """PRD §3.4: "Otherwise the system applies a flat rate to
        the gross (no annualization) according to the locality: NYC
        is 3.80% of gross".

        Claim: NY/NYC, 16h*12500=200000 gross -> local = 200000 *
        0.038 = 7600.
        """
        emp, pp, w4, item, pc = setup_draft_paycheck(
            work_state="NY", work_locality="NYC",
            hourly_rate_cents=12_500, regular_hours=16.0,
        )
        pc = calculate_paycheck(pc["id"])
        assert pc["local_withholding_cents"] == 7_600

    def test_phl_local_flat_rate_on_gross(self, api, seeded_world):
        """PRD §3.4: "PHL is 3.50% of gross."

        Claim: PA/PHL, 16h*12500=200000 -> local = 200000*0.035 =
        7000.
        """
        emp, pp, w4, item, pc = setup_draft_paycheck(
            work_state="PA", work_locality="PHL",
            hourly_rate_cents=12_500, regular_hours=16.0,
        )
        pc = calculate_paycheck(pc["id"])
        assert pc["local_withholding_cents"] == 7_000


class TestNetPayInvariant:
    """PRD §3.4 net pay invariant."""

    def test_net_pay_equals_gross_minus_withholdings(self, api, seeded_world):
        """PRD §3.4: "The paycheck's net_pay_cents is
        gross_wages_cents minus federal, state, and local
        withholdings, minus Social Security, base Medicare, and
        Additional Medicare, minus garnishment_total_cents".

        Claim: stored net_pay_cents equals the exact integer
        difference.
        """
        emp, pp, w4, item, pc = setup_draft_paycheck(
            work_state="TX", hourly_rate_cents=12_500,
            regular_hours=16.0,
        )
        pc = calculate_paycheck(pc["id"])
        assert_paycheck_net_pay_invariant(pc)
