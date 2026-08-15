"""Payment waterfall, overpayment credit, partial payments, and reversals."""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_payment,
    create_payment_payload,
    get_success_data,
    pay_invoice,
    set_clock,
    setup_billed_invoice,
    validate_error,
)
from test_helpers.constants import CLOCK_DUE_PLUS_10D
from test_helpers.fixtures import CLERK, TREASURER

EARLY_DUE = "2026-08-10T00:00:00Z"


class TestPaymentWaterfall:
    def test_overpayment_flows_to_member_credit(self, api):
        """PRD section 3.7: "the portion applied is the smaller of `amount_cents`
        and the remaining outstanding, recorded as the payment's `applied_cents`;
        any remainder of the tender flows into the member's
        `credit_balance_cents` as overpayment." Tender 5000 against a 3950 invoice
        applies 3950 and credits 1050.

        Design: Corner/calculations/payment_waterfall_overpay_to_credit
        """
        ctx = setup_billed_invoice(usage_gallons=2001)  # total 3950
        district = ctx["district"]
        member = ctx["member"]
        invoice = ctx["invoice"]
        assert invoice["total_cents"] == 3950

        payment = pay_invoice(district["id"], member["id"], invoice["id"], 5000)
        assert_payment(payment)
        assert payment["applied_cents"] == 3950
        assert payment["status"] == "POSTED"

        after_invoice = get_success_data(api.get_invoice(district["id"], invoice["id"], TREASURER))
        assert after_invoice["billing_status"] == "PAID"
        assert after_invoice["amount_paid_cents"] == 3950
        after_member = get_success_data(api.get_member(district["id"], member["id"], TREASURER))
        assert after_member["credit_balance_cents"] == 1050


class TestParallelDimensionsCure:
    def _setup_noticed_invoice(self, api):
        """Invoice 4850 aged 10 days past due and NOTICED via issue-notice."""
        ctx = setup_billed_invoice(usage_gallons=4300, due_date_utc=EARLY_DUE)
        district = ctx["district"]
        invoice = ctx["invoice"]
        assert invoice["total_cents"] == 4850
        set_clock(CLOCK_DUE_PLUS_10D)
        noticed = get_success_data(api.issue_notice(district["id"], invoice["id"], CLERK))
        assert noticed["collection_status"] == "NOTICED"
        return ctx

    def test_partial_payment_moves_billing_but_not_collection(self, api):
        """PRD section 3.7: "A partial application moves `ISSUED → PARTIALLY_PAID`"
        while PRD section 3.6 ties the cure to full payment: "Paying an invoice in
        full always returns its collection status to `CURRENT`". A partial payment
        on a NOTICED invoice therefore leaves collection NOTICED.

        Design: Difficulty/non_linear_state_machine/invoice_parallel_dimensions_cure_cycle
        """
        ctx = self._setup_noticed_invoice(api)
        district = ctx["district"]
        invoice = ctx["invoice"]
        payment = pay_invoice(district["id"], ctx["member"]["id"], invoice["id"], 2000)
        assert payment["applied_cents"] == 2000
        after = get_success_data(api.get_invoice(district["id"], invoice["id"], TREASURER))
        assert after["billing_status"] == "PARTIALLY_PAID"
        assert after["collection_status"] == "NOTICED", (
            "A partial payment must not cure the collection dimension"
        )
        assert after["amount_paid_cents"] == 2000

    def test_full_payment_cures_collection_to_current(self, api):
        """PRD section 3.6: "Paying an invoice in full always returns its
        collection status to `CURRENT` from `DELINQUENT`, `NOTICED`,
        `DISCONNECT_ELIGIBLE`, or `DISCONNECTED`." PRD section 3.7: "covering the
        full outstanding moves `ISSUED → PAID` or `PARTIALLY_PAID → PAID`".

        Design: Difficulty/non_linear_state_machine/invoice_parallel_dimensions_cure_cycle
        """
        ctx = self._setup_noticed_invoice(api)
        district = ctx["district"]
        member = ctx["member"]
        invoice = ctx["invoice"]
        pay_invoice(district["id"], member["id"], invoice["id"], 2000)
        pay_invoice(district["id"], member["id"], invoice["id"], 2850)
        after = get_success_data(api.get_invoice(district["id"], invoice["id"], TREASURER))
        assert after["billing_status"] == "PAID"
        assert after["collection_status"] == "CURRENT"
        assert after["amount_paid_cents"] == 4850


class TestPaymentReversal:
    def test_reversal_conserves_invoice_and_credit_state(self, api):
        """PRD section 3.7: "reversal moves the payment `POSTED → REVERSED` (a
        payment already reversed rejects with `ERR_PAYMENT_ALREADY_REVERSED`,
        HTTP 409), debits the applied amount back off the invoice, debits any
        credit portion back off the member, and recomputes the invoice's billing
        status from what remains." Paying 5000 against 4850 then reversing restores
        amount_paid 0 and credit 0 — the conserved pair shows no drift.

        Design: Difficulty/compensating_invariant/payment_reverse_conserves_invoice_outstanding
        """
        ctx = setup_billed_invoice(usage_gallons=4300)  # total 4850, no credit
        district = ctx["district"]
        member = ctx["member"]
        invoice = ctx["invoice"]

        payment = pay_invoice(district["id"], member["id"], invoice["id"], 5000)
        assert payment["applied_cents"] == 4850
        mid_member = get_success_data(api.get_member(district["id"], member["id"], TREASURER))
        assert mid_member["credit_balance_cents"] == 150

        reversed_payment = get_success_data(
            api.reverse_payment(district["id"], payment["id"], TREASURER)
        )
        assert reversed_payment["status"] == "REVERSED"
        after_invoice = get_success_data(api.get_invoice(district["id"], invoice["id"], TREASURER))
        assert after_invoice["amount_paid_cents"] == 0
        assert after_invoice["billing_status"] == "ISSUED"
        assert after_invoice["collection_status"] == "CURRENT"
        after_member = get_success_data(api.get_member(district["id"], member["id"], TREASURER))
        assert after_member["credit_balance_cents"] == 0, "Reversal must debit the overpay credit back"

    def test_reversal_of_partial_and_double_reversal_rejected(self, api):
        """PRD section 3.7: "reversal moves the payment `POSTED → REVERSED` (a
        payment already reversed rejects with `ERR_PAYMENT_ALREADY_REVERSED`,
        HTTP 409), debits the applied amount back off the invoice, debits any
        credit portion back off the member, and recomputes the invoice's billing
        status from what remains."

        Design: Difficulty/compensating_invariant/payment_reverse_conserves_invoice_outstanding
        """
        ctx = setup_billed_invoice(usage_gallons=4300)
        district = ctx["district"]
        invoice = ctx["invoice"]
        payment = pay_invoice(district["id"], ctx["member"]["id"], invoice["id"], 2000)
        assert payment["applied_cents"] == 2000

        get_success_data(api.reverse_payment(district["id"], payment["id"], TREASURER))
        after = get_success_data(api.get_invoice(district["id"], invoice["id"], TREASURER))
        assert after["amount_paid_cents"] == 0
        assert after["billing_status"] == "ISSUED"

        resp = api.reverse_payment(district["id"], payment["id"], TREASURER)
        validate_error(resp, ApiErrorId.ERR_PAYMENT_ALREADY_REVERSED, expected_status=409)
