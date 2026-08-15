"""Invoice lifecycle error battery: DRAFT payment, duplicate generation,
overpayment, invalid credit application, double dispute, pay-after-PAID."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_customer,
    create_fulfilled_ship_job,
    create_received_stock,
    get_success_data,
    make_customer_headers,
    minimal_signature,
    validate_error,
    validate_paginated,
    validate_success,
)

_PM = TEST_USERS["plant_manager_headers"]


def _fulfilled_job():
    cust = create_customer(name="IB Cust")
    stock, _po = create_received_stock(name="70U", grade="UNCOATED",
                                       cost_per_sheet_cents=5, sheets=5000)
    _est, job, _press = create_fulfilled_ship_job(
        cust["id"], minimal_signature(stock["id"], make_ready_cents=50000),
        quantity_ordered=1000, delivered_quantity=1000,
    )
    return cust, job


class TestInvoiceLifecycleErrors:
    def test_pay_draft_invoice_rejected(self, api):
        """PRD §3.12: "Invoice operations attempted from a state that does not
        support them — paying a `DRAFT` invoice, disputing a `PAID` invoice,
        issuing an already-issued invoice — are rejected with
        `ERR_INVOICE_STATE`."

        Design: Corner/errors/invoice_lifecycle_error_battery
        """
        _cust, job = _fulfilled_job()
        inv = get_success_data(api.create_invoice({"job_id": job["id"]}, _PM))
        resp = api.pay_invoice(inv["id"], {"amount_cents": 1}, _PM)
        validate_error(resp, ApiErrorId.ERR_INVOICE_STATE)

    def test_duplicate_production_invoice_rejected(self, api):
        """PRD §3.12: "a job may carry only one production invoice —
        generating a second is rejected with `ERR_DUPLICATE_INVOICE`." The
        first invoice is left in DRAFT so the job remains UNBILLED and the
        duplicate rule is the only precondition that fails (§2.7 orders the
        UNBILLED state gate ahead of the duplicate check but names no error
        code for it at generation time).

        Design: Corner/errors/invoice_lifecycle_error_battery
        """
        _cust, job = _fulfilled_job()
        inv = get_success_data(api.create_invoice({"job_id": job["id"]}, _PM))
        assert inv["status"] == "DRAFT"
        resp = api.create_invoice({"job_id": job["id"]}, _PM)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_INVOICE)

    def test_overpayment_by_one_cent_rejected(self, api):
        """PRD §3.13: "The payment amount must be at least 1 and at most the
        invoice's `amount_outstanding_cents`; a payment outside that range is
        rejected with `ERR_OVERPAYMENT` (HTTP 422)." 85001 > 85000.

        Design: Corner/errors/invoice_lifecycle_error_battery
        """
        _cust, job = _fulfilled_job()
        inv = get_success_data(api.create_invoice({"job_id": job["id"]}, _PM))
        api.issue_invoice(inv["id"], _PM)
        resp = api.pay_invoice(inv["id"], {"amount_cents": 85001}, _PM)
        validate_error(resp, ApiErrorId.ERR_OVERPAYMENT)

    def test_apply_credit_without_balance_rejected(self, api):
        """PRD §3.13: "The amount may not exceed the smaller of the customer's
        `reprint_credit_balance_cents` and the invoice's
        `amount_outstanding_cents`; violating that bound is rejected with
        `ERR_CREDIT_APPLICATION_INVALID` (HTTP 422)." Balance 0 makes any
        positive amount a violation.

        Design: Corner/errors/invoice_lifecycle_error_battery
        """
        _cust, job = _fulfilled_job()
        inv = get_success_data(api.create_invoice({"job_id": job["id"]}, _PM))
        api.issue_invoice(inv["id"], _PM)
        resp = api.apply_credit(inv["id"], {"amount_cents": 1}, _PM)
        validate_error(resp, ApiErrorId.ERR_CREDIT_APPLICATION_INVALID)

    def test_double_dispute_rejected(self, api):
        """PRD §3.12: "Invoice operations attempted from a state that does not
        support them — paying a `DRAFT` invoice, disputing a `PAID` invoice,
        issuing an already-issued invoice — are rejected with
        `ERR_INVOICE_STATE`." §3.13 defines dispute as `ISSUED → DISPUTED`
        only, so a second dispute from DISPUTED is such an operation.

        Design: Corner/errors/invoice_lifecycle_error_battery
        """
        cust, job = _fulfilled_job()
        inv = get_success_data(api.create_invoice({"job_id": job["id"]}, _PM))
        api.issue_invoice(inv["id"], _PM)
        r1 = api.dispute_invoice(inv["id"], {"reason": "quality"},
                                 make_customer_headers(cust["id"]))
        validate_success(r1, 200)
        r2 = api.dispute_invoice(inv["id"], {"reason": "again"}, _PM)
        validate_error(r2, ApiErrorId.ERR_INVOICE_STATE)

    def test_pay_after_paid_rejected_and_conservation_holds(self, api):
        """PRD §3.13: "A payment covering the exact outstanding amount moves
        the invoice to `PAID`"; PRD §3.12: PAID is terminal — "paying a...
        [PAID] invoice" is rejected with ERR_INVOICE_STATE. The invoice's
        conservation invariant holds at 85000 paid + 0 credit + 0 outstanding.

        Design: Corner/errors/invoice_lifecycle_error_battery
        """
        cust, job = _fulfilled_job()
        inv = get_success_data(api.create_invoice({"job_id": job["id"]}, _PM))
        api.issue_invoice(inv["id"], _PM)
        api.dispute_invoice(inv["id"], {"reason": "quality"},
                            make_customer_headers(cust["id"]))
        r = api.pay_invoice(inv["id"], {"amount_cents": 85000}, _PM)
        data = validate_success(r, 201)
        assert data["status"] == "PAID", "exact outstanding from DISPUTED pays the invoice"
        r2 = api.pay_invoice(inv["id"], {"amount_cents": 1}, _PM)
        validate_error(r2, ApiErrorId.ERR_INVOICE_STATE)
        after = get_success_data(api.get_invoice(inv["id"], _PM))
        assert after["amount_paid_cents"] == 85000
        assert after["credit_applied_cents"] == 0
        assert after["amount_outstanding_cents"] == 0
        rows, meta = validate_paginated(
            api.list_invoices(_PM, params={"job_id": job["id"], "status": "PAID"}))
        assert meta["total_count"] == 1
