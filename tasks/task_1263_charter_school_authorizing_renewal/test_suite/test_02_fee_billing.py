"""Authorizer fee billing: variants, rounding order, band keying, ledger (PRD §3.8)."""
import pytest

from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_open_school, create_fee_invoice, finalize_invoice,
    create_finalized_invoice, assert_invoice_ledger_invariant,
    make_staff_headers, make_board_headers, make_school_operator_headers,
)

STAFF = make_staff_headers("staff_1")


class TestFeeInvoiceEstimatedVsFinalVariant:
    def test_estimated_variant_bills_from_estimated_enrollment(self, api):
        """PRD §3.8: "The invoice is born in `ESTIMATED` status with
        `billed_variant` `ESTIMATED`, `audited_enrollment` still null, and
        `paid_cents` and `waived_cents` both zero."
        PRD §3.8: "the monthly charge is `total_funding_cents` multiplied by the
        `fee_rate` and divided by twelve, rounded half-up to a whole cent, and
        `billed_amount_cents` is twelve times that rounded monthly figure."

        Design: Difficulty/dual_variant_calc/fee_invoice_estimated_vs_final_variant
        """
        ctx = create_open_school(school_name="DV Fee Academy", applicant_id="applicant_dv2")
        invoice = create_fee_invoice(ctx["school"]["id"], fiscal_year=2026,
                                     estimated_enrollment=400,
                                     base_per_pupil_cents=800000,
                                     qualifying_supplemental_pupils=100)
        # adm 400 -> base 320,000,000 (MID, 0.08) -> supp 6,400,000 -> total
        # 326,400,000; rate 0.020; monthly 544,000 -> billed 6,528,000
        assert invoice["billed_variant"] == "ESTIMATED"
        assert invoice["status"] == "ESTIMATED"
        assert invoice["audited_enrollment"] is None
        assert invoice["paid_cents"] == 0 and invoice["waived_cents"] == 0
        assert invoice["base_funding_cents"] == 320_000_000
        assert invoice["supplemental_cents"] == 6_400_000
        assert invoice["total_funding_cents"] == 326_400_000
        assert invoice["fee_rate"] == pytest.approx(0.020, abs=1e-9)
        assert invoice["billed_amount_cents"] == 6_528_000

    def test_final_variant_recomputed_at_finalize(self, api):
        """PRD §3.8: "finalization moves it `ESTIMATED` → `FINALIZED`, flips
        `billed_variant` to `FINAL`, and recomputes every computed field under
        the `FINAL` variant — so identical inputs produce a different billed
        amount whenever the audited and estimated enrollments differ."

        Design: Difficulty/dual_variant_calc/fee_invoice_estimated_vs_final_variant
        """
        ctx = create_open_school(school_name="DV Fee Academy", applicant_id="applicant_dv2")
        invoice = create_fee_invoice(ctx["school"]["id"], fiscal_year=2026,
                                     estimated_enrollment=400,
                                     base_per_pupil_cents=800000,
                                     qualifying_supplemental_pupils=100)
        finalized = finalize_invoice(invoice["id"], audited_enrollment=500)
        # adm 500 -> base 400,000,000 (MID) -> supp 6,400,000 -> total
        # 406,400,000; monthly round(677,333.33) = 677,333 -> billed 8,127,996
        assert finalized["billed_variant"] == "FINAL"
        assert finalized["status"] == "FINALIZED"
        assert finalized["audited_enrollment"] == 500
        assert finalized["billed_amount_cents"] == 8_127_996
        assert finalized["billed_amount_cents"] != invoice["billed_amount_cents"]


