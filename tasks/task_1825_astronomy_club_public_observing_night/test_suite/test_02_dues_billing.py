"""Dues invoicing: proration variants, payment sufficiency, credit ledger."""
from datetime import datetime

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_dues_payment,
    create_member,
    create_tier,
    get_success_data,
    issue_invoice,
    make_member_headers,
    pay_invoice,
    validate_error,
    validate_success,
)

OFFICER = TEST_USERS["club_officer_headers"]


def _instant(iso_text):
    """Parse an ISO 8601 instant regardless of fractional-digit formatting."""
    return datetime.fromisoformat(iso_text.replace("Z", "+00:00"))


class TestDuesProrationVariants:
    def test_proration_midyear_uses_single_final_rounding(self, api):
        """PRD: "For any other day count — the mid-year-join case — the
        charged amount is the tier's `annual_dues_cents` multiplied by the
        day count of the invoice period and divided by 365, with the
        resulting rational rounded half-up to integer cents in a single final
        rounding."
        PRD: "Per-period partial rounding followed by summation is a
        different, forbidden interpretation: the rounding happens after the
        full unrounded rational value has been computed, not on any
        intermediate per-month or per-day slice."

        Design: Difficulty/dual_variant_calc/dues_proration_midyear_vs_full_period
        """
        tier = create_tier(annual_dues_cents=120000)
        member = create_member(tier["id"], full_name="Pat Pro")
        # 2026-08-01 -> 2026-11-01 is 92 days: 120000 * 92 / 365 = 30246.575...
        # A single final round_half_up gives 30247.
        resp = api.create_dues_invoice(
            {"member_id": member["id"],
             "period_start": "2026-08-01T00:00:00Z",
             "period_end": "2026-11-01T00:00:00Z"},
            OFFICER)
        invoice = validate_success(resp, 201)
        assert invoice["amount_cents"] == 30247, (
            "Mid-year proration rounds once at the end: "
            f"expected 30247, got {invoice['amount_cents']}")

    def test_proration_full_period_charges_annual_dues_verbatim(self, api):
        """PRD: "When the invoice covers a full membership year — that is,
        the day count from `period_start` to `period_end` equals exactly 365
        — the charged `amount_cents` is the tier's `annual_dues_cents`
        exactly, with no proration arithmetic performed."

        Design: Difficulty/dual_variant_calc/dues_proration_midyear_vs_full_period
        """
        tier = create_tier(annual_dues_cents=120000)
        member = create_member(tier["id"], full_name="Annual Ann")
        # 2026-08-01 -> 2027-08-01 is exactly 365 days.
        resp = api.create_dues_invoice(
            {"member_id": member["id"],
             "period_start": "2026-08-01T00:00:00Z",
             "period_end": "2027-08-01T00:00:00Z"},
            OFFICER)
        invoice = validate_success(resp, 201)
        assert invoice["amount_cents"] == 120000, (
            "Full-year invoice charges annual dues exactly, no proration")


class TestPaymentSufficiency:
    def test_insufficient_payment_rejected(self, api):
        """PRD: "A payment suffices only if the tendered amount plus any
        previously accrued member credit covers the invoice's `amount_cents`
        in full; otherwise the posting is rejected with
        `ERR_PAYMENT_INSUFFICIENT` (HTTP 422)."
        PRD: "When coverage is complete, the invoice moves `OPEN → PAID`"

        Design: Corner/validations/insufficient_payment_rejected
        """
        tier = create_tier(annual_dues_cents=120000)
        member = create_member(tier["id"], full_name="Short Pay")
        invoice = issue_invoice(member["id"], "2026-08-01T00:00:00Z",
                                "2027-08-01T00:00:00Z")
        assert invoice["amount_cents"] == 120000

        resp = api.create_dues_payment(
            {"invoice_id": invoice["id"], "member_id": member["id"],
             "amount_cents": 119999},
            make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_PAYMENT_INSUFFICIENT)
        assert resp.status_code == 422

        ok = validate_success(
            api.create_dues_payment(
                {"invoice_id": invoice["id"], "member_id": member["id"],
                 "amount_cents": 120000},
                make_member_headers(member["id"])),
            201)
        assert_dues_payment(ok)

        settled = validate_success(api.get_dues_invoice(invoice["id"], OFFICER))
        assert settled["status"] == "PAID", (
            "Full payment flips the invoice OPEN -> PAID")


