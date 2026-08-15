"""CIAC invoicing: payments, refunds, segregation of duties, and the final true-up."""
from test_helpers import (
    ApiErrorId,
    ONE_ASPHALT_CROSSING,
    TWO_ASPHALT_CROSSINGS,
    TWO_LOADS,
    assert_ciac_payment,
    build_user_headers,
    get_success_data,
    refresh_application,
    refresh_invoice,
    refresh_main_extension,
    refund_invoice,
    setup_as_built_recorded_app,
    setup_ciac_pending_app,
    validate_error,
    validate_paginated,
    validate_success,
)

# As-built inputs shared by the true-up scenarios
AS_BUILT_LARGER = dict(
    actual_footage_ft=220,
    actual_unit_cost_cents=4750,
    actual_rock_excavation=True,
    actual_crossings=[
        {"surface_type": "ASPHALT", "length_ft": 12.0, "width_ft": 3.0},
        {"surface_type": "ASPHALT", "length_ft": 8.0, "width_ft": 3.0},
        {"surface_type": "CONCRETE", "length_ft": 5.0, "width_ft": 3.0},
    ],
)
AS_BUILT_SMALLER = dict(
    actual_footage_ft=150,
    actual_unit_cost_cents=4500,
    actual_rock_excavation=False,
    actual_crossings=ONE_ASPHALT_CROSSING,
)
AS_BUILT_IDENTICAL = dict(
    actual_footage_ft=200,
    actual_unit_cost_cents=4500,
    actual_rock_excavation=False,
    actual_crossings=TWO_ASPHALT_CROSSINGS,
)


def _finalize(ctx, api, clerk_headers):
    return get_success_data(api.finalize_main_extension(ctx["me"]["id"], clerk_headers))


class TestFinalTrueUpDivergence:
    def test_final_variant_diverges_from_provisional(self, api, clerk_headers):
        """PRD §3.8: "the final net, `final_net_ciac_cents`, is that sum minus the same appliance-driven allowance priced at the standard 4,500 cents per foot, floored at zero; the `final_gross_up_cents` is again twenty-one seventy-ninths of the final net, rounded half up to whole cents; and the `final_total_due_cents` is their sum. The signed `ciac_delta_cents` is the final total minus the provisional total."

        Design: Difficulty/dual_variant_calc/ciac_provisional_vs_final_trueup_diverge
        """
        ctx = setup_as_built_recorded_app(
            loads=list(TWO_LOADS),
            design_footage_ft=200,
            crossings=TWO_ASPHALT_CROSSINGS,
            rock=False,
            payment_amount=322785,
            **AS_BUILT_LARGER,
        )
        finalized = _finalize(ctx, api, clerk_headers)
        assert finalized["status"] == "FINALIZED"
        assert finalized["provisional_total_due_cents"] == 322785, (
            "variant 1 (design inputs): 200 ft @ 4500, 2 crossings, no rock"
        )
        assert finalized["final_net_ciac_cents"] == 855000, (
            f"220x4750 + 3x15000 + 220x2000 - 150x4500 = 855000, "
            f"got {finalized['final_net_ciac_cents']}"
        )
        assert finalized["final_gross_up_cents"] == 227278
        assert finalized["final_total_due_cents"] == 1082278
        assert finalized["ciac_delta_cents"] == 759493, (
            "the same application prices out differently under the two variants"
        )

    def test_positive_delta_reopens_paid_invoice(self, api, clerk_headers):
        """PRD §3.8: "The invoice is then trued-up: an invoice already `PAID` reopens to `ISSUED` with `amount_due_cents` repriced to the final total when the delta is positive"
        PRD §3.3: "`balance_due_cents`, the amount due minus the payments applied."

        Design: Difficulty/dual_variant_calc/ciac_provisional_vs_final_trueup_diverge
        """
        ctx = setup_as_built_recorded_app(
            loads=list(TWO_LOADS),
            design_footage_ft=200,
            crossings=TWO_ASPHALT_CROSSINGS,
            rock=False,
            payment_amount=322785,
            **AS_BUILT_LARGER,
        )
        _finalize(ctx, api, clerk_headers)
        invoice = refresh_invoice(ctx["invoice"]["id"])
        assert invoice["status"] == "ISSUED", (
            f"delta +759493 reopens the PAID invoice, got {invoice['status']}"
        )
        assert invoice["amount_due_cents"] == 1082278
        assert invoice["balance_due_cents"] == 759493, (
            f"1082278 - 322785 = 759493 still owed, got {invoice['balance_due_cents']}"
        )
        assert invoice["payments_applied_cents"] == 322785, (
            "the true-up never erases recorded payments"
        )


