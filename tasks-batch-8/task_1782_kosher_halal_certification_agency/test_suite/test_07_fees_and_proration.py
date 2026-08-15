"""Fee arithmetic: proration variants, rounding order, volume discount."""
from test_helpers import (
    ApiErrorId,
    create_certifiable_product,
    find_invoices,
    get_client,
    make_officer_headers,
    set_clock,
    setup_certified_client,
    validate_error,
    validate_success,
)

def _officer():
    return make_officer_headers("co-1")


class TestProrataDualVariant:
    def test_prorata_fee_anniversary_vs_calendar_year_divergence(self, api):
        """PRD section 3.8: "Each product's line is prorated forward-looking:
        the cycle end is the active agreement's `term_end_date` under an
        `ANNIVERSARY` cycle, or December 31 of the addition year under a
        `CALENDAR_YEAR` cycle — so identical inputs price differently whenever
        the term end is not December 31."

        Design: Difficulty/dual_variant_calc/prorata_fee_anniversary_vs_calendar_year_divergence
        """
        ctx_a = setup_certified_client(legal_name="Anniv Co",
                                       billing_cycle="ANNIVERSARY",
                                       term_start_date="2026-04-01",
                                       per_product_fee_cents=73000)
        ctx_b = setup_certified_client(legal_name="CalYear Co",
                                       billing_cycle="CALENDAR_YEAR",
                                       term_start_date="2026-04-01",
                                       per_product_fee_cents=73000)
        assert ctx_a["agreement"]["term_end_date"] == "2027-03-31"
        assert ctx_b["agreement"]["term_end_date"] == "2026-12-31"

        set_clock("2026-07-01T00:00:00Z")
        extra_a = create_certifiable_product(
            ctx_a["client"]["id"], [ctx_a["ingredients"][0]["id"]], name="PA2")
        extra_b = create_certifiable_product(
            ctx_b["client"]["id"], [ctx_b["ingredients"][0]["id"]], name="PB2")
        validate_success(api.add_certificate_products(
            ctx_a["certificate"]["id"], [extra_a["id"]], _officer()), 201)
        validate_success(api.add_certificate_products(
            ctx_b["certificate"]["id"], [extra_b["id"]], _officer()), 201)

        inv_a = find_invoices(invoice_type="PRODUCT_ADDITION",
                              related_certificate_id=ctx_a["certificate"]["id"])
        inv_b = find_invoices(invoice_type="PRODUCT_ADDITION",
                              related_certificate_id=ctx_b["certificate"]["id"])
        assert len(inv_a) == 1 and len(inv_b) == 1
        assert inv_a[0]["total_cents"] == 54600, (
            "73000 x 273/365 (term end 2027-03-31) = 54600")
        assert inv_b[0]["total_cents"] == 36600, (
            "73000 x 183/365 (cycle end 2026-12-31) = 36600")
        assert inv_a[0]["total_cents"] != inv_b[0]["total_cents"], (
            "identical fee and addition date price differently by billing cycle")

    def test_prorata_fee_calendar_year_invoice_fields(self, api):
        """PRD section 3.8: "Days remaining are the calendar days from the
        addition date up to but not including the cycle end date, floored at
        zero. The raw line amount is `per_product_fee_cents` multiplied by days
        remaining and divided by 365; each line is rounded half-up to integer
        cents individually". PRD section 3.8: "`discount_cents` defaults to zero
        when no tier applies."

        Design: Difficulty/dual_variant_calc/prorata_fee_anniversary_vs_calendar_year_divergence
        """
        ctx_b = setup_certified_client(legal_name="CalYear Co 2",
                                       billing_cycle="CALENDAR_YEAR",
                                       term_start_date="2026-04-01",
                                       per_product_fee_cents=73000)
        set_clock("2026-07-01T00:00:00Z")
        extra_b = create_certifiable_product(
            ctx_b["client"]["id"], [ctx_b["ingredients"][0]["id"]], name="PB2")
        validate_success(api.add_certificate_products(
            ctx_b["certificate"]["id"], [extra_b["id"]], _officer()), 201)
        inv_b = find_invoices(invoice_type="PRODUCT_ADDITION",
                              related_certificate_id=ctx_b["certificate"]["id"])
        assert len(inv_b) == 1
        assert inv_b[0]["subtotal_cents"] == 36600
        assert inv_b[0]["discount_cents"] == 0
        assert inv_b[0]["total_cents"] == 36600
        assert inv_b[0]["status"] == "ISSUED"


