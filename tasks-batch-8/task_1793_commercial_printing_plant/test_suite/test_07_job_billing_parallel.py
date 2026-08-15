"""Job billing dimension evolving in parallel with production status, and
customer exposure reconciliation on invoice issue and payments."""
from test_helpers import (
    TEST_USERS,
    create_customer,
    create_fulfilled_ship_job,
    create_issued_invoice,
    create_received_stock,
    get_success_data,
    make_customer_headers,
    minimal_signature,
    standard_signatures,
    validate_success,
)

_PM = TEST_USERS["plant_manager_headers"]


class TestParallelBillingDimension:
    def _fulfilled_issued(self):
        cust = create_customer(name="Par Cust")
        stock, _po = create_received_stock(name="80G", cost_per_sheet_cents=9, sheets=50000)
        _est, job, inv, _press = create_issued_invoice(
            cust["id"], standard_signatures(stock["id"]),
            quantity_ordered=10002, delivered_quantity=10502,
            press_spoilage_pct=3, bindery_spoilage_pct=2,
            finishing_options=["PERF", "SCORE"], included_proof_rounds=2,
        )
        return cust, job, inv

    def test_dispute_moves_billing_side_only(self, api):
        """PRD §3.15: "The `billing_status` dimension evolves in parallel";
        PRD §3.13: "Disputing moves the invoice `ISSUED → DISPUTED` and bumps
        its `version`; a disputed invoice remains payable." Meanwhile PRD
        §2.8: "when an invoice reaches `PAID`, the job's `billing_status`
        moves to `SETTLED`, and if the job has already been `FULFILLED`, its
        `production_status` simultaneously moves to `CLOSED`" — only that
        billing event closes the job, so production stays FULFILLED through a
        dispute.

        Design: Difficulty/non_linear_state_machine/job_parallel_billing_dimension
        """
        cust, job, inv = self._fulfilled_issued()
        resp = api.dispute_invoice(inv["id"], {"reason": "color complaint"},
                                   make_customer_headers(cust["id"]))
        validate_success(resp, 200)
        inv_after = get_success_data(api.get_invoice(inv["id"], _PM))
        job_after = get_success_data(api.get_job(job["id"], _PM))
        assert inv_after["status"] == "DISPUTED"
        assert job_after["production_status"] == "FULFILLED"
        assert job_after["billing_status"] == "INVOICED"

    def test_payment_from_disputed_settles_and_closes(self, api):
        """PRD §3.13: "a disputed invoice remains payable — both partial and
        exact payments apply from `DISPUTED` as they do from `ISSUED`, with
        the same cascades"; "A payment covering the exact outstanding amount
        moves the invoice to `PAID`, which cascades: the job's
        `billing_status` becomes `SETTLED`, and if the job's
        `production_status` is `FULFILLED`, the job closes to `CLOSED`."

        Design: Difficulty/non_linear_state_machine/job_parallel_billing_dimension
        """
        cust, job, inv = self._fulfilled_issued()
        api.dispute_invoice(inv["id"], {"reason": "color complaint"},
                            make_customer_headers(cust["id"]))
        resp = api.pay_invoice(inv["id"], {"amount_cents": 811923}, _PM)
        validate_success(resp, 201)
        inv_after = get_success_data(api.get_invoice(inv["id"], _PM))
        job_after = get_success_data(api.get_job(job["id"], _PM))
        assert inv_after["status"] == "PAID"
        assert job_after["billing_status"] == "SETTLED"
        assert job_after["production_status"] == "CLOSED"