class TestSettledInvoiceGate:
    def test_payment_on_settled_invoice_rejected_not_payable(self, api, clerk_c_headers):
        """PRD §3.3: "Payments are accepted only while the invoice is `ISSUED` or `PARTIALLY_PAID`; any other invoice status is rejected with `ERR_INVOICE_NOT_PAYABLE` (HTTP 409)."
        PRD §2.6: "7. **Entity state machine validity** — the target entity's current state must permit the requested transition, else `ERR_INVALID_STATE` or the more specific member of the state-gate family (`ERR_INVOICE_NOT_PAYABLE`, `ERR_INVOICE_NOT_REFUNDABLE`, `ERR_COMMITMENT_NOT_REVISABLE`, `ERR_SERVICE_LINE_NOT_INSTALLED`, `ERR_METER_NOT_READY`), all HTTP 409."
        PRD §2.6: "12. **Fiscal gates** — CIAC settlement state and payment/refund amount rules (`ERR_CIAC_UNPAID`, `ERR_OVERPAYMENT`, `ERR_REFUND_AMOUNT_MISMATCH`), guarding construction scheduling, application completion, payment recording, and refund recording."

        Design: Difficulty/priority_pair_validation_conflict/settled_invoice_payment_state_beats_overpay
        """
        ctx = setup_as_built_recorded_app(
            loads=list(TWO_LOADS),
            design_footage_ft=200,
            crossings=TWO_ASPHALT_CROSSINGS,
            rock=False,
            payment_amount=322785,
            **AS_BUILT_IDENTICAL,
        )
        _finalize(ctx, api, clerk_c_headers)
        invoice = refresh_invoice(ctx["invoice"]["id"])
        assert invoice["status"] == "SETTLED", "identical as-built means delta zero"
        assert invoice["balance_due_cents"] == 0

        # 1000 > balance 0 also trips the overpayment rule, but the state gate
        # (priority 7) precedes the fiscal gate (priority 12).
        resp = api.record_payment(
            ctx["invoice"]["id"], {"amount_cents": 1000, "method": "ACH"}, clerk_c_headers
        )
        validate_error(resp, ApiErrorId.ERR_INVOICE_NOT_PAYABLE, expected_status=409)

    def test_rejected_payment_leaves_no_trace(self, api, clerk_c_headers):
        """PRD §3.3: "Every recorded payment appends a payment event carrying the `ciac_invoice_id`, the `direction` `PAYMENT`, the amount, the method, and the clerk's identity as `recorded_by_user_id`."
        PRD §3.8: "and settles to `SETTLED` when the delta is exactly zero."

        Design: Difficulty/priority_pair_validation_conflict/settled_invoice_payment_state_beats_overpay
        """
        ctx = setup_as_built_recorded_app(
            loads=list(TWO_LOADS),
            design_footage_ft=200,
            crossings=TWO_ASPHALT_CROSSINGS,
            rock=False,
            payment_amount=322785,
            **AS_BUILT_IDENTICAL,
        )
        _finalize(ctx, api, clerk_c_headers)

        resp = api.record_payment(
            ctx["invoice"]["id"], {"amount_cents": 1000, "method": "ACH"}, clerk_c_headers
        )
        validate_error(resp, ApiErrorId.ERR_INVOICE_NOT_PAYABLE, expected_status=409)

        invoice = refresh_invoice(ctx["invoice"]["id"])
        assert invoice["status"] == "SETTLED"
        resp = api.list_ciac_payments(
            clerk_c_headers, params={"ciac_invoice_id": ctx["invoice"]["id"]}
        )
        _, meta = validate_paginated(resp)
        assert meta["total_count"] == 1, (
            "only the original full payment exists; the rejected attempt left no event"
        )


