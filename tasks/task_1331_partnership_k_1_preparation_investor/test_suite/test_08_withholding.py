"""Foreign partner withholding: CURRENT_ACTUAL vs SAFE_HARBOR variants, the
Q4 floor remainder, remittance guard, penalty computation, and accrual
uniqueness."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS, CANONICAL_FEE_FUND, CANONICAL_TOTALS,
    create_fund, create_partner, create_tax_year, close_books,
    post_capital_event, create_and_lock_final_run, accrue_withholding,
    create_withholding_accrual_payload, set_clock, setup_k1_generated,
    assert_withholding_record,
)

ADMIN = TEST_USERS["fund_tax_admin_headers"]
PREPARER = TEST_USERS["tax_preparer_headers"]
REVIEWER = TEST_USERS["tax_reviewer_headers"]

FOREIGN_LP = {
    "key": "lp2", "legal_name": "LP2", "partner_type": "FOREIGN_INDIVIDUAL",
    "partner_class": "LIMITED", "residency_state": "XX",
    "ownership_pct_bps": 3000, "capital_commitment_cents": 30000000,
    "admission_date": "2024-01-01",
}


def _single_foreign_partner_locked(api, gross=9779333):
    """One FOREIGN_INDIVIDUAL partner (10000bps) and a LOCKED FINAL run; the
    partner is allocated the full net ordinary income."""
    fund = create_fund()
    partner = create_partner(
        fund["id"], legal_name="FR", partner_type="FOREIGN_INDIVIDUAL",
        residency_state="XX", ownership_pct_bps=10000,
    )
    ty = create_tax_year(fund["id"], year=2025, gross_ordinary_income_cents=gross)
    close_books(ty["id"])
    create_and_lock_final_run(ty["id"])
    return fund, partner, ty


class TestSafeHarborVsCurrentActual:
    def _scenario(self, api):
        """Two-year setup. 2024: net ordinary 3500000 (gross 4000000 less the
        discounted 500000 fee), LOCKED FINAL run, four CURRENT_ACTUAL quarters
        for LP2 at 97125 each. 2025: net ordinary 9500000, gain 20000000,
        interest 5000000, with 2025-01-01 contributions establishing beginning
        capital; LOCKED FINAL run allocates LP2 a total of 9779333."""
        from test_helpers import setup_fund_with_partners
        fund, partners = setup_fund_with_partners(
            partner_specs=[
                {
                    "key": "gp1", "legal_name": "GP1", "partner_type": "US_ENTITY",
                    "partner_class": "GENERAL", "residency_state": "DE",
                    "ownership_pct_bps": 1000, "capital_commitment_cents": 10000000,
                    "admission_date": "2024-01-01",
                },
                {
                    "key": "lp1", "legal_name": "LP1", "partner_type": "US_INDIVIDUAL",
                    "partner_class": "LIMITED", "residency_state": "CA",
                    "ownership_pct_bps": 6000, "capital_commitment_cents": 60000000,
                    "admission_date": "2024-01-01",
                },
                dict(FOREIGN_LP),
            ],
            fund_overrides=CANONICAL_FEE_FUND,
        )
        ty24 = create_tax_year(
            fund["id"], year=2024, gross_ordinary_income_cents=4000000,
            capital_gain_cents=0, interest_income_cents=0,
        )
        close_books(ty24["id"])
        create_and_lock_final_run(ty24["id"])
        for quarter in (1, 2, 3, 4):
            accrue_withholding(ty24["id"], quarter, "CURRENT_ACTUAL")
        ty25 = create_tax_year(fund["id"], year=2025, **CANONICAL_TOTALS)
        # 2025-01-01 contributions set beginning capital for the preferred tier
        post_capital_event(partners["lp1"]["id"], ty25["id"], "CONTRIBUTION", 60000000, "2025-01-01")
        post_capital_event(partners["lp2"]["id"], ty25["id"], "CONTRIBUTION", 30000000, "2025-01-01")
        close_books(ty25["id"])
        create_and_lock_final_run(ty25["id"])
        return ty25

    def test_current_actual_derives_from_locked_final_run(self, api):
        """PRD §3.7: "Under `CURRENT_ACTUAL`, the partner’s annual effectively
        connected taxable income is the sum of that partner’s allocation line
        amounts across all categories in the year’s `LOCKED` `FINAL` run, and
        this annual figure is stored in `annual_ecti_cents`."
        PRD §3.7: "The quarterly base for each of the first three quarters is
        the annual amount divided by four and rounded down to a whole cent,
        while the fourth quarter’s base is the annual amount minus three times
        that floored quarter, so any division remainder lands in the fourth
        quarter. Each quarter’s `accrued_cents` is its base multiplied by
        `rate_bps` and divided by ten thousand, rounded half-up."

        Design: Difficulty/dual_variant_calc/withholding_safe_harbor_vs_current_actual
        """
        ty25 = self._scenario(api)
        resp = api.create_withholding_accruals(
            create_withholding_accrual_payload(ty25["id"], quarter=1, method="CURRENT_ACTUAL"),
            PREPARER,
        )
        records = validate_success(resp, 201)
        assert len(records) == 1
        record = records[0]
        assert_withholding_record(record)
        # annual ECTI 9779333; Q1 base floor(9779333/4) = 2444833; x 3700bps
        assert record["annual_ecti_cents"] == 9779333
        assert record["accrued_cents"] == 904588, (
            f"Q1 CURRENT_ACTUAL accrual: {record['accrued_cents']}"
        )
        assert record["rate_bps"] == 3700

    def test_safe_harbor_flat_quarters_from_prior_year(self, api):
        """PRD §3.7: "Under `SAFE_HARBOR`, the basis is the prior year: the
        system sums `accrued_cents` over the partner’s withholding records
        whose tax year is the immediately preceding year, in any status, taking
        zero when no such records exist, and stores that prior-year total in
        `annual_ecti_cents`."
        PRD §3.7: "Each quarter’s `accrued_cents` is then the prior-year total
        multiplied by one hundred and ten percent and divided by four, rounded
        half-up to integer cents — identical for all four quarters."
        PRD §3.7: "The two methods diverge whenever the current year’s
        allocation differs from one hundred and ten percent of last year’s
        withholding."

        Design: Difficulty/dual_variant_calc/withholding_safe_harbor_vs_current_actual
        """
        ty25 = self._scenario(api)
        ca_records = validate_success(
            api.create_withholding_accruals(
                create_withholding_accrual_payload(ty25["id"], quarter=1, method="CURRENT_ACTUAL"),
                PREPARER,
            ),
            201,
        )
        sh_records = validate_success(
            api.create_withholding_accruals(
                create_withholding_accrual_payload(ty25["id"], quarter=2, method="SAFE_HARBOR"),
                PREPARER,
            ),
            201,
        )
        sh = sh_records[0]
        # prior-year total 4 x 97125 = 388500; x 110% / 4 = 106838
        assert sh["annual_ecti_cents"] == 388500
        assert sh["accrued_cents"] == 106838, (
            f"Q2 SAFE_HARBOR accrual: {sh['accrued_cents']}"
        )
        assert ca_records[0]["accrued_cents"] != sh["accrued_cents"], (
            "the two variants must diverge for the same partner and tax year"
        )


class TestQuarterFourRemainder:
    def test_withholding_q4_holds_floor_remainder(self, api):
        """PRD §3.7: "The quarterly base for each of the first three quarters
        is the annual amount divided by four and rounded down to a whole cent,
        while the fourth quarter’s base is the annual amount minus three times
        that floored quarter, so any division remainder lands in the fourth
        quarter."
        PRD §3.8: "Two cascades follow creation: for every foreign partner
        receiving a package, a fourth-quarter `CURRENT_ACTUAL` withholding
        record is accrued, and every `DRAFT` composite filing of the tax year
        recomputes its totals now that per-partner income is snapshotted."
        PRD §3.7: "Quarterly due dates fall on April 15 for the first quarter,
        June 15 for the second, September 15 for the third, and December 15 for
        the fourth, all within the tax year itself."

        Design: Corner/calculations/withholding_q4_holds_floor_remainder
        """
        scenario = setup_k1_generated(
            fund_overrides=CANONICAL_FEE_FUND,
            tax_year_overrides=dict(CANONICAL_TOTALS),
            contributions=[
                ("gp1", 10000000, "2025-01-01"),
                ("lp1", 60000000, "2025-01-01"),
                ("lp2", 30000000, "2025-01-01"),
            ],
        )
        ty = scenario["tax_year"]
        lp2 = scenario["partners"]["lp2"]
        data, meta = validate_paginated(
            api.list_withholding_records(PREPARER, params={"tax_year_id": ty["id"], "quarter": 4})
        )
        assert meta["total_count"] == 1, f"exactly one Q4 record: {meta['total_count']}"
        record = data[0]
        assert_withholding_record(record)
        assert record["partner_id"] == lp2["id"]
        assert record["method"] == "CURRENT_ACTUAL"
        # ECTI_4 = 9779333 - 3 x 2444833 = 2444834; x 3700bps -> 904589
        assert record["accrued_cents"] == 904589, (
            f"Q4 holds the floor remainder: {record['accrued_cents']}"
        )
        assert record["rate_bps"] == 3700
        assert record["due_date"] == "2025-12-15"


class TestRemitAndPenalty:
    def test_remit_exceeding_accrued_rejected(self, api):
        """PRD §3.7: "The cumulative `remitted_cents` plus the new amount must
        not exceed `accrued_cents`, else `ERR_REMIT_EXCEEDS_ACCRUED`. A partial
        remittance moves the record from `ACCRUED` to `PARTIALLY_REMITTED`, and
        further partial remittances keep it there while the cumulative total
        remains below the accrued amount; a remittance that completes the
        accrued amount exactly moves the record to `REMITTED` with
        `remitted_cents` equal to `accrued_cents`."

        Design: Corner/validations/remit_exceeding_accrued_rejected
        """
        fund, partner, ty = _single_foreign_partner_locked(api)
        record = accrue_withholding(ty["id"], 1, "CURRENT_ACTUAL")[0]
        assert record["accrued_cents"] == 904588
        resp_over = api.remit_withholding(record["id"], {"amount_cents": 904589}, PREPARER)
        validate_error(resp_over, ApiErrorId.ERR_REMIT_EXCEEDS_ACCRUED)
        resp_exact = api.remit_withholding(record["id"], {"amount_cents": 904588}, PREPARER)
        remitted = validate_success(resp_exact, 200)
        assert remitted["status"] == "REMITTED"
        assert remitted["remitted_cents"] == 904588

    def test_withholding_penalty_months_and_cap(self, api):
        """PRD §3.7: "The underpayment is `accrued_cents` minus
        `remitted_cents`, floored at zero. The months late are the complete
        calendar months between the `due_date` and the current clock date:
        twelve times the difference in calendar years plus the difference in
        calendar months, reduced by one when the clock’s day-of-month is
        earlier than the due date’s day-of-month, and never below zero —
        remitting or reconciling on or before the due date yields zero months
        late."
        PRD §3.7: "The effective months are the months late capped at five, and
        the penalty is the underpayment multiplied by five hundred basis points
        per month and by the effective months, divided by ten thousand, and
        rounded half-up to integer cents."

        Design: Corner/calculations/withholding_penalty_months_and_cap
        """
        fund, partner, ty = _single_foreign_partner_locked(api)
        record = accrue_withholding(ty["id"], 1, "CURRENT_ACTUAL")[0]
        set_clock("2025-05-01T00:00:00Z")
        validate_success(api.remit_withholding(record["id"], {"amount_cents": 500000}, PREPARER), 200)
        set_clock("2025-07-15T00:00:00Z")
        resp = api.reconcile_withholding(record["id"], REVIEWER)
        reconciled = validate_success(resp, 200)
        assert reconciled["status"] == "RECONCILED"
        # due 2025-04-15, clock 2025-07-15 -> 3 complete months;
        # underpayment 404588 x 500bps x 3 -> 60688
        assert reconciled["penalty_cents"] == 60688, (
            f"penalty: {reconciled['penalty_cents']}"
        )
        assert reconciled["remitted_cents"] == 500000, "reconcile must not move remitted_cents"


class TestAccrualValidation:
    def test_duplicate_withholding_accrual_rejected(self, api):
        """PRD §3.7: "Only one record may exist per partner, tax year, and
        quarter — a second accrual for an existing triple is rejected with
        `ERR_DUPLICATE_WITHHOLDING_ACCRUAL` — and if the tax year has no
        foreign `ACTIVE` partners at all, the bulk call fails with
        `ERR_NO_FOREIGN_PARTNERS`."

        Design: Corner/validations/duplicate_withholding_accrual_rejected
        """
        fund, partner, ty = _single_foreign_partner_locked(api, gross=1000000)
        accrue_withholding(ty["id"], 1, "CURRENT_ACTUAL")
        resp = api.create_withholding_accruals(
            create_withholding_accrual_payload(ty["id"], quarter=1, method="SAFE_HARBOR"),
            PREPARER,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_WITHHOLDING_ACCRUAL)

    def test_accrual_without_foreign_partners_rejected(self, api):
        """PRD §3.7: "Only one record may exist per partner, tax year, and
        quarter — a second accrual for an existing triple is rejected with
        `ERR_DUPLICATE_WITHHOLDING_ACCRUAL` — and if the tax year has no
        foreign `ACTIVE` partners at all, the bulk call fails with
        `ERR_NO_FOREIGN_PARTNERS`."

        Design: Corner/validations/accrual_without_foreign_partners_rejected
        """
        fund = create_fund()
        create_partner(fund["id"], legal_name="P", partner_type="US_INDIVIDUAL")
        ty = create_tax_year(fund["id"], year=2025, gross_ordinary_income_cents=1000000)
        close_books(ty["id"])
        create_and_lock_final_run(ty["id"])
        resp = api.create_withholding_accruals(
            create_withholding_accrual_payload(ty["id"], quarter=1, method="CURRENT_ACTUAL"),
            PREPARER,
        )
        validate_error(resp, ApiErrorId.ERR_NO_FOREIGN_PARTNERS)