class TestFeeMonthlyRoundingOrder:
    def test_billed_amount_uses_per_month_rounding(self, api):
        """PRD §3.8: "Rounding order is pinned per month rather than per year:
        the monthly charge is `total_funding_cents` multiplied by the `fee_rate`
        and divided by twelve, rounded half-up to a whole cent, and
        `billed_amount_cents` is twelve times that rounded monthly figure."
        PRD §3.8: "Rounding the annual product once instead would yield a
        different cent value whenever the monthly division is fractional; the
        per-month order is the specified behavior."

        Design: Difficulty/combinatorial_formula/fee_monthly_rounding_order
        """
        ctx = create_open_school(school_name="CF Rounding Academy", applicant_id="applicant_cf2")
        invoice = create_fee_invoice(ctx["school"]["id"], fiscal_year=2027,
                                     estimated_enrollment=500,
                                     base_per_pupil_cents=800000,
                                     qualifying_supplemental_pupils=100)
        # total 406,400,000 at 0.020: per-month round(677,333.33) = 677,333
        # -> 12 * 677,333 = 8,127,996; a round-of-annual would give 8,128,000
        assert invoice["billed_amount_cents"] == 8_127_996
        assert invoice["billed_amount_cents"] != 8_128_000

    def test_fee_rate_and_total_funding_feed_the_monthly_rounding(self, api):
        """PRD §3.8: "The fee itself is tiered on enrollment: an invoice whose
        active enrollment is at most 300 pupils bills at a `fee_rate` of 0.025,
        from 301 through 800 pupils at 0.020, and at 801 or more pupils at
        0.015."

        Design: Difficulty/combinatorial_formula/fee_monthly_rounding_order
        """
        ctx = create_open_school(school_name="CF Rounding Academy", applicant_id="applicant_cf2")
        invoice = create_fee_invoice(ctx["school"]["id"], fiscal_year=2027,
                                     estimated_enrollment=500,
                                     base_per_pupil_cents=800000,
                                     qualifying_supplemental_pupils=100)
        assert invoice["total_funding_cents"] == 406_400_000
        assert invoice["fee_rate"] == pytest.approx(0.020, abs=1e-9)
        assert_invoice_ledger_invariant(invoice)


class TestSupplementalBandKeyedOnBaseOnly:
    def test_supplemental_uses_small_band_rate_from_base(self, api):
        """PRD §3.8: "Second, that base alone selects the supplemental band: a
        base under 200,000,000 cents — two million dollars — is the small band
        with a supplemental rate of 0.12; a base from 200,000,000 cents up to
        and including 600,000,000 cents — two to six million dollars — is the
        mid band at 0.08; and a base above 600,000,000 cents is the large band
        at 0.05."

        Design: Difficulty/combinatorial_formula/supplemental_band_keyed_on_base_only
        """
        ctx = create_open_school(school_name="CF Circular Academy", applicant_id="applicant_cf3")
        invoice = create_fee_invoice(ctx["school"]["id"], fiscal_year=2028,
                                     estimated_enrollment=250,
                                     base_per_pupil_cents=796000,
                                     qualifying_supplemental_pupils=40)
        # base = 250 * 796,000 = 199,000,000 -> SMALL band (0.12) keyed on base
        # supp = round_half_up(40 * 796,000 * 0.12) = 3,820,800
        assert invoice["base_funding_cents"] == 199_000_000
        assert invoice["supplemental_cents"] == 3_820_800

    def test_total_crossing_mid_cap_proves_band_keyed_on_base(self, api):
        """PRD §3.8: "The funding base is computed in a pinned order, because
        the supplemental band is keyed on the base alone and never on the
        total."

        Design: Difficulty/combinatorial_formula/supplemental_band_keyed_on_base_only
        """
        ctx = create_open_school(school_name="CF Circular Academy", applicant_id="applicant_cf3")
        invoice = create_fee_invoice(ctx["school"]["id"], fiscal_year=2028,
                                     estimated_enrollment=250,
                                     base_per_pupil_cents=796000,
                                     qualifying_supplemental_pupils=40)
        # total 202,820,800 is past the small cap; had the band been keyed on
        # the total the rate would have been 0.08 and supp 2,547,200 instead.
        assert invoice["total_funding_cents"] == 202_820_800
        assert invoice["total_funding_cents"] >= 200_000_000
        assert invoice["supplemental_cents"] == 3_820_800


