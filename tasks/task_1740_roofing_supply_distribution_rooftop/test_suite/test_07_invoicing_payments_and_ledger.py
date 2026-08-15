"""Invoicing moves the hold into the open balance; payments age oldest-first."""
from test_helpers import (
    TEST_USERS,
    api_client,
    get_success_data,
    setup_delivered_order,
    setup_invoiced_order,
    validate_success,
)

CREDIT = TEST_USERS["credit_analyst_headers"]


class TestCreditLedgerConservedAcrossInvoice:
    def _delivered_ctx(self):
        return setup_delivered_order(branch_code="BR-I2", sku="SH-I2",
                                     price=2000, roof_squares=10.0,
                                     on_hand=500, lot_code="LOT-I2",
                                     slot_date="2026-08-16",
                                     company_name="Ledger Co")

    def test_invoice_moves_total_from_hold_to_open_balance(self, api):
        """PRD §3.7: "Invoicing settles the provisional into the real: the
        order's `total_cents` is subtracted from the account's
        `pending_delivery_hold_cents` and added to its `open_balance_cents`,
        and the same amount is added to the job account's `job_balance_cents`."

        30 bundles * 2000 = 60000 subtotal + 8500 ground fee = 68500 total.

        Design: Difficulty/compensating_invariant/credit_ledger_conserved_across_invoice_posting
        """
        ctx = self._delivered_ctx()
        account_id = ctx["account"]["id"]
        before = get_success_data(
            api_client.get_contractor_account(account_id, CREDIT))
        assert before["pending_delivery_hold_cents"] == 68500
        assert before["open_balance_cents"] == 0

        invoiced = validate_success(
            api_client.invoice_order(ctx["order"]["id"], CREDIT))
        assert invoiced["payment_status"] == "INVOICED"
        after = get_success_data(
            api_client.get_contractor_account(account_id, CREDIT))
        assert after["open_balance_cents"] == ctx["order"]["total_cents"]
        assert after["pending_delivery_hold_cents"] == 0

    def test_invoice_conserves_ledger_sum_and_ages_the_job(self, api):
        """PRD §3.7: "the order's `total_cents` is subtracted from the
        account's `pending_delivery_hold_cents` and added to its
        `open_balance_cents`, and the same amount is added to the job
        account's `job_balance_cents`."

        open + pending after the invoice equals pending before it — the
        invoice only re-labels the same 68500 obligation.

        Design: Difficulty/compensating_invariant/credit_ledger_conserved_across_invoice_posting
        """
        ctx = self._delivered_ctx()
        account_id = ctx["account"]["id"]
        before = get_success_data(
            api_client.get_contractor_account(account_id, CREDIT))
        pending_before = before["pending_delivery_hold_cents"]
        get_success_data(api_client.invoice_order(ctx["order"]["id"], CREDIT))
        after = get_success_data(
            api_client.get_contractor_account(account_id, CREDIT))
        assert (after["open_balance_cents"]
                + after["pending_delivery_hold_cents"]) == pending_before
        job = get_success_data(
            api_client.get_job_account(ctx["job"]["id"], CREDIT))
        assert job["job_balance_cents"] == 68500


