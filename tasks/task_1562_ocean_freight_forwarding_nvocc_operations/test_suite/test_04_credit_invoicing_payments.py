"""Shipper credit exposure variants, freight invoicing, and payments."""
from test_helpers import (
    ApiErrorId,
    create_confirmed_booking,
    create_draft_freight_invoice,
    create_issued_freight_invoice,
    create_quoted_booking,
    find_booking_invoice,
    setup_discharged_fcl_scenario,
    setup_lcl_lane,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import BC, FC, OPS


def _get_shipper(api, shipper_id):
    return validate_success(api.get_shipper(shipper_id, OPS), 200)


class TestPostedVsForwardExposure:
    def test_posted_exposure_zero_with_unbilled_confirmed_booking(self, api):
        """PRD §3.1: "The **posted** variant is the sum of `balance_cents`
        over every invoice belonging to this shipper whose status is `ISSUED`
        or `PARTIALLY_PAID`."

        Design: Difficulty/dual_variant_calc/credit_exposure_posted_vs_forward_divergence
        """
        ctx = setup_lcl_lane()
        create_confirmed_booking(ctx)

        shipper = _get_shipper(api, ctx["shipper"]["id"])
        assert shipper["credit_exposure_posted_cents"] == 0, (
            "no ISSUED/PARTIALLY_PAID invoices exist, so posted stays 0"
        )

    def test_forward_exposure_includes_unbilled_estimate(self, api):
        """PRD §3.1: "The **forward** variant is the posted value plus the sum
        of `estimated_freight_cents` over every booking of this shipper whose
        status is one of `CONFIRMED`, `DOCUMENTATION_CLEARED`, `LOADED`,
        `DEPARTED`, or `ARRIVED` and that does not yet have any FREIGHT
        invoice in `DRAFT`, `ISSUED`, `PARTIALLY_PAID`, or `PAID`."
        PRD §3.6: "On success the estimate is frozen and the shipper's
        `credit_exposure_forward_cents` now includes this booking."

        Design: Difficulty/dual_variant_calc/credit_exposure_posted_vs_forward_divergence
        """
        ctx = setup_lcl_lane()
        create_confirmed_booking(ctx)

        shipper = _get_shipper(api, ctx["shipper"]["id"])
        assert shipper["credit_exposure_forward_cents"] == 77400, (
            "base 57000 + BAF 5700 + THC 7200 + DOC 7500"
        )
        assert (shipper["credit_exposure_forward_cents"]
                > shipper["credit_exposure_posted_cents"]), (
            "the two variants diverge for identical invoice state"
        )

    def test_forward_input_set_excludes_quoted_and_cancelled(self, api):
        """PRD §3.1: "The **forward** variant is the posted value plus the sum
        of `estimated_freight_cents` over every booking of this shipper whose
        status is one of `CONFIRMED`, `DOCUMENTATION_CLEARED`, `LOADED`,
        `DEPARTED`, or `ARRIVED` and that does not yet have any FREIGHT
        invoice in `DRAFT`, `ISSUED`, `PARTIALLY_PAID`, or `PAID`."

        Design: Corner/calculations/credit_exposure_input_set_excludes_quoted_and_cancelled
        """
        ctx = setup_lcl_lane()
        booking = create_quoted_booking(ctx)

        shipper = _get_shipper(api, ctx["shipper"]["id"])
        assert shipper["credit_exposure_forward_cents"] == 0, (
            "QUOTED is not in the forward input set"
        )
        assert shipper["credit_exposure_posted_cents"] == 0

        validate_success(api.confirm_booking(booking["id"], BC), 200)
        validate_success(api.cancel_booking(booking["id"], BC,
                                            reason="input set check"), 200)
        shipper = _get_shipper(api, ctx["shipper"]["id"])
        assert shipper["credit_exposure_forward_cents"] == 0, (
            "CANCELLED is not in the forward input set either"
        )
        assert shipper["credit_exposure_posted_cents"] == 0


class TestConfirmCancelExposureConservation:
    def test_confirm_raises_forward_exposure(self, api):
        """PRD §3.6: "On success the estimate is frozen and the shipper's
        `credit_exposure_forward_cents` now includes this booking."

        Design: Difficulty/compensating_invariant/shipper_credit_exposure_confirm_cancel_conservation
        """
        ctx = setup_lcl_lane()
        booking = create_quoted_booking(ctx)
        baseline = _get_shipper(api, ctx["shipper"]["id"])
        assert baseline["credit_exposure_forward_cents"] == 0

        validate_success(api.confirm_booking(booking["id"], BC), 200)
        shipper = _get_shipper(api, ctx["shipper"]["id"])
        assert shipper["credit_exposure_forward_cents"] == 77400
        assert shipper["credit_exposure_posted_cents"] == 0

    def test_cancel_restores_exposure_baseline(self, api):
        """PRD §3.7: "From `QUOTED`, no cancellation fee applies. From
        `CONFIRMED` or `DOCUMENTATION_CLEARED`, cancellation auto-creates a
        `CANCELLATION` invoice in `DRAFT` with a single `CANCELLATION_FEE`
        line at a flat 75000 cents."
        PRD §3.1: "The **posted** variant is the sum of `balance_cents` over
        every invoice belonging to this shipper whose status is `ISSUED` or
        `PARTIALLY_PAID`."

        Design: Difficulty/compensating_invariant/shipper_credit_exposure_confirm_cancel_conservation
        """
        ctx = setup_lcl_lane()
        booking = create_confirmed_booking(ctx)
        validate_success(api.cancel_booking(booking["id"], BC,
                                            reason="compensation test"), 200)

        shipper = _get_shipper(api, ctx["shipper"]["id"])
        assert shipper["credit_exposure_forward_cents"] == 0
        assert shipper["credit_exposure_posted_cents"] == 0, (
            "the DRAFT cancellation invoice never enters either exposure variant"
        )

        cx = find_booking_invoice(booking["id"], "CANCELLATION")
        assert cx is not None and cx["status"] == "DRAFT"
        assert cx["total_cents"] == 75000
        cancelled = validate_success(api.get_booking(booking["id"], OPS), 200)
        assert cancelled["status"] == "CANCELLED"


class TestCreditLimitGate:
    def test_credit_limit_exact_equality_confirm_allowed_then_second_fails(
            self, api):
        """PRD §3.6: "The credit gate runs at confirm: the shipper's forward
        exposure **excluding this booking's own estimate**, plus this
        booking's `estimated_freight_cents`, must be less than or equal to the
        shipper's `credit_limit_cents`; equality is allowed. A failed gate
        rejects with `ERR_CREDIT_LIMIT_EXCEEDED`."

        Design: Corner/validations/credit_limit_exact_equality_confirm_allowed_then_second_fails
        """
        ctx = setup_lcl_lane(shipper_overrides={"credit_limit_cents": 77400})
        b1 = create_quoted_booking(ctx)
        b2 = create_quoted_booking(ctx)

        first = validate_success(api.confirm_booking(b1["id"], BC), 200)
        assert first["status"] == "CONFIRMED", "0 + 77400 <= 77400 (equality)"

        res = api.confirm_booking(b2["id"], BC)
        validate_error(res, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED,
                       expected_status=402)


class TestInvoicePayments:
    def _issued_freight_invoice(self, api, ctx):
        booking = create_confirmed_booking(ctx)
        invoice = create_issued_freight_invoice(booking["id"])
        assert invoice["total_cents"] == 77400
        return booking, invoice

    def test_invoice_overpayment_rejected(self, api):
        """PRD §3.12: "Payments — recorded by a `FinanceController` — carry an
        `amount_cents` that must be strictly greater than zero and less than
        or equal to the current `balance_cents`; a violation is rejected with
        `ERR_OVERPAYMENT`."

        Design: Corner/validations/invoice_overpayment_rejected
        """
        ctx = setup_lcl_lane()
        _booking, invoice = self._issued_freight_invoice(api, ctx)

        res = api.record_invoice_payment(invoice["id"], 77401, FC)
        validate_error(res, ApiErrorId.ERR_OVERPAYMENT, expected_status=422)
        after = validate_success(api.get_invoice(invoice["id"], FC), 200)
        assert after["status"] == "ISSUED"
        assert after["paid_cents"] == 0

        paid = validate_success(
            api.record_invoice_payment(invoice["id"], 77400, FC), 200)
        assert paid["status"] == "PAID", "exact balance payment settles"

    def test_partial_payment_self_loop(self, api):
        """PRD §3.12: "A payment smaller than the remaining balance
        transitions the invoice to `PARTIALLY_PAID` (and a further partial
        payment on an already `PARTIALLY_PAID` invoice is a self-loop back to
        `PARTIALLY_PAID`); a payment equal to the remaining balance
        transitions it to `PAID`."

        Design: Difficulty/non_linear_state_machine/invoice_partial_payment_self_loop
        """
        ctx = setup_lcl_lane()
        _booking, invoice = self._issued_freight_invoice(api, ctx)

        after_first = validate_success(
            api.record_invoice_payment(invoice["id"], 50000, FC), 200)
        assert after_first["status"] == "PARTIALLY_PAID"
        assert after_first["balance_cents"] == 27400

        after_second = validate_success(
            api.record_invoice_payment(invoice["id"], 10000, FC), 200)
        assert after_second["status"] == "PARTIALLY_PAID", (
            "PARTIALLY_PAID -> PARTIALLY_PAID self-loop"
        )
        assert after_second["balance_cents"] == 17400

    def test_final_payment_settles_to_paid(self, api):
        """PRD §3.12: "A payment smaller than the remaining balance
        transitions the invoice to `PARTIALLY_PAID` (and a further partial
        payment on an already `PARTIALLY_PAID` invoice is a self-loop back to
        `PARTIALLY_PAID`); a payment equal to the remaining balance
        transitions it to `PAID`."

        Design: Difficulty/non_linear_state_machine/invoice_partial_payment_self_loop
        """
        ctx = setup_lcl_lane()
        _booking, invoice = self._issued_freight_invoice(api, ctx)
        validate_success(api.record_invoice_payment(invoice["id"], 50000, FC), 200)
        validate_success(api.record_invoice_payment(invoice["id"], 10000, FC), 200)

        settled = validate_success(
            api.record_invoice_payment(invoice["id"], 17400, FC), 200)
        assert settled["status"] == "PAID"
        assert settled["balance_cents"] == 0
        assert settled["paid_cents"] == 77400


class TestPerLineRoundingOrder:
    def _draft_freight_invoice(self, api, ctx):
        booking = create_confirmed_booking(ctx)
        invoice = create_draft_freight_invoice(booking["id"])
        assert invoice["total_cents"] == 77400
        assert invoice["version"] == 1
        return invoice

    def test_pinned_per_line_rounding_beats_sum_then_round(self, api):
        """PRD §2.7: "Invoice line rounding is **pinned per line**: each
        line's `amount_cents` is independently rounded to integer cents via
        round half up from the product of `quantity` and `unit_rate_cents`,
        and the invoice `total_cents` is the plain sum of those per-line
        rounded amounts. Summing raw unrounded products and rounding once at
        the end is incorrect and yields different cents whenever a line
        product has a fractional cent."

        Design: Difficulty/combinatorial_formula/invoice_per_line_rounding_order_mode_b
        """
        ctx = setup_lcl_lane()
        invoice = self._draft_freight_invoice(api, ctx)

        after_one = validate_success(
            api.add_invoice_adjustment(invoice["id"], "SURCH-1", 0.5, 2999,
                                       invoice["version"], FC),
            200)
        # 77400 + round_half_up(0.5 x 2999) = 77400 + 1500.
        assert after_one["total_cents"] == 78900

        after_two = validate_success(
            api.add_invoice_adjustment(invoice["id"], "SURCH-2", 0.5, 2999,
                                       after_one["version"], FC),
            200)
        assert after_two["total_cents"] == 80400, (
            "pinned order: 77400 + 1500 + 1500; sum-then-round would give 80399"
        )

    def test_adjustment_bumps_invoice_version(self, api):
        """PRD §3.12: "The new line has `line_type` `MANUAL_ADJUSTMENT`, its
        `amount_cents` is rounded per the pinned per-line rule, `total_cents`
        is recomputed as the sum of rounded lines, and the invoice's `version`
        increments by one."
        PRD §2.4: "`version` (integer): a system-managed counter that starts
        at 1 on creation and increments by one on every mutation of the
        resource."

        Design: Difficulty/combinatorial_formula/invoice_per_line_rounding_order_mode_b
        """
        ctx = setup_lcl_lane()
        invoice = self._draft_freight_invoice(api, ctx)

        after_one = validate_success(
            api.add_invoice_adjustment(invoice["id"], "SURCH-1", 0.5, 2999,
                                       invoice["version"], FC),
            200)
        assert after_one["version"] == 2
        after_two = validate_success(
            api.add_invoice_adjustment(invoice["id"], "SURCH-2", 0.5, 2999,
                                       after_one["version"], FC),
            200)
        assert after_two["version"] == 3
        manual = [l for l in after_two["lines"]
                  if l["line_type"] == "MANUAL_ADJUSTMENT"]
        assert len(manual) == 2
        assert all(l["amount_cents"] == 1500 for l in manual)


class TestFreightInvoiceUniqueness:
    def test_duplicate_freight_invoice_per_booking_rejected(self, api):
        """PRD §3.12: "At most one FREIGHT invoice exists per booking; a
        second attempt is rejected with `ERR_INVOICE_EXISTS`."

        Design: Corner/validations/duplicate_freight_invoice_per_booking_rejected
        """
        ctx = setup_lcl_lane()
        booking = create_confirmed_booking(ctx)
        create_draft_freight_invoice(booking["id"])

        res = api.create_invoice({"booking_id": booking["id"],
                                  "invoice_type": "FREIGHT"}, FC)
        validate_error(res, ApiErrorId.ERR_INVOICE_EXISTS, expected_status=409)


class TestAutoSuspendThreshold:
    def test_rate_threshold_auto_suspend_on_invoice_issue(self, api):
        """PRD §3.1: "Suspension also happens automatically: when an invoice
        issue leaves the shipper's posted exposure greater than its
        `credit_limit_cents`, the system transitions the shipper from `ACTIVE`
        to `SUSPENDED` without further operator action."
        PRD §3.1: "The **posted** variant is the sum of `balance_cents` over
        every invoice belonging to this shipper whose status is `ISSUED` or
        `PARTIALLY_PAID`."

        Design: Corner/complexity_layers/rate_threshold_auto_suspend_on_invoice_issue
        """
        ctx = setup_discharged_fcl_scenario(
            shipper_overrides={"credit_limit_cents": 250000})
        booking = ctx["booking"]

        # FREIGHT invoice (236000) issued while booking is ARRIVED: posting
        # stays within the 250000 limit, so the shipper remains ACTIVE.
        freight = create_issued_freight_invoice(booking["id"])
        assert freight["total_cents"] == 236000
        shipper = _get_shipper(api, ctx["shipper"]["id"])
        assert shipper["status"] == "ACTIVE"
        assert shipper["credit_exposure_posted_cents"] == 236000

        # Gate out (+5 demurrage days = 105000) and return (+3 detention days
        # = 36000): empty-return auto-creates the D&D invoice.
        validate_success(api.set_clock("2026-09-30T12:00:00Z", OPS), 200)
        validate_success(
            api.gate_out_assignment(ctx["assignment"]["id"], BC), 200)
        validate_success(api.set_clock("2026-10-06T12:00:00Z", OPS), 200)
        validate_success(
            api.empty_return_assignment(ctx["assignment"]["id"], BC), 200)

        dd = find_booking_invoice(booking["id"], "DEMURRAGE_DETENTION")
        assert dd is not None, "empty-return must auto-create the D&D invoice"
        assert dd["total_cents"] == 141000
        assert dd["status"] == "DRAFT"

        validate_success(api.issue_invoice(dd["id"], FC), 200)
        shipper = _get_shipper(api, ctx["shipper"]["id"])
        assert shipper["credit_exposure_posted_cents"] == 377000
        assert shipper["status"] == "SUSPENDED", (
            "the issue event crossing the limit auto-suspends the shipper"
        )