class TestFeeLedgerConservation:
    def test_pay_settles_in_full_and_preserves_ledger(self, api):
        """PRD §3.8: "payment settles in full only: `paid_cents` becomes exactly
        `billed_amount_cents` and the invoice moves to `PAID`."
        PRD §3.8: "`paid_cents` plus `waived_cents` plus the outstanding
        remainder always equals `billed_amount_cents`, and the outstanding
        remainder never goes negative."

        Design: Difficulty/compensating_invariant/fee_ledger_conservation_pay_and_waive
        """
        ctx = create_open_school(school_name="CI Fee Academy", applicant_id="applicant_ci2")
        invoice = create_finalized_invoice(ctx["school"]["id"], fiscal_year=2026,
                                           estimated_enrollment=400,
                                           base_per_pupil_cents=800000,
                                           qualifying_supplemental_pupils=100,
                                           audited_enrollment=400)
        assert invoice["billed_amount_cents"] == 6_528_000
        paid = validate_success(
            api.pay_fee_invoice(invoice["id"],
                                make_school_operator_headers(ctx["school"]["id"])), 200)
        assert paid["status"] == "PAID"
        assert paid["paid_cents"] == 6_528_000 == paid["billed_amount_cents"]
        assert paid["waived_cents"] == 0
        assert_invoice_ledger_invariant(paid)

    def test_waive_zero_paid_preserves_ledger(self, api):
        """PRD §3.8: "A `BoardMember` may instead waive a `FINALIZED` invoice,
        but only while nothing has been paid — a non-zero `paid_cents` is
        rejected with `ERR_INVOICE_INVALID_STATE` — moving it to `WAIVED` with
        `waived_cents` set to the full `billed_amount_cents`."

        Design: Difficulty/compensating_invariant/fee_ledger_conservation_pay_and_waive
        """
        ctx = create_open_school(school_name="CI Fee Academy", applicant_id="applicant_ci2")
        invoice = create_finalized_invoice(ctx["school"]["id"], fiscal_year=2027,
                                           estimated_enrollment=400,
                                           base_per_pupil_cents=800000,
                                           qualifying_supplemental_pupils=100,
                                           audited_enrollment=400)
        billed_before = invoice["billed_amount_cents"]
        waived = validate_success(
            api.waive_fee_invoice(invoice["id"], make_board_headers("board_1")), 200)
        assert waived["status"] == "WAIVED"
        assert waived["waived_cents"] == 6_528_000 == billed_before
        assert waived["paid_cents"] == 0
        assert waived["billed_amount_cents"] == billed_before
        assert_invoice_ledger_invariant(waived)


class TestInvoiceStateGuards:
    def test_pay_before_finalize_rejected(self, api):
        """PRD §3.8: "The owning `SchoolOperator` pays a `FINALIZED` invoice —
        any other status, `ERR_INVOICE_INVALID_STATE`; another school's
        operator, `ERR_RESOURCE_OWNERSHIP_MISMATCH` — and payment settles in
        full only: `paid_cents` becomes exactly `billed_amount_cents` and the
        invoice moves to `PAID`."

        Design: Corner/state_machines/sm_invoice_pay_before_finalize_rejected
        """
        ctx = create_open_school(school_name="SM Invoice Academy", applicant_id="applicant_s13")
        invoice = create_fee_invoice(ctx["school"]["id"], fiscal_year=2026,
                                     estimated_enrollment=400,
                                     base_per_pupil_cents=800000,
                                     qualifying_supplemental_pupils=100)
        res = api.pay_fee_invoice(invoice["id"],
                                  make_school_operator_headers(ctx["school"]["id"]))
        validate_error(res, ApiErrorId.ERR_INVOICE_INVALID_STATE, expected_status=409)
        invoices = validate_success(
            api.list_fee_invoices(ctx["school"]["id"], STAFF), 200)
        current = next(i for i in invoices if i["id"] == invoice["id"])
        assert current["status"] == "ESTIMATED"
        assert current["paid_cents"] == 0