class TestPerLineRoundingOrder:
    def test_product_addition_per_line_rounding_then_sum(self, api):
        """PRD section 3.8: "each line is rounded half-up to integer cents
        individually, and `subtotal_cents` is the sum of the rounded lines —
        summing first and rounding once is forbidden."

        Design: Difficulty/combinatorial_formula/product_addition_per_line_rounding_then_sum
        """
        ctx = setup_certified_client(legal_name="Round Co",
                                     billing_cycle="ANNIVERSARY",
                                     term_start_date="2026-01-01",
                                     per_product_fee_cents=10000,
                                     num_products=1)
        assert ctx["agreement"]["term_end_date"] == "2026-12-31"
        set_clock("2026-07-01T00:00:00Z")
        p2 = create_certifiable_product(
            ctx["client"]["id"], [ctx["ingredients"][0]["id"]], name="PR2")
        p3 = create_certifiable_product(
            ctx["client"]["id"], [ctx["ingredients"][0]["id"]], name="PR3")
        validate_success(api.add_certificate_products(
            ctx["certificate"]["id"], [p2["id"], p3["id"]], _officer()), 201)

        inv = find_invoices(invoice_type="PRODUCT_ADDITION",
                            related_certificate_id=ctx["certificate"]["id"])
        assert len(inv) == 1
        assert inv[0]["subtotal_cents"] == 10028, (
            "round_half_up(10000 x 183/365) = 5014 per line, twice: 10028; "
            "the forbidden sum-then-round would give 10027")
        assert inv[0]["total_cents"] == 10028

    def test_product_addition_updates_listed_count(self, api, officer_headers):
        """PRD section 3.7: "The call creates one `INCLUDED` entry per product,
        increments `active_product_count` accordingly". PRD section 3.8:
        "`discount_cents` defaults to zero when no tier applies."

        Design: Difficulty/combinatorial_formula/product_addition_per_line_rounding_then_sum
        """
        ctx = setup_certified_client(legal_name="Round Co 2",
                                     billing_cycle="ANNIVERSARY",
                                     term_start_date="2026-01-01",
                                     per_product_fee_cents=10000,
                                     num_products=1)
        set_clock("2026-07-01T00:00:00Z")
        p2 = create_certifiable_product(
            ctx["client"]["id"], [ctx["ingredients"][0]["id"]], name="PR2")
        p3 = create_certifiable_product(
            ctx["client"]["id"], [ctx["ingredients"][0]["id"]], name="PR3")
        entries = validate_success(api.add_certificate_products(
            ctx["certificate"]["id"], [p2["id"], p3["id"]], _officer()), 201)
        assert len(entries) == 2
        assert all(e["status"] == "INCLUDED" for e in entries)

        cert = validate_success(api.get_certificate(ctx["certificate"]["id"],
                                                    officer_headers))
        assert cert["active_product_count"] == 3
        inv = find_invoices(invoice_type="PRODUCT_ADDITION",
                            related_certificate_id=ctx["certificate"]["id"])
        assert inv[0]["subtotal_cents"] == 10028
        assert inv[0]["discount_cents"] == 0, "subtotal 10028 is below 100000"
        assert inv[0]["total_cents"] == 10028