class TestInvoiceAndPaymentSideEffects:
    def test_invoice_transitions_payment_status_and_job_balance(self, api):
        """PRD §3.7: "Once an order has been delivered, a `CreditAnalyst`
        posts the invoice, moving the order's `payment_status` from `UNPAID`
        to `INVOICED`."
        PRD §3.7: "the same amount is added to the job account's
        `job_balance_cents`."

        15 bundles * 2000 = 30000 + 8500 ground fee = 38500 onto the job.

        Design: Corner/endpoints/invoice_transitions_payment_status
        """
        ctx = setup_invoiced_order(branch_code="BR-EP4", sku="SH-EP4",
                                   roof_squares=5.0, lot_code="LOT-EP4",
                                   slot_date="2026-08-16",
                                   company_name="EP4 Co")
        assert ctx["order"]["payment_status"] == "INVOICED"
        assert ctx["job"]["job_balance_cents"] == 38500

    def test_payment_covering_invoice_flips_status_paid(self, api):
        """PRD §3.7: "it walks the oldest-first order, reduces the account's
        `open_balance_cents` by the amount (floored at zero), flips each
        affected order's `payment_status` to `PAID` when its invoice is fully
        covered, and reports back the `applied_to_order_ids` it touched along
        with the resulting `new_open_balance_cents`."

        A 38500-cent payment exactly covers the 38500-cent invoice.

        Design: Corner/state_machines/payment_covers_invoice_flips_payment_status_paid
        """
        ctx = setup_invoiced_order(branch_code="BR-SM7", sku="SH-SM7",
                                   roof_squares=5.0, lot_code="LOT-SM7",
                                   company_name="SM7 Co")
        total = ctx["order"]["total_cents"]
        assert total == 38500
        payment = validate_success(api_client.post_payment(
            ctx["account"]["id"],
            {"amount_cents": total, "job_account_id": ctx["job"]["id"]},
            CREDIT), expected_status=201)
        assert ctx["order"]["id"] in payment["applied_to_order_ids"]
        assert payment["new_open_balance_cents"] == 0
        order = get_success_data(
            api_client.get_order(ctx["order"]["id"], CREDIT))
        assert order["payment_status"] == "PAID"
        account = get_success_data(
            api_client.get_contractor_account(ctx["account"]["id"], CREDIT))
        assert account["open_balance_cents"] == 0

    def test_payment_applies_to_oldest_invoice_first(self, api):
        """PRD §3.7: "When a contractor owes on several invoices, payments
        apply to the oldest unpaid invoice first, ordered by `created_at`
        ascending, and `job_balance_cents` is simply the running sum of unpaid
        invoice totals attributed to that job."

        Two invoiced orders of 38500 each (open 77000); a 38500 payment
        settles the first and leaves the second INVOICED.

        Design: Corner/calculations/job_account_aging_oldest_invoice_first
        """
        first = setup_invoiced_order(branch_code="BR-CA6", sku="SH-CA6",
                                     roof_squares=5.0, lot_code="LOT-CA6",
                                     slot_date="2026-08-16",
                                     company_name="Calc6 Co")
        account = first["account"]
        job = first["job"]
        # Second order on the same job, driven through the same lifecycle.
        from test_helpers import (
            confirm_order,
            convert_to_order,
            create_quoted_takeoff,
            dispatch_and_complete,
            schedule_delivery,
        )
        takeoff_b = create_quoted_takeoff(job["id"], first["product"]["id"],
                                          5.0, 0, 0)
        order_b = convert_to_order(takeoff_b["id"], first["branch"]["id"],
                                   account["id"])
        confirm_order(order_b["id"], account["id"])
        _slot, delivery_b = schedule_delivery(
            order_b["id"], first["branch"]["id"], slot_date="2026-08-16",
            equipment_type="GROUND", capacity=5)
        dispatch_and_complete(delivery_b["id"])
        get_success_data(api_client.invoice_order(order_b["id"], CREDIT))

        account = get_success_data(
            api_client.get_contractor_account(account["id"], CREDIT))
        assert account["open_balance_cents"] == 77000
        validate_success(api_client.post_payment(
            account["id"], {"amount_cents": 38500, "job_account_id": job["id"]},
            CREDIT), expected_status=201)
        order_a_after = get_success_data(
            api_client.get_order(first["order"]["id"], CREDIT))
        order_b_after = get_success_data(
            api_client.get_order(order_b["id"], CREDIT))
        assert order_a_after["payment_status"] == "PAID"
        assert order_b_after["payment_status"] == "INVOICED"
        account = get_success_data(
            api_client.get_contractor_account(account["id"], CREDIT))
        assert account["open_balance_cents"] == 38500