class TestDuesCreditConservation:
    def test_overpayment_creates_credit_and_settles_invoice(self, api):
        """PRD: "Overpayment is not lost: the excess becomes member credit,
        and each later settlement records in its own `credit_applied_cents`
        how much of a prior overpayment it consumed."
        PRD: "When coverage is complete, the invoice moves `OPEN → PAID`, and
        the member's `dues_paid_through` recomputes to the later of its
        current value and the invoice's `period_end`."

        Design: Difficulty/compensating_invariant/dues_payment_credit_conservation
        """
        tier = create_tier(annual_dues_cents=120000)
        member = create_member(tier["id"], full_name="Ledger Liz")
        invoice = issue_invoice(member["id"], "2026-08-01T00:00:00Z",
                                "2027-08-01T00:00:00Z")

        resp = api.create_dues_payment(
            {"invoice_id": invoice["id"], "member_id": member["id"],
             "amount_cents": 150000},
            make_member_headers(member["id"]))
        payment = validate_success(resp, 201)
        assert payment["credit_applied_cents"] == 0, (
            "The overpaying settlement consumes no prior credit — it creates "
            "30000 of new credit instead (150000 tendered == 120000 consumed "
            "+ 30000 outstanding)")

        settled = validate_success(api.get_dues_invoice(invoice["id"], OFFICER))
        assert settled["status"] == "PAID"

        refreshed = validate_success(api.get_member(member["id"], OFFICER))
        assert _instant(refreshed["dues_paid_through"]) == _instant(
            "2027-08-01T00:00:00Z"), (
            "dues_paid_through recomputes to the invoice's period_end")

    def test_credit_consumed_by_later_settlement(self, api):
        """PRD: "Overpayment is not lost: the excess becomes member credit,
        and each later settlement records in its own `credit_applied_cents`
        how much of a prior overpayment it consumed."
        PRD: "A payment suffices only if the tendered amount plus any
        previously accrued member credit covers the invoice's `amount_cents`
        in full"

        Design: Difficulty/compensating_invariant/dues_payment_credit_conservation
        """
        tier = create_tier(annual_dues_cents=120000)
        member = create_member(tier["id"], full_name="Credit Carol")
        inv1 = issue_invoice(member["id"], "2026-08-01T00:00:00Z",
                             "2027-08-01T00:00:00Z")
        pay_invoice(inv1["id"], member["id"], 150000)  # 30000 credit created

        inv2 = issue_invoice(member["id"], "2028-08-01T00:00:00Z",
                             "2029-08-01T00:00:00Z")
        # 2028-08-01 -> 2029-08-01 is exactly 365 days (the leap day
        # 2028-02-29 falls outside this window), so the full-year variant
        # charges the tier's annual_dues_cents verbatim.
        assert inv2["amount_cents"] == 120000
        # Tender only 90000; the 30000 credit covers the rest.
        resp = api.create_dues_payment(
            {"invoice_id": inv2["id"], "member_id": member["id"],
             "amount_cents": 90000},
            make_member_headers(member["id"]))
        payment2 = validate_success(resp, 201)
        assert payment2["credit_applied_cents"] == 30000, (
            "The later settlement consumes exactly the outstanding credit")

        settled2 = validate_success(api.get_dues_invoice(inv2["id"], OFFICER))
        assert settled2["status"] == "PAID", (
            "Tendered 90000 + 30000 credit covers the 120000 invoice")


class TestDuesPaymentAppendOnly:
    def test_dues_payment_immutable_no_update_endpoint(self, api):
        """PRD: "A `DuesPayment` and a `SkyQualityReading` are append-only
        records: they carry only `id` and `created_at` — neither `updated_at`
        nor `version` exists on these resources."

        Design: Corner/entities/dues_payment_immutable_no_update_endpoint
        """
        tier = create_tier(annual_dues_cents=120000)
        member = create_member(tier["id"], full_name="Append Al")
        invoice = issue_invoice(member["id"], "2026-08-01T00:00:00Z",
                                "2027-08-01T00:00:00Z")
        payment = pay_invoice(invoice["id"], member["id"], 120000)
        assert_dues_payment(payment)
        assert "updated_at" not in payment, (
            "DuesPayment is append-only: no updated_at field")
        assert "version" not in payment, (
            "DuesPayment is append-only: no version field")

        fetched = validate_success(api.get_dues_payment(payment["id"], OFFICER))
        assert "updated_at" not in fetched
        assert "version" not in fetched