class TestRefundConservation:
    def test_negative_delta_moves_invoice_to_refund_pending(self, api, clerk_headers):
        """PRD §3.8: "moves to `REFUND_PENDING` with `refund_required_cents` set to the payments applied minus the final total — the negated delta — when the delta is negative"
        PRD §3.8: "the final net, `final_net_ciac_cents`, is that sum minus the same appliance-driven allowance priced at the standard 4,500 cents per foot, floored at zero; the `final_gross_up_cents` is again twenty-one seventy-ninths of the final net, rounded half up to whole cents; and the `final_total_due_cents` is their sum."

        Design: Difficulty/compensating_invariant/ciac_pay_finalize_refund_conserves_net_cash
        """
        ctx = setup_as_built_recorded_app(
            loads=list(TWO_LOADS),
            design_footage_ft=200,
            crossings=TWO_ASPHALT_CROSSINGS,
            rock=False,
            payment_amount=322785,
            **AS_BUILT_SMALLER,
        )
        finalized = _finalize(ctx, api, clerk_headers)
        assert finalized["final_net_ciac_cents"] == 15000
        assert finalized["final_gross_up_cents"] == 3987
        assert finalized["final_total_due_cents"] == 18987

        invoice = refresh_invoice(ctx["invoice"]["id"])
        assert invoice["status"] == "REFUND_PENDING"
        assert invoice["refund_required_cents"] == 303798, (
            f"322785 - 18987 = 303798, got {invoice['refund_required_cents']}"
        )

    def test_full_refund_conserves_net_cash(self, api, clerk_c_headers):
        """PRD §3.3: "Partial refunds are allowed: the invoice stays `REFUND_PENDING` until the issued refunds exactly equal the required refund, at which point it becomes `REFUNDED`."
        PRD §3.3: "it tracks `payments_applied_cents` — the running sum of every `PAYMENT` event — `refunds_issued_cents` — the running sum of every `REFUND` event"

        Design: Difficulty/compensating_invariant/ciac_pay_finalize_refund_conserves_net_cash
        """
        ctx = setup_as_built_recorded_app(
            loads=list(TWO_LOADS),
            design_footage_ft=200,
            crossings=TWO_ASPHALT_CROSSINGS,
            rock=False,
            payment_amount=322785,
            **AS_BUILT_SMALLER,
        )
        _finalize(ctx, api, clerk_c_headers)

        refund_invoice(ctx["invoice"]["id"], 303798, clerk_headers=clerk_c_headers)
        invoice = refresh_invoice(ctx["invoice"]["id"])
        assert invoice["status"] == "REFUNDED"
        assert invoice["payments_applied_cents"] == 322785
        assert invoice["refunds_issued_cents"] == 303798
        net_cash = invoice["payments_applied_cents"] - invoice["refunds_issued_cents"]
        me = refresh_main_extension(ctx["me"]["id"])
        assert net_cash == 18987 == invoice["amount_due_cents"] == me["final_total_due_cents"], (
            f"net cash {net_cash} must equal the final total with zero drift"
        )