class TestVolumeDiscount:
    def test_volume_discount_priced_on_prediscount_subtotal(self, api):
        """PRD section 3.8: "A volume discount then applies exactly once, keyed
        on the pre-discount subtotal: ten percent when the subtotal is at least
        200000 cents, five percent when at least 100000 cents, otherwise zero,
        with the discount amount itself rounded half-up". PRD section 2.6:
        "Volume-discount tier selection keys on the pre-discount subtotal
        exactly once; the post-discount total never re-enters tier selection,
        even when subtracting the discount drops the total below the threshold
        that granted it."

        Design: Difficulty/combinatorial_formula/volume_discount_priced_on_prediscount_subtotal
        """
        ctx = setup_certified_client(legal_name="Disc Co",
                                     billing_cycle="ANNIVERSARY",
                                     term_start_date="2026-01-01",
                                     per_product_fee_cents=100000,
                                     num_products=1)
        set_clock("2026-07-01T00:00:00Z")
        p2 = create_certifiable_product(
            ctx["client"]["id"], [ctx["ingredients"][0]["id"]], name="PD2")
        p3 = create_certifiable_product(
            ctx["client"]["id"], [ctx["ingredients"][0]["id"]], name="PD3")
        validate_success(api.add_certificate_products(
            ctx["certificate"]["id"], [p2["id"], p3["id"]], _officer()), 201)

        inv = find_invoices(invoice_type="PRODUCT_ADDITION",
                            related_certificate_id=ctx["certificate"]["id"])
        assert len(inv) == 1
        assert inv[0]["subtotal_cents"] == 100274, "2 x round(100000 x 183/365)"
        assert inv[0]["discount_cents"] == 5014, (
            "round_half_up(100274 x 5/100) = 5014")
        assert inv[0]["total_cents"] == 95260

    def test_volume_discount_total_below_tier_not_retiered(self, api):
        """PRD section 2.6: "the post-discount total never re-enters tier
        selection, even when subtracting the discount drops the total below the
        threshold that granted it."

        Design: Difficulty/combinatorial_formula/volume_discount_priced_on_prediscount_subtotal
        """
        ctx = setup_certified_client(legal_name="Disc Co 2",
                                     billing_cycle="ANNIVERSARY",
                                     term_start_date="2026-01-01",
                                     per_product_fee_cents=100000,
                                     num_products=1)
        set_clock("2026-07-01T00:00:00Z")
        p2 = create_certifiable_product(
            ctx["client"]["id"], [ctx["ingredients"][0]["id"]], name="PD2")
        p3 = create_certifiable_product(
            ctx["client"]["id"], [ctx["ingredients"][0]["id"]], name="PD3")
        validate_success(api.add_certificate_products(
            ctx["certificate"]["id"], [p2["id"], p3["id"]], _officer()), 201)

        inv = find_invoices(invoice_type="PRODUCT_ADDITION",
                            related_certificate_id=ctx["certificate"]["id"])
        assert inv[0]["total_cents"] == 95260 < 100000, (
            "the discounted total lands below the 5% tier threshold")
        assert inv[0]["discount_cents"] == 5014 != 0, (
            "yet the tier was evaluated once on the pre-discount subtotal")


