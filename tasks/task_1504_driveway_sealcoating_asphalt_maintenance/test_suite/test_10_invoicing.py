"""Invoicing and settlement: provisional-vs-final pricing variants, pinned
rounding order, the billing dimension, and payment exactness."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_invoice,
    assert_work_order,
    find_invoice_for_work_order,
    get_invoice,
    get_work_order,
    make_customer_headers,
    setup_completed_job,
    setup_issued_invoice,
    setup_quote_scenario,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["office_admin_headers"]

# Standard commercial job: assessment 1200/40/2/10/5, actuals 1250/44/12.
ACTUALS_1250 = {
    "actual_area_sqft": 1250,
    "actual_crack_ft": 44,
    "actual_pothole_area_sqft": 12,
    "actual_stripe_ft": 0,
    "gallons_used": 17,
}


class TestProvisionalVsFinalPricing:
    """The same job priced twice: provisionally on assessment snapshots,
    finally on crew-recorded actuals."""

    def test_provisional_quote_pricing_on_snapshots(self, api):
        """PRD §3.3: "At creation the quote pins three measurement snapshots
        from the assessment — `area_sqft_snapshot`, `crack_ft_snapshot`, and
        `pothole_area_snapshot` — and computes provisional pricing."

        Design: Difficulty/dual_variant_calc/quote_provisional_vs_final_invoice_pricing
        """
        ctx = setup_quote_scenario()
        quote = ctx["quote"]
        assert quote["area_sqft_snapshot"] == 1200
        assert quote["crack_ft_snapshot"] == 40
        assert quote["pothole_area_snapshot"] == 10
        assert quote["subtotal_cents"] == 42800
        assert quote["mobilization_fee_cents"] == 7500
        assert quote["total_cents"] == 50300, (
            f"provisional total on snapshots, got {quote['total_cents']}"
        )

    def test_final_invoice_pricing_on_actuals_diverges(self, api):
        """PRD §3.9: "Its `line_items` recompute the four scope lines — seal,
        crack fill, patch, striping — using the identical tier rates, grade
        factors, per-unit rates, and per-line half-up rounding of the quote,
        but applied to `actual_area_sqft`, `actual_crack_ft`,
        `actual_pothole_area_sqft`, and `actual_stripe_ft`." and
        "`total_cents` is the subtotal plus the surcharge."

        Design: Difficulty/dual_variant_calc/quote_provisional_vs_final_invoice_pricing
        """
        ctx = setup_completed_job(actuals=ACTUALS_1250)
        assert ctx["quote"]["total_cents"] == 50300
        invoice = find_invoice_for_work_order(ctx["work_order"]["id"])
        assert_invoice(invoice)
        assert invoice["status"] == "DRAFT"
        # Final on actuals: seal 1250*24 = 30000; crack 44*150 = 6600;
        # patch 12*800 = 9600; lines 46200 < 200000 -> mobilization 7500.
        assert invoice["subtotal_cents"] == 53700, (
            f"46200 + 7500 mobilization = 53700, got {invoice['subtotal_cents']}"
        )
        assert invoice["fuel_surcharge_cents"] == 3222, (
            f"53700 < 100000 -> 6% = 3222, got {invoice['fuel_surcharge_cents']}"
        )
        assert invoice["total_cents"] == 56922
        assert invoice["total_cents"] != ctx["quote"]["total_cents"], (
            "provisional and final variants diverge whenever actuals differ"
        )


class TestInvoiceRoundingOrderPinned:
    """Per-line round-half-up then sum is pinned; sum-then-round would be one
    cent lower on this fixture (39981.6c seal float, 1522.5c crack float)."""

    def _completed_premium_job(self, api):
        ctx = setup_completed_job(
            lot_kind="COMMERCIAL_LOT",
            address="55 Market St",
            customer_overrides={"name": "Beta Retail LLC", "email": "ops@beta.example",
                                "phone": "555-0200"},
            measured_area_sqft=1234,
            crack_linear_ft=10.15,
            pothole_count=0,
            pothole_area_sqft=0,
            oil_spot_area_sqft=0,
            material_overrides={
                "product_name": "SealMaster Premium",
                "grade": "PREMIUM",
                "coverage_sqft_per_gallon": 70,
                "reapplication_months": 36,
                "warranty_months": 24,
                "price_per_gallon_cents": 1500,
            },
            quote_overrides={"include_patch": False},
            delivered_gallons=200,
            drive_minutes_est=15,
            vehicles_to_move=0,
            actuals={
                "actual_area_sqft": 1234,
                "actual_crack_ft": 10.15,
                "actual_pothole_area_sqft": 0,
                "actual_stripe_ft": 0,
                "gallons_used": 18,
            },
        )
        return ctx

    def test_per_line_rounding_before_sum(self, api):
        """PRD §3.9: "The evaluation order is pinned: round each line to
        integer cents first; then a mobilization line of 7500 cents joins when
        the sum of those four rounded lines is strictly below 200000 cents".
        PRD §2.5: "implementations that sum unrounded intermediate values and
        round once at the end produce different cent amounts and are
        non-conformant."

        Design: Difficulty/combinatorial_formula/invoice_rounding_order_pinned
        """
        ctx = self._completed_premium_job(api)
        invoice = find_invoice_for_work_order(ctx["work_order"]["id"])
        amounts = sorted(
            line["amount_cents"] for line in invoice["line_items"] if line["amount_cents"] > 0
        )
        # seal round_half_up(1234 * 24 * 1.35 = 39981.6) = 39982;
        # crack round_half_up(10.15 * 150 = 1522.5) = 1523; mobilization 7500.
        assert amounts == [1523, 7500, 39982], (
            f"each line rounds half-up to integer cents first: {amounts}"
        )
        # Pinned order: 39982 + 1523 + 7500 = 49005 (sum-then-round gives 49004).
        assert invoice["subtotal_cents"] == 49005, (
            f"per-line-first rounding yields 49005, got {invoice['subtotal_cents']}"
        )

    def test_surcharge_tiered_on_rounded_subtotal(self, api):
        """PRD §3.9: "a fuel surcharge tier is then keyed on that rounded
        subtotal — 6 percent when below 100000 cents, 4 percent when at least
        100000 but below 500000, 2 percent when at least 500000 — and
        `fuel_surcharge_cents` is the rounded-half-up product; `total_cents`
        is the subtotal plus the surcharge."

        Design: Difficulty/combinatorial_formula/invoice_rounding_order_pinned
        """
        ctx = self._completed_premium_job(api)
        invoice = find_invoice_for_work_order(ctx["work_order"]["id"])
        assert invoice["subtotal_cents"] == 49005
        assert invoice["fuel_surcharge_cents"] == 2940, (
            f"49005 < 100000 -> round_half_up(49005 * 0.06) = 2940, "
            f"got {invoice['fuel_surcharge_cents']}"
        )
        assert invoice["total_cents"] == 51945


class TestParallelStateDimensions:
    """Execution and billing evolve independently; payment collapses a
    COMPLETED job to CLOSED."""

    def test_complete_leaves_billing_uninvoiced_and_issue_advances_billing(self, api):
        """PRD §3.4: "The billing dimension runs `UNINVOICED → INVOICED →
        PAID`, driven entirely by the invoice lifecycle." PRD §3.9: "An
        `OfficeAdmin` issues a `DRAFT` invoice (else
        `ERR_INVOICE_NOT_ISSUABLE`), stamping `issued_at` and flipping the
        work order's billing dimension to `INVOICED`."

        Design: Difficulty/non_linear_state_machine/work_order_parallel_state_dimensions
        """
        ctx = setup_completed_job(actuals=ACTUALS_1250)
        wo = ctx["work_order"]
        assert wo["execution_status"] == "COMPLETED"
        assert wo["billing_status"] == "UNINVOICED", (
            "completion does not advance the billing dimension"
        )
        assert wo["striping_status"] == "NOT_REQUIRED"

        invoice = find_invoice_for_work_order(wo["id"])
        issued = validate_success(api.issue_invoice(invoice["id"], ADMIN))
        assert issued["status"] == "ISSUED"
        assert issued["issued_at"] is not None
        wo_after = get_work_order(wo["id"])
        assert wo_after["billing_status"] == "INVOICED"
        assert wo_after["execution_status"] == "COMPLETED", (
            "issuing touches billing only"
        )
        assert wo_after["striping_status"] == "NOT_REQUIRED"

    def test_payment_closes_completed_work_order(self, api):
        """PRD §3.7: "A completed work order whose invoice reaches `PAID`
        closes automatically, moving execution to `CLOSED`." PRD §3.9:
        "Payment stamps `paid_at`, moves billing to `PAID`, and closes a
        `COMPLETED` work order as described in §3.7."

        Design: Difficulty/non_linear_state_machine/work_order_parallel_state_dimensions
        """
        ctx = setup_issued_invoice(actuals=ACTUALS_1250)
        invoice = ctx["invoice"]
        assert invoice["total_cents"] == 56922

        paid = validate_success(
            api.pay_invoice(
                invoice["id"],
                {"amount_cents": 56922},
                make_customer_headers(ctx["customer"]["id"]),
            )
        )
        assert paid["status"] == "PAID"
        assert paid["paid_at"] is not None

        wo = get_work_order(ctx["work_order"]["id"])
        assert_work_order(wo)
        assert wo["billing_status"] == "PAID"
        assert wo["execution_status"] == "CLOSED", (
            "pay collapses the execution dimension to CLOSED"
        )
        assert wo["striping_status"] == "NOT_REQUIRED"


class TestPaymentExactness:
    def test_underpayment_rejected_then_exact_payment_succeeds(self, api):
        """PRD §3.9: "Payment — by the owning customer or an `OfficeAdmin` —
        requires `ISSUED` (else `ERR_INVOICE_NOT_PAYABLE`), and the tendered
        `amount_cents` must equal the invoice's `total_cents` exactly (else
        `ERR_PAYMENT_AMOUNT_MISMATCH`)."

        Design: Corner/errors/payment_amount_mismatch_rejected
        """
        ctx = setup_issued_invoice(actuals=ACTUALS_1250)
        invoice = ctx["invoice"]
        assert invoice["total_cents"] == 56922

        resp = api.pay_invoice(invoice["id"], {"amount_cents": 56921}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_PAYMENT_AMOUNT_MISMATCH, 422)
        assert get_invoice(invoice["id"])["status"] == "ISSUED"

        paid = validate_success(
            api.pay_invoice(invoice["id"], {"amount_cents": 56922}, ADMIN)
        )
        assert paid["status"] == "PAID"
        assert paid["paid_at"] is not None


class TestPayBeforeIssue:
    def test_pay_on_draft_invoice_rejected(self, api):
        """PRD §3.9: "Payment — by the owning customer or an `OfficeAdmin` —
        requires `ISSUED` (else `ERR_INVOICE_NOT_PAYABLE`)".

        Design: Corner/errors/invoice_pay_before_issue_rejected
        """
        ctx = setup_completed_job(
            lot_kind="RESIDENTIAL_DRIVEWAY", address="1 Elm St",
            measured_area_sqft=900, crack_linear_ft=10, pothole_count=1,
            pothole_area_sqft=2, window_start_hour=7, window_end_hour=10,
            drive_minutes_est=15, vehicles_to_move=1,
        )
        invoice = find_invoice_for_work_order(ctx["work_order"]["id"])
        assert invoice["status"] == "DRAFT"
        # Final on actuals 900/10/2: seal 27000 + crack 1500 + patch 1600
        # = 30100 < 200000 -> mobilization 7500 -> subtotal 37600;
        # surcharge 6% = 2256 -> total 39856.
        assert invoice["subtotal_cents"] == 37600, (
            f"30100 + 7500 = 37600, got {invoice['subtotal_cents']}"
        )
        assert invoice["fuel_surcharge_cents"] == 2256
        assert invoice["total_cents"] == 39856

        resp = api.pay_invoice(
            invoice["id"], {"amount_cents": invoice["total_cents"]}, ADMIN
        )
        validate_error(resp, ApiErrorId.ERR_INVOICE_NOT_PAYABLE, 409)


class TestIssueTwice:
    def test_second_issue_rejected(self, api):
        """PRD §3.9: "An `OfficeAdmin` issues a `DRAFT` invoice (else
        `ERR_INVOICE_NOT_ISSUABLE`), stamping `issued_at` and flipping the
        work order's billing dimension to `INVOICED`."

        Design: Corner/state_machines/invoice_issue_twice_rejected
        """
        ctx = setup_issued_invoice(
            lot_kind="RESIDENTIAL_DRIVEWAY", address="1 Elm St",
            measured_area_sqft=900, crack_linear_ft=10, pothole_count=1,
            pothole_area_sqft=2, window_start_hour=7, window_end_hour=10,
            drive_minutes_est=15, vehicles_to_move=1,
        )
        invoice = ctx["invoice"]
        assert invoice["status"] == "ISSUED"

        resp = api.issue_invoice(invoice["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVOICE_NOT_ISSUABLE, 409)

        after = get_invoice(invoice["id"])
        assert after["status"] == "ISSUED"
        assert after["issued_at"] == invoice["issued_at"], (
            "a rejected re-issue must not restamp issued_at"
        )