class TestPaymentRecording:
    def test_payment_event_is_append_only(self, api, clerk_headers):
        """PRD §2.4: "One resource is deliberately exempt: a **CIAC payment event** is an append-only ledger entry. It carries `id` and `created_at` only — both `updated_at` and `version` are absent, because a payment or refund event, once recorded, is never modified."
        PRD §3.3: "Every recorded payment appends a payment event carrying the `ciac_invoice_id`, the `direction` `PAYMENT`, the amount, the method, and the clerk's identity as `recorded_by_user_id`."

        Design: Corner/entities/ciac_payment_immutable_event
        """
        ctx = setup_ciac_pending_app(
            design_footage_ft=200, crossings=ONE_ASPHALT_CROSSING, rock=False
        )
        resp = api.record_payment(
            ctx["invoice"]["id"], {"amount_cents": 100000, "method": "CARD"}, clerk_headers
        )
        event = validate_success(resp, expected_status=201)
        assert_ciac_payment(event)
        assert event["ciac_invoice_id"] == ctx["invoice"]["id"]
        assert event["direction"] == "PAYMENT"
        assert event["amount_cents"] == 100000
        assert event["method"] == "CARD"
        assert event["recorded_by_user_id"] == "clerk-b"

        invoice = refresh_invoice(ctx["invoice"]["id"])
        assert invoice["status"] == "PARTIALLY_PAID"
        assert invoice["balance_due_cents"] == 346203, (
            f"446203 - 100000 = 346203, got {invoice['balance_due_cents']}"
        )

    def test_payment_by_issuing_rep_rejected(self, api):
        """PRD §3.3: "the clerk's identity must differ from the invoice's `issued_by_user_id` — the rep who approved the design may not collect on their own quote, and the attempt is rejected with `ERR_SOD_PAYMENT_BY_ISSUER` (HTTP 422)"

        Design: Corner/errors/sod_payment_by_issuer_rejected
        """
        ctx = setup_ciac_pending_app(
            design_footage_ft=200, crossings=ONE_ASPHALT_CROSSING, rock=False
        )
        assert ctx["invoice"]["issued_by_user_id"] == "rep-1"
        issuer_as_clerk = build_user_headers("rep-1", "BillingClerk")
        resp = api.record_payment(
            ctx["invoice"]["id"], {"amount_cents": 446203, "method": "ACH"}, issuer_as_clerk
        )
        validate_error(resp, ApiErrorId.ERR_SOD_PAYMENT_BY_ISSUER, expected_status=422)

        invoice = refresh_invoice(ctx["invoice"]["id"])
        assert invoice["status"] == "ISSUED"
        assert invoice["payments_applied_cents"] == 0

    def test_overpayment_by_one_cent_rejected(self, api, clerk_headers):
        """PRD §3.3: "the amount must not exceed the current `balance_due_cents`, else `ERR_OVERPAYMENT` (HTTP 422)"

        Design: Corner/errors/overpayment_amount_rejected
        """
        ctx = setup_ciac_pending_app(
            design_footage_ft=200, crossings=ONE_ASPHALT_CROSSING, rock=False
        )
        assert ctx["invoice"]["amount_due_cents"] == 446203
        resp = api.record_payment(
            ctx["invoice"]["id"], {"amount_cents": 446204, "method": "CARD"}, clerk_headers
        )
        validate_error(resp, ApiErrorId.ERR_OVERPAYMENT, expected_status=422)

        invoice = refresh_invoice(ctx["invoice"]["id"])
        assert invoice["status"] == "ISSUED"
        assert invoice["payments_applied_cents"] == 0
        resp = api.list_ciac_payments(
            clerk_headers, params={"ciac_invoice_id": ctx["invoice"]["id"]}
        )
        _, meta = validate_paginated(resp)
        assert meta["total_count"] == 0, "a rejected payment appends no ledger event"

    def test_refund_on_issued_invoice_rejected(self, api, clerk_headers):
        """PRD §3.3: "While an invoice sits in `REFUND_PENDING` — and only then, else `ERR_INVOICE_NOT_REFUNDABLE` (HTTP 409) — a clerk records a refund against it."

        Design: Corner/errors/refund_on_issued_invoice_rejected
        """
        ctx = setup_ciac_pending_app(
            design_footage_ft=200, crossings=ONE_ASPHALT_CROSSING, rock=False
        )
        resp = api.record_refund(
            ctx["invoice"]["id"], {"amount_cents": 100, "method": "ACH"}, clerk_headers
        )
        validate_error(resp, ApiErrorId.ERR_INVOICE_NOT_REFUNDABLE, expected_status=409)