class TestExposureComponentSwapOnIssue:
    def test_customer_exposure_component_swap_on_issue(self, api):
        """PRD §3.1: "The `exposure_cents` is the sum of
        `amount_outstanding_cents` across all of the customer's invoices in
        `ISSUED`, `PARTIALLY_PAID`, or `DISPUTED` status, plus the sum of
        `total_price_cents` across the customer's jobs whose `billing_status`
        is `UNBILLED` and whose `production_status` is neither `CLOSED` nor
        `CANCELLED`." Before issue the UNBILLED job contributes 773267; after
        issue the ISSUED invoice's 811923 replaces it — no double counting.

        Design: Corner/calculations/customer_exposure_component_swap_on_issue
        """
        cust = create_customer(name="EX Cust")
        stock, _po = create_received_stock(name="80G", cost_per_sheet_cents=9, sheets=50000)
        _est, job, _press = create_fulfilled_ship_job(
            cust["id"], standard_signatures(stock["id"]),
            quantity_ordered=10002, delivered_quantity=10502,
            press_spoilage_pct=3, bindery_spoilage_pct=2,
            finishing_options=["PERF", "SCORE"], included_proof_rounds=2,
        )
        inv = get_success_data(api.create_invoice({"job_id": job["id"]}, _PM))
        before = get_success_data(api.get_customer(cust["id"], _PM))
        assert before["exposure_cents"] == 773267, (
            f"UNBILLED job contributes its total 773267, got {before['exposure_cents']}"
        )
        api.issue_invoice(inv["id"], _PM)
        after = get_success_data(api.get_customer(cust["id"], _PM))
        assert after["exposure_cents"] == 811923, (
            f"after issue the invoice outstanding 811923 replaces the job component, got {after['exposure_cents']}"
        )
        job_after = get_success_data(api.get_job(job["id"], _PM))
        assert job_after["billing_status"] == "INVOICED"


class TestPaymentReconcilesExposure:
    def test_exposure_after_partial_payment(self, api):
        """PRD §3.13: "A partial payment — one strictly below the outstanding
        amount — moves the invoice to `PARTIALLY_PAID`, increments
        `amount_paid_cents` by the payment, recomputes
        `amount_outstanding_cents`, and recomputes the customer's exposure and
        posture." Exposure walks 85000 -> 35000 across a 50000 payment.

        Design: Corner/cross_cutting_layers/invoice_payment_reconciles_exposure
        """
        cust = create_customer(name="DR Cust")
        stock, _po = create_received_stock(name="70U", grade="UNCOATED",
                                           cost_per_sheet_cents=5, sheets=5000)
        _est, job, inv, _press = create_issued_invoice(
            cust["id"], minimal_signature(stock["id"]),
            quantity_ordered=1000, delivered_quantity=1000,
        )
        c1 = get_success_data(api.get_customer(cust["id"], _PM))
        assert c1["exposure_cents"] == 85000
        api.pay_invoice(inv["id"], {"amount_cents": 50000}, _PM)
        c2 = get_success_data(api.get_customer(cust["id"], _PM))
        inv2 = get_success_data(api.get_invoice(inv["id"], _PM))
        assert c2["exposure_cents"] == 35000
        assert inv2["status"] == "PARTIALLY_PAID"

    def test_final_payment_settles_and_closes(self, api):
        """PRD §3.13: "The `SETTLED` billing transition is evaluated on every
        payment or credit application, so the cascade fires the moment the
        last open invoice of a job reaches `PAID`." A final 35000 payment
        drops exposure to 0, pays the invoice, and closes the FULFILLED job.

        Design: Corner/cross_cutting_layers/invoice_payment_reconciles_exposure
        """
        cust = create_customer(name="DR2 Cust")
        stock, _po = create_received_stock(name="70U", grade="UNCOATED",
                                           cost_per_sheet_cents=5, sheets=5000)
        _est, job, inv, _press = create_issued_invoice(
            cust["id"], minimal_signature(stock["id"]),
            quantity_ordered=1000, delivered_quantity=1000,
        )
        api.pay_invoice(inv["id"], {"amount_cents": 50000}, _PM)
        api.pay_invoice(inv["id"], {"amount_cents": 35000}, _PM)
        c3 = get_success_data(api.get_customer(cust["id"], _PM))
        inv3 = get_success_data(api.get_invoice(inv["id"], _PM))
        job3 = get_success_data(api.get_job(job["id"], _PM))
        assert c3["exposure_cents"] == 0
        assert inv3["status"] == "PAID"
        assert job3["billing_status"] == "SETTLED"
        assert job3["production_status"] == "CLOSED"
