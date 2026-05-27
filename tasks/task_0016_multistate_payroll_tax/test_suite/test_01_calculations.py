"""Withholding pipeline calculations — gross wages, federal income tax,
state/local income tax, FICA Social Security, base Medicare, additional Medicare.

Drives instances from both queue (A) difficulty design and queue (B) corner design.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    set_clock,
    seed_federal_tax_table_2025_single,
    seed_california_tax_table_2025,
    seed_federal_and_california_2025,
    seed_ny_tax_tables_2025,
    setup_employee_with_filed_w4,
    create_draft_paycheck_run,
    attach_regular_paycheck,
    attach_overtime_paycheck,
    attach_double_paycheck,
    attach_retro_paycheck,
    approve_run,
    pay_run,
    create_employee,
    create_and_file_w4,
    seed_employee_ytd,
    get_employee,
    get_paycheck,
    create_paycheck_payload,
    regular_paycheck_payload,
    TEST_USERS,
)


# =========================================================================
# Queue (A) Difficulty — rule 1 dual_variant_calc
# =========================================================================

class TestProvisionalVsReconciledFederalWithholding:
    """The is_year_end_run flag swaps the federal withholding variant per PRD §3.4."""

    def test_year_end_run_recomputes_fed_with_reconciled_variant(self, api):
        """PRD §3.4: "The reconciled variant runs only when the pay request that
        advances a run from `APPROVED` to `PAID` carries `is_year_end_run` set to
        true in its request body."
        PRD §3.4: "annual_wages_actual is Employee.ytd_wages_cents *before* this
        paycheck plus this paycheck's gross_wages_cents"
        PRD §3.4: "fed_withheld_cents for this paycheck is the larger of zero and
        that adjusted annual tax minus Employee.ytd_fed_withheld_cents *before*
        this paycheck."

        Fresh employee (ytd zero); a $2000 REGULAR paycheck under is_year_end_run=true
        runs the reconciled variant: adjusted_annual = 200000 - 1460000 = negative,
        all brackets skipped, annual_tax_actual = 0, fed_withheld_cents = 0.

        Design: Difficulty/dual_variant_calc/paycheck_fed_withholding_provisional_vs_reconciled
        """
        set_clock("2025-12-15T00:00:00.000Z")
        seed_federal_and_california_2025()
        emp, _ = setup_employee_with_filed_w4()
        run = create_draft_paycheck_run(
            pay_period_start="2025-12-15T00:00:00.000Z",
            pay_period_end="2025-12-31T23:59:59.999Z",
            pay_date="2025-12-31T00:00:00.000Z",
        )
        pay = attach_regular_paycheck(run["id"], emp["id"])
        approve_run(run["id"])
        pay_run(run["id"], is_year_end_run=True)

        check = get_paycheck(pay["id"])
        assert check["fed_withheld_cents"] == 0, \
            f"reconciled fed_withheld for ytd=0 employee w/ adjusted_annual<0 must be 0, got {check['fed_withheld_cents']}"
        assert check["gross_wages_cents"] == 200000
        assert check["status"] == "PAID"

    def test_provisional_variant_uses_per_paycheck_percentage_method(self, api):
        """PRD §3.4: "Provisional federal withholding (`fed_withheld_cents`) is
        computed at paycheck creation by the per-paycheck percentage method"
        PRD §3.4: "The procedure projects the current paycheck's gross to an
        annual figure by multiplying it by `PAY_PERIODS_PER_YEAR`, which is 26
        (biweekly)."
        PRD §3.4: "the standard deduction for the filer's `filing_status` —
        `1,460,000` cents (\\$14,600.00) for `SINGLE`"

        Fresh SINGLE employee with $2000 REGULAR paycheck:
        annual_wages = 200000 × 26 = 5,200,000
        adjusted_annual = 5,200,000 - 1,460,000 = 3,740,000
        bracket math (10/12/22 schedule): 117500 + 307800 = 425,300 annual
        per_pay = 425300 // 26 = 16,357

        Design: Difficulty/dual_variant_calc/paycheck_fed_withholding_provisional_vs_reconciled
        """
        set_clock("2025-12-15T00:00:00.000Z")
        seed_federal_and_california_2025()
        emp, _ = setup_employee_with_filed_w4()
        run = create_draft_paycheck_run(
            pay_period_start="2025-12-15T00:00:00.000Z",
            pay_period_end="2025-12-31T23:59:59.999Z",
            pay_date="2025-12-31T00:00:00.000Z",
        )
        pay = attach_regular_paycheck(run["id"], emp["id"])

        assert pay["fed_withheld_cents"] == 16357, \
            f"provisional fed_withheld should be 16357 on $2000 SINGLE biweekly, got {pay['fed_withheld_cents']}"
        assert pay["gross_wages_cents"] == 200000
        assert pay["status"] == "PENDING"


# =========================================================================
# Queue (A) Difficulty — rule 2 combinatorial_formula
# =========================================================================

class TestSupplementalFlatBranch:
    """OVERTIME / DOUBLE / RETRO pay_types take the flat supplemental branch."""

    def test_overtime_uses_federal_supplemental_branch_with_extra_withholding(self, api):
        """PRD §3.4: "For `OVERTIME`, `DOUBLE`, and `RETRO` paychecks the
        percentage-method branch is skipped: the provisional federal withholding
        is the gross wages multiplied by the federal row's
        `supplemental_flat_basis_points` and floor-divided by 10000, plus
        `extra_withholding_cents`, floored at zero."

        Setup: OVERTIME 40h @ $25/hr w/ W-4 extra_withholding_cents=500.
        gross = (4000 × 2500 × 3) // 200 = 150,000
        fed = 150000 × 2200 // 10000 + 500 = 33,000 + 500 = 33,500

        Design: Difficulty/combinatorial_formula/federal_overtime_supplemental_branch_mode_a
        """
        set_clock("2025-11-01T00:00:00.000Z")
        seed_federal_and_california_2025()
        emp = create_employee(work_state_code="CA", residence_state_code="CA")
        create_and_file_w4(emp["id"], extra_withholding_cents=500)
        run = create_draft_paycheck_run(
            pay_period_start="2025-11-01T00:00:00.000Z",
            pay_period_end="2025-11-15T23:59:59.999Z",
            pay_date="2025-11-15T00:00:00.000Z",
        )
        pay = attach_overtime_paycheck(
            run["id"], emp["id"],
            overtime_hours_e2=4000, hourly_rate_cents=2500,
        )

        assert pay["gross_wages_cents"] == 150000, \
            f"OVERTIME 40h @ $25/hr should be 150000c gross, got {pay['gross_wages_cents']}"
        assert pay["fed_withheld_cents"] == 33500, \
            f"OVERTIME flat supp + extra=500 should be 33500, got {pay['fed_withheld_cents']}"
        assert pay["status"] == "PENDING"


# =========================================================================
# Queue (A) Difficulty — rule 6 boundary_precision_check (Medicare YTD)
# =========================================================================

class TestAdditionalMedicareBoundary:
    """The $200,000 YTD Medicare threshold is strictly ABOVE per PRD §3.4."""

    def test_at_threshold_contributes_zero_additional_medicare(self, api):
        """PRD §3.4: "The boundary semantics are strict: a paycheck that pushes
        the year-to-date from \\$199,999.99 to exactly \\$200,000.00 contributes
        zero cents (the threshold dollar itself is not yet above)"

        Setup: ytd_medicare = 19,800,000c seeded; new $2000 paycheck pushes YTD
        to exactly 20,000,000c. addl_medicare_cents must be 0.

        Design: Difficulty/boundary_precision_check/addl_medicare_threshold_exact_no_charge
        """
        set_clock("2025-11-01T00:00:00.000Z")
        seed_federal_and_california_2025()
        emp = create_employee()
        seed_employee_ytd(emp["id"], ytd_medicare_wages_cents=19_800_000)
        create_and_file_w4(emp["id"])
        run = create_draft_paycheck_run()
        pay = attach_regular_paycheck(run["id"], emp["id"])

        assert pay["addl_medicare_cents"] == 0, \
            f"YTD pushed to exactly $200k must contribute 0c addl Medicare, got {pay['addl_medicare_cents']}"
        assert pay["medicare_withheld_cents"] == 2900, \
            f"base Medicare on $2000 gross must be 2900c, got {pay['medicare_withheld_cents']}"
        assert pay["gross_wages_cents"] == 200000


# =========================================================================
# Queue (B) Corner — section calculations
# =========================================================================

class TestFicaSocialSecurityCap:
    """SS_WAGE_BASE_CENTS cap per PRD §3.4."""

    def test_at_cap_yields_zero_ss_withheld(self, api):
        """PRD §3.4: "When the employee's year-to-date Social Security wages
        have already reached the wage base, the remaining capacity is zero and
        `ss_withheld_cents` is zero."

        Setup: ytd_ss=16,860,000 (at cap); a new $2000 paycheck yields ss=0.

        Design: Corner/calculations/ss_wage_base_cap_hit
        """
        set_clock("2025-11-01T00:00:00.000Z")
        seed_federal_and_california_2025()
        emp = create_employee()
        seed_employee_ytd(emp["id"], ytd_ss_wages_cents=16_860_000)
        create_and_file_w4(emp["id"])
        run = create_draft_paycheck_run()
        pay = attach_regular_paycheck(run["id"], emp["id"])

        assert pay["ss_withheld_cents"] == 0, \
            f"at SS wage base cap, ss_withheld must be 0, got {pay['ss_withheld_cents']}"
        assert pay["gross_wages_cents"] == 200000

    def test_partial_cross_through_ss_wage_base(self, api):
        """PRD §3.4: "The taxable portion of this paycheck is the smaller of
        `gross_wages_cents` and the remaining capacity; `ss_withheld_cents` is
        that taxable portion multiplied by `SS_RATE_BASIS_POINTS = 620` (6.20%)
        and floor-divided by 10000."

        Setup: ytd_ss=16,800,000; remaining capacity = 60,000; gross=200,000;
        taxable=min(200000, 60000)=60000; ss = 60000 × 620 // 10000 = 3,720.

        Design: Corner/calculations/ss_wage_base_partial_cross
        """
        set_clock("2025-11-01T00:00:00.000Z")
        seed_federal_and_california_2025()
        emp = create_employee()
        seed_employee_ytd(emp["id"], ytd_ss_wages_cents=16_800_000)
        create_and_file_w4(emp["id"])
        run = create_draft_paycheck_run()
        pay = attach_regular_paycheck(run["id"], emp["id"])

        assert pay["ss_withheld_cents"] == 3720, \
            f"partial-cross ss_withheld should be 3720, got {pay['ss_withheld_cents']}"


class TestStateAndLocalWithholding:
    """State/local withholding per PRD §3.4 and §3.2 (TX/WA have no income tax)."""

    def test_texas_employee_yields_zero_state_withholding(self, api):
        """PRD §3.2: "`STATE:TX` and `STATE:WA` are deliberately seeded with an
        empty brackets list — these states levy no income tax, and state
        withholding evaluates to zero for any employee whose `work_state_code`
        is one of them."

        Design: Corner/calculations/state_tx_no_income_tax
        """
        set_clock("2025-11-01T00:00:00.000Z")
        seed_federal_tax_table_2025_single()
        emp = create_employee(work_state_code="TX", residence_state_code="TX")
        create_and_file_w4(emp["id"])
        run = create_draft_paycheck_run()
        pay = attach_regular_paycheck(run["id"], emp["id"])

        assert pay["state_withheld_cents"] == 0, \
            f"TX employee must have 0 state withholding, got {pay['state_withheld_cents']}"

    def test_nyc_local_withholding_applied(self, api):
        """PRD §3.4: "The system makes two passes through the rate-table for
        each paycheck: one for `STATE:<work_state_code>` and one for
        `LOCAL:<locality_code>`."
        PRD §3.4: "for a `REGULAR` paycheck, the per-pay tax is the
        bracket-summed tax over `gross_wages_cents`"

        NY brackets 400bp lowest, NYC 300bp single bracket → on $2000 gross:
        state = 200000 × 400 // 10000 = 8000
        local = 200000 × 300 // 10000 = 6000

        Design: Corner/calculations/nyc_local_withholding_applied
        """
        set_clock("2025-11-01T00:00:00.000Z")
        seed_federal_tax_table_2025_single()
        seed_ny_tax_tables_2025()
        emp = create_employee(
            work_state_code="NY", residence_state_code="NY", locality_code="NYC",
        )
        create_and_file_w4(emp["id"])
        run = create_draft_paycheck_run()
        pay = attach_regular_paycheck(run["id"], emp["id"])

        assert pay["state_withheld_cents"] == 8000
        assert pay["local_withheld_cents"] == 6000


class TestGrossWagesByPayType:
    """gross_wages_calc has four branches by pay_type per PRD §3.4."""

    def test_double_pay_type_uses_2x_multiplier(self, api):
        """PRD §3.4: "For a `DOUBLE` paycheck, the multiplier is two: gross is
        `double_hours_e2` multiplied by `hourly_rate_cents`, multiplied by 2,
        then floor-divided by 100."

        Setup: DOUBLE 20.00h @ $25/hr → (2000 × 2500 × 2) // 100 = 100,000.

        Design: Corner/calculations/double_pay_type_gross_2x_multiplier
        """
        set_clock("2025-11-01T00:00:00.000Z")
        seed_federal_and_california_2025()
        emp, _ = setup_employee_with_filed_w4()
        run = create_draft_paycheck_run()
        pay = attach_double_paycheck(
            run["id"], emp["id"],
            double_hours_e2=2000, hourly_rate_cents=2500,
        )
        assert pay["gross_wages_cents"] == 100000, \
            f"DOUBLE gross should be 100000, got {pay['gross_wages_cents']}"

    def test_retro_pay_type_uses_flat_amount(self, api):
        """PRD §3.4: "For a `RETRO` paycheck, gross is simply
        `retro_amount_cents`."

        Setup: RETRO retro_amount_cents=150000 → gross=150000 (ignores hours/rate).

        Design: Corner/calculations/retro_pay_flat_amount
        """
        set_clock("2025-11-01T00:00:00.000Z")
        seed_federal_and_california_2025()
        emp, _ = setup_employee_with_filed_w4()
        run = create_draft_paycheck_run()
        pay = attach_retro_paycheck(run["id"], emp["id"], retro_amount_cents=150000)
        assert pay["gross_wages_cents"] == 150000, \
            f"RETRO gross should equal retro_amount_cents (150000), got {pay['gross_wages_cents']}"


class TestAdditionalMedicareAboveThresholdPartial:
    """Partial cross of $200k YTD Medicare threshold per PRD §3.4."""

    def test_partial_cross_yields_proportional_addl_medicare(self, api):
        """PRD §3.4: "The taxable portion above the threshold is computed as
        the larger of zero and the new YTD minus the threshold, minus the
        larger of zero and the prior YTD minus the threshold. `addl_medicare_cents`
        is then that taxable portion multiplied by the additional-Medicare rate
        and floor-divided by 10000."

        Setup: ytd_medicare=19,900,000; gross=200,000; portion above = 100000;
        addl = 100000 × 90 // 10000 = 900.

        Design: Corner/calculations/addl_medicare_above_threshold_partial
        """
        set_clock("2025-11-01T00:00:00.000Z")
        seed_federal_and_california_2025()
        emp = create_employee()
        seed_employee_ytd(emp["id"], ytd_medicare_wages_cents=19_900_000)
        create_and_file_w4(emp["id"])
        run = create_draft_paycheck_run()
        pay = attach_regular_paycheck(run["id"], emp["id"])

        assert pay["addl_medicare_cents"] == 900, \
            f"partial-cross addl Medicare should be 900, got {pay['addl_medicare_cents']}"