class TestRefundSegregation:
    def test_refund_by_payment_clerk_rejected(self, api, clerk_headers):
        """PRD §3.3: "The refunding clerk's identity must differ from the `recorded_by_user_id` of every posted payment on that invoice, else `ERR_SOD_REFUND_BY_PAYER` (HTTP 422)"

        Design: Corner/errors/sod_refund_by_payer_rejected
        """
        ctx = setup_as_built_recorded_app(
            loads=list(TWO_LOADS),
            design_footage_ft=200,
            crossings=TWO_ASPHALT_CROSSINGS,
            rock=False,
            payment_amount=322785,  # recorded by clerk-b via the default fixture clerk
            **AS_BUILT_SMALLER,
        )
        _finalize(ctx, api, clerk_headers)
        invoice = refresh_invoice(ctx["invoice"]["id"])
        assert invoice["status"] == "REFUND_PENDING"
        assert invoice["refund_required_cents"] == 303798

        resp = api.record_refund(
            ctx["invoice"]["id"], {"amount_cents": 303798, "method": "ACH"}, clerk_headers
        )
        validate_error(resp, ApiErrorId.ERR_SOD_REFUND_BY_PAYER, expected_status=422)

        invoice = refresh_invoice(ctx["invoice"]["id"])
        assert invoice["status"] == "REFUND_PENDING"
        assert invoice["refunds_issued_cents"] == 0

    def test_refund_above_remaining_rejected_then_exact_succeeds(self, api, clerk_c_headers):
        """PRD §3.3: "the amount must not exceed the still-outstanding refund — the `refund_required_cents` minus the `refunds_issued_cents` so far — else `ERR_REFUND_AMOUNT_MISMATCH` (HTTP 422). Partial refunds are allowed: the invoice stays `REFUND_PENDING` until the issued refunds exactly equal the required refund, at which point it becomes `REFUNDED`."

        Design: Corner/errors/refund_above_remaining_rejected
        """
        ctx = setup_as_built_recorded_app(
            loads=list(TWO_LOADS),
            design_footage_ft=200,
            crossings=TWO_ASPHALT_CROSSINGS,
            rock=False,
            payment_amount=322785,
            **AS_BUILT_SMALLER,
        )
        _finalize(ctx, api, clerk_c_headers)

        resp = api.record_refund(
            ctx["invoice"]["id"], {"amount_cents": 303799, "method": "ACH"}, clerk_c_headers
        )
        validate_error(resp, ApiErrorId.ERR_REFUND_AMOUNT_MISMATCH, expected_status=422)

        resp = api.record_refund(
            ctx["invoice"]["id"], {"amount_cents": 303798, "method": "ACH"}, clerk_c_headers
        )
        validate_success(resp, expected_status=201)
        invoice = refresh_invoice(ctx["invoice"]["id"])
        assert invoice["status"] == "REFUNDED"
        assert invoice["refunds_issued_cents"] == 303798


class TestImmediateConsistency:
    def test_full_payment_bubbles_application_immediately(self, api, clerk_headers, rep_headers):
        """PRD §3.3: "a payment exactly equal to the balance moves the invoice to `PAID`, and that event bubbles the application from `CIAC_PENDING` to `APPROVED_FOR_CONSTRUCTION`."

        Design: Corner/consistency_model/immediate_visibility_after_cascade
        """
        ctx = setup_ciac_pending_app(
            design_footage_ft=200, crossings=ONE_ASPHALT_CROSSING, rock=False
        )
        resp = api.record_payment(
            ctx["invoice"]["id"], {"amount_cents": 446203, "method": "ACH"}, clerk_headers
        )
        validate_success(resp, expected_status=201)

        invoice = refresh_invoice(ctx["invoice"]["id"])
        assert invoice["status"] == "PAID"
        assert invoice["balance_due_cents"] == 0
        app = refresh_application(ctx["app"]["id"])
        assert app["status"] == "APPROVED_FOR_CONSTRUCTION", (
            "the bubble-up commits in the same transaction as the payment"
        )
