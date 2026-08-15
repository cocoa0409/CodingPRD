"""Tax installment monitoring: sweep transitions, penalty accrual, mark-paid."""
from test_helpers import (
    EA1,
    create_active_bare_loan,
    create_tax_record,
    get_success_data,
    mark_tax_paid_payload,
    release_disbursement,
    schedule_disbursement,
    set_clock,
    setup_active_account,
    validate_success,
)


class TestPenaltyVariants:
    def _setup_two_records(self, api):
        """Active bare loan + two identical 300000 tax records due 2026-08-01
        (grace 0, 150 bps): seq 1 SIMPLE, seq 2 COMPOUND."""
        loan = create_active_bare_loan(loan_number="LN-PEN-1",
                                       borrower_name="Penny Lope")
        r1 = create_tax_record(loan["id"], installment_sequence=1,
                               penalty_method="SIMPLE")
        r2 = create_tax_record(loan["id"], installment_sequence=2,
                               penalty_method="COMPOUND")
        return loan, r1, r2

    def _sweep_to_november(self):
        # Two nudges: under any sweep-pass reading the records are DELINQUENT
        # after the first and PENALTY_ACCRUING after the second; the
        # recomputed penalty (3 whole 30/360 months) is the same at both.
        set_clock("2026-11-15T00:00:00Z")
        set_clock("2026-11-16T00:00:00Z")

    def test_simple_penalty_accrues_single_multiplication(self, api):
        """PRD: "Under `SIMPLE`, the accrued penalty is `amount_due_cents`
        multiplied by the monthly rate (basis points over 10,000) multiplied by
        the whole months elapsed, rounded half-up once."

        Design: Difficulty/dual_variant_calc/tax_penalty_simple_vs_compound_accrual
        """
        loan, r1, _r2 = self._setup_two_records(api)
        self._sweep_to_november()

        rec = validate_success(api.get_tax_record(r1["id"], EA1), 200)
        assert rec["status"] == "PENALTY_ACCRUING"
        # delinquent_since 2026-08-02; 103 days of 30/360 -> 3 whole months;
        # 300000 * 0.015 * 3 = 13500.
        assert rec["accrued_penalty_cents"] == 13_500

    def test_compound_penalty_rounds_inside_the_loop(self, api):
        """PRD: "Under `COMPOUND`, the balance starts at `amount_due_cents` and
        is iterated once per whole month elapsed, each iteration adding the
        balance times the monthly rate rounded half-up to whole cents before
        the next iteration begins — per-month rounding inside the loop is
        pinned, and the final penalty is the resulting balance minus
        `amount_due_cents`."
        PRD: "Compounding is strictly more expensive than the simple variant
        once at least two whole months have elapsed."

        Design: Difficulty/dual_variant_calc/tax_penalty_simple_vs_compound_accrual
        """
        loan, r1, r2 = self._setup_two_records(api)
        self._sweep_to_november()

        simple = validate_success(api.get_tax_record(r1["id"], EA1), 200)
        compound = validate_success(api.get_tax_record(r2["id"], EA1), 200)
        assert compound["status"] == "PENALTY_ACCRUING"
        # 300000 -> 304500 -> 309068 -> 313704: penalty 13704.
        assert compound["accrued_penalty_cents"] == 13_704
        assert compound["accrued_penalty_cents"] > simple["accrued_penalty_cents"]