class TestZeroDayProration:
    def test_zero_day_proration_produces_zero_total_auto_paid_invoice(
            self, api, officer_headers):
        """PRD section 3.8: "Days remaining are the calendar days from the
        addition date up to but not including the cycle end date, floored at
        zero." PRD section 3.8: "A zero-total invoice — possible when nothing
        remains to bill — is created directly in `PAID` status with
        `paid_recorded_by` set to the literal string `system`."

        Design: Difficulty/boundary_precision_check/zero_day_proration_produces_zero_total_auto_paid_invoice
        """
        ctx = setup_certified_client(legal_name="Zero Co",
                                     billing_cycle="ANNIVERSARY",
                                     term_start_date="2026-01-01",
                                     num_products=1)
        assert ctx["agreement"]["term_end_date"] == "2026-12-31"
        set_clock("2026-12-31T10:00:00Z")
        p2 = create_certifiable_product(
            ctx["client"]["id"], [ctx["ingredients"][0]["id"]], name="PZr2")
        validate_success(api.add_certificate_products(
            ctx["certificate"]["id"], [p2["id"]], _officer()), 201)

        inv = find_invoices(invoice_type="PRODUCT_ADDITION",
                            related_certificate_id=ctx["certificate"]["id"])
        assert len(inv) == 1
        assert inv[0]["total_cents"] == 0, (
            "days_remaining == 0 on the cycle's final day")
        assert inv[0]["status"] == "PAID", "zero-total auto-payment"
        assert inv[0]["paid_recorded_by"] == "system"
        assert get_client(ctx["client"]["id"])["total_billed_cents"] == 120000, (
            "the zero invoice does not move the billed ledger")

    def test_zero_day_proration_still_lists_the_product(self, api,
                                                        officer_headers):
        """PRD section 3.7: "The call creates one `INCLUDED` entry per product,
        increments `active_product_count` accordingly". PRD section 3.8: "A
        zero-total invoice — possible when nothing remains to bill — is created
        directly in `PAID` status with `paid_recorded_by` set to the literal
        string `system`."

        Design: Difficulty/boundary_precision_check/zero_day_proration_produces_zero_total_auto_paid_invoice
        """
        ctx = setup_certified_client(legal_name="Zero Co 2",
                                     billing_cycle="ANNIVERSARY",
                                     term_start_date="2026-01-01",
                                     num_products=1)
        set_clock("2026-12-31T10:00:00Z")
        p2 = create_certifiable_product(
            ctx["client"]["id"], [ctx["ingredients"][0]["id"]], name="PZr2")
        entries = validate_success(api.add_certificate_products(
            ctx["certificate"]["id"], [p2["id"]], _officer()), 201)
        assert len(entries) == 1 and entries[0]["status"] == "INCLUDED"

        cert = validate_success(api.get_certificate(ctx["certificate"]["id"],
                                                    officer_headers))
        assert cert["active_product_count"] == 2, (
            "the zero-fee addition still lists the product")
        inv = find_invoices(invoice_type="PRODUCT_ADDITION",
                            related_certificate_id=ctx["certificate"]["id"])
        assert inv[0]["status"] == "PAID"
        assert inv[0]["paid_recorded_by"] == "system"


class TestAddProductsAtomicity:
    def test_add_products_atomicity_on_partial_failure(self, api,
                                                       officer_headers):
        """PRD section 3.7: "Adding products to an `ACTIVE` certificate is
        atomic: the call names one or more `product_ids`, and any failure
        rejects the whole call." PRD section 3.7: "must not already be listed on
        this certificate in `INCLUDED` or `FROZEN`
        (`ERR_PRODUCT_ALREADY_CERTIFIED`)".

        Design: Corner/validations/add_products_atomicity_on_partial_failure
        """
        ctx = setup_certified_client(legal_name="AT Co", num_products=2)
        listed = ctx["products"][1]
        unlisted = create_certifiable_product(
            ctx["client"]["id"], [ctx["ingredients"][0]["id"]], name="PA2")
        billed_before = get_client(ctx["client"]["id"])["total_billed_cents"]

        resp = api.add_certificate_products(
            ctx["certificate"]["id"], [unlisted["id"], listed["id"]],
            _officer())
        validate_error(resp, ApiErrorId.ERR_PRODUCT_ALREADY_CERTIFIED)

        cert = validate_success(api.get_certificate(ctx["certificate"]["id"],
                                                    officer_headers))
        assert cert["active_product_count"] == 2, (
            "the valid product in the same call must not be added")
        assert get_client(ctx["client"]["id"])[
            "total_billed_cents"] == billed_before, (
                "no PRODUCT_ADDITION invoice persisted after the atomic failure")
        assert find_invoices(
            invoice_type="PRODUCT_ADDITION",
            related_certificate_id=ctx["certificate"]["id"]) == []
