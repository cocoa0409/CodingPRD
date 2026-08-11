"""Invoice lifecycle: finalize precondition, payment exactness, dispute/resolve
branch, OCC on finalize, credit balance reconciliation, and InvoiceLineItem
immutability contract.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    api_client,
    TEST_USERS,
    make_customer_headers,
    create_invoice_payload,
    create_customer,
    create_invoice,
    setup_active_subscription,
    setup_finalized_invoice,
    setup_paid_invoice,
    setup_completed_visit_with_report,
    assert_invoice_line_item,
)

OPS = TEST_USERS["ops_headers"]
BILLING = TEST_USERS["billing_headers"]


# =========================================================================
# Corner / endpoints / invoice_finalize_period_not_closed
# Corner / validations / record_payment_amount_mismatch
# Corner / state_machines / invoice_terminal_paid_lockdown
# Corner / cross_cutting_complexity_layers / occ_invoice_finalize_stale_version
# =========================================================================

class TestInvoiceFinalizeAndPayment:
    def test_finalize_rejected_when_period_not_closed(self, api):
        """PRD §2.9 item 17: "Invoice finalize requires `billing_period_end`
        to be at or before the current logical time — otherwise
        `ERR_PERIOD_NOT_CLOSED`."

        Design: Corner/endpoints/invoice_finalize_period_not_closed
        """
        customer = create_customer()
        api_client.set_current_utc("2026-05-15T00:00:00Z", OPS)
        invoice = create_invoice(
            customer["id"],
            billing_period_start="2026-06-01T00:00:00Z",
            billing_period_end="2026-07-01T00:00:00Z",
        )
        resp = api_client.finalize_invoice(
            invoice["id"], {"expected_invoice_version": invoice["version"]}, BILLING
        )
        validate_error(resp, ApiErrorId.ERR_PERIOD_NOT_CLOSED)

    def test_finalize_rejected_with_stale_expected_version(self, api):
        """PRD §2.7: "The second guarded endpoint is the finalize action on an
        `Invoice`. The request must carry `expected_invoice_version` matching
        the invoice's current `version`. If another writer has advanced the
        invoice's version since the client last read it — for example because
        a vacation-window application or a satisfaction resolution posted new
        line items onto this invoice in the interim — the finalize request is
        rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/occ_invoice_finalize_stale_version
        """
        customer = create_customer()
        api_client.set_current_utc("2026-06-01T00:00:00Z", OPS)
        invoice = create_invoice(customer["id"])
        # Deliberately use a stale version (current - 1).
        stale_version = invoice["version"] - 1
        resp = api_client.finalize_invoice(
            invoice["id"], {"expected_invoice_version": stale_version}, BILLING
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    def test_record_payment_rejected_on_amount_mismatch(self, api):
        """PRD §2.9 item 18: "Payment recording requires the submitted
        `amount_cents` to exactly equal the invoice's `total_due_cents` — no
        overpayment, no underpayment — otherwise
        `ERR_PAYMENT_AMOUNT_MISMATCH`."

        Design: Corner/validations/record_payment_amount_mismatch
        """
        customer, finalized = setup_finalized_invoice()
        # Any value != total_due_cents is rejected. total_due is 0 for an
        # empty invoice, so submit 9999 (a mismatch).
        resp = api_client.record_payment_invoice(
            finalized["id"], {"amount_cents": 9999}, BILLING
        )
        validate_error(resp, ApiErrorId.ERR_PAYMENT_AMOUNT_MISMATCH)

    def test_dispute_rejected_on_paid_invoice(self, api):
        """PRD §3.7: "A finalized invoice may be paid. The `BillingAdmin`
        records payment by supplying `amount_cents`, which must exactly equal
        `total_due_cents` — no overpayment, no underpayment — else
        `ERR_PAYMENT_AMOUNT_MISMATCH`. A successful payment moves the invoice
        to `PAID`. Alternatively, the `Customer` may dispute a finalized
        invoice by supplying a `reason`; the invoice moves to `DISPUTED`."
        Because the dispute branch is declared from FINALIZED only, a PAID
        invoice cannot be disputed — the transition is invalid from PAID.

        Design: Corner/state_machines/invoice_terminal_paid_lockdown
        """
        customer, paid = setup_paid_invoice()
        resp = api_client.dispute_invoice(
            paid["id"], {"reason": "too late"}, make_customer_headers(customer["id"])
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


# =========================================================================
# Difficulty / non_linear_state_machine / invoice_dispute_resolve_branching
# Difficulty / compensating_invariant / customer_credit_balance_invariant
# Corner / cross_cutting_complexity_layers / derived_field_reconciliation_credit_balance
# =========================================================================

class TestInvoiceDisputeResolveBranch:
    def _setup_disputed(self):
        customer, finalized = setup_finalized_invoice()
        dispute_resp = api_client.dispute_invoice(
            finalized["id"],
            {"reason": "missed visit charged"},
            make_customer_headers(customer["id"]),
        )
        disputed = get_success_data(dispute_resp)
        return customer, disputed

    def test_dispute_then_resolve_moves_invoice_to_resolved(self, api):
        """PRD §3.7: "the `Customer` may dispute a finalized invoice by
        supplying a `reason`; the invoice moves to `DISPUTED`. Dispute
        resolution is performed by a `BillingAdmin`, who supplies a
        `resolution_credit_cents` ... the invoice then moves to `RESOLVED`."

        Design: Difficulty/non_linear_state_machine/invoice_dispute_resolve_branching
        """
        customer, disputed = self._setup_disputed()
        resolve_resp = api_client.resolve_dispute_invoice(
            disputed["id"], {"resolution_credit_cents": 1500}, BILLING
        )
        resolved = validate_success(resolve_resp)
        assert resolved["invoice_status"] == "RESOLVED"

    def test_resolution_credit_posted_to_customer_balance(self, api):
        """PRD §3.7: "If the resolution credit is positive, a
        `SATISFACTION_CREDIT` line is posted to the next `OPEN` invoice —
        creating one if none exists — and the customer's
        `credit_balance_cents` is increased by the resolution amount"

        Design: Difficulty/compensating_invariant/customer_credit_balance_invariant
        """
        customer, disputed = self._setup_disputed()
        api_client.resolve_dispute_invoice(
            disputed["id"], {"resolution_credit_cents": 1500}, BILLING
        )
        get_resp = api_client.get_customer(customer["id"], BILLING)
        data = validate_success(get_resp)
        assert data["credit_balance_cents"] == 1500

    def test_credit_balance_zero_before_resolve_then_nonzero_after(self, api):
        """PRD §3.1: "The resulting `Customer` record starts with
        `account_status` set to `ACTIVE`, a `credit_balance_cents` of 0"
        combined with PRD §3.7: "the customer's `credit_balance_cents` is
        increased by the resolution amount".

        Design: Difficulty/compensating_invariant/customer_credit_balance_invariant
        """
        customer, disputed = self._setup_disputed()
        # Pre-resolve: customer has zero credit.
        pre = validate_success(api_client.get_customer(customer["id"], BILLING))
        assert pre["credit_balance_cents"] == 0
        api_client.resolve_dispute_invoice(
            disputed["id"], {"resolution_credit_cents": 1500}, BILLING
        )
        post = validate_success(api_client.get_customer(customer["id"], BILLING))
        assert post["credit_balance_cents"] == 1500

    def test_invoice_goes_to_resolved_not_paid_when_dispute_path_taken(self, api):
        """PRD §3.7: "the `Customer` may dispute a finalized invoice by
        supplying a `reason`; the invoice moves to `DISPUTED`. Dispute
        resolution is performed by a `BillingAdmin` ... the invoice then
        moves to `RESOLVED`."

        Design: Difficulty/non_linear_state_machine/invoice_dispute_resolve_branching
        """
        customer, disputed = self._setup_disputed()
        api_client.resolve_dispute_invoice(
            disputed["id"], {"resolution_credit_cents": 1500}, BILLING
        )
        get_resp = api_client.get_invoice(disputed["id"], BILLING)
        data = validate_success(get_resp)
        # Final state after dispute+resolve is RESOLVED, not PAID.
        assert data["invoice_status"] == "RESOLVED"
        assert data["invoice_status"] != "PAID"


class TestCreditBalanceReconciliation:
    def test_satisfaction_resolve_credits_customer_balance(self, api):
        """PRD §3.8: "resolution stamps `resolved_at` with the current logical
        time, writes the credit onto the report, adds the credit to the
        customer's `credit_balance_cents`, and recomputes the customer's
        `satisfaction_rolling_avg`."

        Design: Corner/cross_cutting_complexity_layers/derived_field_reconciliation_credit_balance
        """
        customer, visit, report = setup_completed_visit_with_report(
            rating=2, issue_category="MISSED_SPOT", report_in_review=True
        )
        api_client.resolve_satisfaction_report(
            report["id"], {"resolution_credit_cents": 750}, OPS
        )
        get_resp = api_client.get_customer(customer["id"], OPS)
        data = validate_success(get_resp)
        assert data["credit_balance_cents"] == 750


# =========================================================================
# Corner / validations / resolution_credit_out_of_range
# =========================================================================

class TestResolutionCreditRange:
    def test_credit_above_max_rejected(self, api):
        """PRD §2.9 item 19: "A satisfaction resolution credit must be at
        least 0 and at most 100000 cents (a $1000 cap on any single
        resolution) — otherwise `ERR_CREDIT_OUT_OF_RANGE`."

        Design: Corner/validations/resolution_credit_out_of_range
        """
        customer, visit, report = setup_completed_visit_with_report(
            rating=2, issue_category="LATE_ARRIVAL", report_in_review=True
        )
        resp = api_client.resolve_satisfaction_report(
            report["id"], {"resolution_credit_cents": 100001}, OPS
        )
        validate_error(resp, ApiErrorId.ERR_CREDIT_OUT_OF_RANGE)


# =========================================================================
# Corner / entities / invoice_line_item_immutable_common_fields
# =========================================================================

class TestInvoiceLineItemShape:
    def test_line_item_omits_updated_at_and_version(self, api):
        """PRD §2.4: "The one exception to the common-field rule is
        `InvoiceLineItem`, which carries only `id` and `created_at`;
        `InvoiceLineItem` does not have `updated_at` and does not have
        `version`, because line items are immutable once written onto an
        invoice."

        Design: Corner/entities/invoice_line_item_immutable_common_fields
        """
        # Build a completed visit under an OPEN invoice covering the visit's
        # scheduled_date. The completion posts a VISIT_CHARGE line item
        # (PRD §3.7: "each completed visit generates a `VISIT_CHARGE` line").
        customer, yard, profile, plan, subscription = setup_active_subscription(
            clock_iso="2026-05-01T00:00:00Z"
        )
        invoice = create_invoice(customer["id"])  # OPEN, covering May 2026
        from test_helpers import (
            create_technician,
            create_service_route,
            create_scheduled_visit,
            make_technician_headers,
        )

        technician = create_technician()
        route = create_service_route(
            service_date="2026-05-04T00:00:00Z",
            assigned_technician_id=technician["id"],
            max_visit_capacity=5,
        )
        visit = create_scheduled_visit(
            subscription["id"],
            route_id=route["id"],
            scheduled_date="2026-05-04T00:00:00Z",
            scheduled_window_start="2026-05-04T09:00:00Z",
            scheduled_window_end="2026-05-04T10:00:00Z",
        )
        api_client.publish_service_route(route["id"], OPS)
        api_client.set_current_utc("2026-05-04T08:00:00Z", OPS)
        api_client.start_service_route(route["id"], make_technician_headers(technician["id"]))
        api_client.depart_visit(visit["id"], make_technician_headers(technician["id"]))
        api_client.arrive_visit(visit["id"], make_technician_headers(technician["id"]))
        api_client.complete_visit(visit["id"], make_technician_headers(technician["id"]))
        items_resp = api_client.get_invoice_line_items(invoice["id"], BILLING)
        items = validate_success(items_resp)
        assert len(items) >= 1, "Completing a visit should post at least one line item"
        for line in items:
            assert_invoice_line_item(line)