class TestGraceBoundaryAndFirstMonth:
    def test_paid_at_grace_boundary_vs_one_month_late(self, api):
        """PRD: "Timing decides the landing state: from `MONITORING` or
        `DUE_SOON`, payment on or before `due_date` plus `grace_period_days`
        lands in `PAID_CURRENT` with the penalty frozen at its current value of
        zero; from `DELINQUENT`, `PENALTY_ACCRUING`, or `REDEMPTION_RISK`,
        payment lands in `PAID_DELINQUENT` with `accrued_penalty_cents`
        recomputed one final time as of today and then frozen permanently."
        PRD: "its `amount_cents` must be at least `amount_due_cents`"

        Design: Corner/calculations/tax_penalty_grace_boundary_and_first_month
        """
        ctx = setup_active_account(loan_number="LN-CAL-6",
                                   borrower_name="Grace Period",
                                   deposits=[(600_000, "2026-08-05")])
        acct_id = ctx["account"]["id"]
        loan_id = ctx["loan"]["id"]
        r1 = create_tax_record(loan_id, parcel_number="P-7", installment_sequence=1,
                               due_date="2026-08-10", grace_period_days=5)
        r2 = create_tax_record(loan_id, parcel_number="P-7", installment_sequence=2,
                               due_date="2026-08-10", grace_period_days=5)
        d1 = schedule_disbursement(acct_id, ctx["line_items"][0]["id"],
                                   ctx["payee"]["id"], amount_cents=300_000,
                                   due_date="2026-08-10",
                                   scheduled_release_date="2026-08-10")
        d2 = schedule_disbursement(acct_id, ctx["line_items"][0]["id"],
                                   ctx["payee"]["id"], amount_cents=300_000,
                                   due_date="2026-08-10",
                                   scheduled_release_date="2026-08-10")
        set_clock("2026-08-15T00:00:00Z")
        release_disbursement(d1["id"])
        release_disbursement(d2["id"])

        # Exactly due_date + grace (2026-08-10 + 5): on-time payment.
        paid1 = validate_success(api.mark_tax_paid(
            r1["id"], mark_tax_paid_payload(d1["id"]), EA1), 200)
        assert paid1["status"] == "PAID_CURRENT"
        assert paid1["accrued_penalty_cents"] == 0
        assert paid1["paid_via_disbursement_id"] == d1["id"]

        # 2026-09-16: delinquent_since is 2026-08-16, so exactly one whole
        # 30/360 month has elapsed -> 300000 * 1.5% = 4500.
        set_clock("2026-09-16T00:00:00Z")
        paid2 = validate_success(api.mark_tax_paid(
            r2["id"], mark_tax_paid_payload(d2["id"]), EA1), 200)
        assert paid2["status"] == "PAID_DELINQUENT"
        assert paid2["accrued_penalty_cents"] == 4_500
        assert paid2["paid_via_disbursement_id"] == d2["id"]


class TestDueSoonDelinquentSweep:
    def test_monitoring_to_due_soon_to_delinquent_boundaries(self, api):
        """PRD: "A record in `MONITORING` becomes `DUE_SOON` when the current
        date falls within the window from 30 days before `due_date` through
        `due_date` plus `grace_period_days`, both ends inclusive. From either
        `MONITORING` or `DUE_SOON`, once the current date passes `due_date`
        plus `grace_period_days`, the record becomes `DELINQUENT` and
        `delinquent_since` is fixed at `due_date` plus `grace_period_days`
        plus one day."

        Design: Corner/cross_cutting_layers/tax_record_due_soon_delinquent_sweep
        """
        loan = create_active_bare_loan(loan_number="LN-SWP-2",
                                       borrower_name="Due Soon")
        rec = create_tax_record(loan["id"], parcel_number="P-9",
                                due_date="2026-09-10", grace_period_days=5)
        assert rec["status"] == "MONITORING"

        set_clock("2026-08-10T00:00:00Z")
        rec = validate_success(api.get_tax_record(rec["id"], EA1), 200)
        assert rec["status"] == "MONITORING", (
            "one day before the 30-day window the record is still MONITORING")

        set_clock("2026-08-11T00:00:00Z")
        rec = validate_success(api.get_tax_record(rec["id"], EA1), 200)
        assert rec["status"] == "DUE_SOON", (
            "exactly 30 days before due_date enters the DUE_SOON window")

        set_clock("2026-09-16T00:00:00Z")
        rec = validate_success(api.get_tax_record(rec["id"], EA1), 200)
        assert rec["status"] == "DELINQUENT", (
            "past due_date + grace_period_days (2026-09-15) the record is DELINQUENT")
        assert rec["delinquent_since"] == "2026-09-16", (
            "delinquent_since = due_date + grace_period_days + 1 day")
