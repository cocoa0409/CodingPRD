"""Job cancellation battery: fee-free early stages, CANCELLATION_FEE from
PLATED, cancel-point cutoff, and locked-gang protection."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    accept_estimate,
    approve_proof,
    create_accepted_job,
    create_customer,
    create_gang_with_members,
    create_job_in_bindery,
    create_plated_job,
    create_received_stock,
    get_success_data,
    lock_gang,
    make_customer_headers,
    minimal_signature,
    quote_estimate,
    create_estimate,
    upload_proof,
    validate_error,
    validate_paginated,
    validate_success,
)

_PM = TEST_USERS["plant_manager_headers"]


class TestJobCancellation:
    def _setup(self, api):
        cust = create_customer(name="JC Cust")
        stock, _po = create_received_stock(name="70U", grade="UNCOATED",
                                           cost_per_sheet_cents=5, sheets=5000)
        sigs = minimal_signature(stock["id"], make_ready_cents=50000)
        # A: PREPRESS; B: PLATED; C: BINDERY; D1/D2: LOCKED gang members
        _ea, ja = create_accepted_job(cust["id"], sigs, quantity_ordered=1000, job_name="A")
        _eb, jb, _pb = create_plated_job(cust["id"], minimal_signature(stock["id"],
                                         make_ready_cents=50000),
                                         quantity_ordered=1000, job_name="B")
        _ec, jc, _run, _press = create_job_in_bindery(
            cust["id"], minimal_signature(stock["id"], make_ready_cents=50000),
            quantity_ordered=1000, job_name="C")
        jd1 = create_plated_job(cust["id"], minimal_signature(stock["id"],
                                make_ready_cents=50000), quantity_ordered=1000, job_name="D1")[1]
        jd2 = create_plated_job(cust["id"], minimal_signature(stock["id"],
                                make_ready_cents=60000), quantity_ordered=1000, job_name="D2")[1]
        gang = create_gang_with_members(stock["id"], [jd1["id"], jd2["id"]])
        lock_gang(gang["id"])
        return cust, ja, jb, jc, jd1

    def test_cancel_from_prepress_is_fee_free(self, api):
        """PRD §3.11: "Cancelling from `PREPRESS` incurs no fee: the job moves
        to `CANCELLED`, its `billing_status` becomes `NOT_BILLABLE`, and no
        invoice is created."

        Design: Corner/errors/job_cancellation_battery
        """
        _cust, ja, _jb, _jc, _jd1 = self._setup(api)
        resp = api.cancel_job(ja["id"], {"reason": "customer request"}, _PM)
        data = validate_success(resp, 200)
        assert data["production_status"] == "CANCELLED"
        assert data["billing_status"] == "NOT_BILLABLE"
        _rows, meta = validate_paginated(api.list_invoices(_PM, params={"job_id": ja["id"]}))
        assert meta["total_count"] == 0

    def test_cancel_from_plated_creates_cancellation_fee_invoice(self, api):
        """PRD §3.11: "Cancelling from `PLATED`... auto-creates a
        `CANCELLATION_FEE` invoice in `ISSUED` status whose `total_due_cents`
        is exactly the job's `make_ready_total_cents`; the job's
        `billing_status` becomes `INVOICED`."

        Design: Corner/errors/job_cancellation_battery
        """
        _cust, _ja, jb, _jc, _jd1 = self._setup(api)
        resp = api.cancel_job(jb["id"], {}, _PM)
        data = validate_success(resp, 200)
        assert data["production_status"] == "CANCELLED"
        assert data["billing_status"] == "INVOICED"
        rows, meta = validate_paginated(api.list_invoices(_PM, params={"job_id": jb["id"]}))
        assert meta["total_count"] == 1
        fee = rows[0]
        assert fee["kind"] == "CANCELLATION_FEE"
        assert fee["status"] == "ISSUED"
        assert fee["total_due_cents"] == 50000

    def test_cancel_from_bindery_rejected(self, api):
        """PRD §3.11: "Cancelling from `BINDERY` or later is rejected with
        `ERR_JOB_PAST_CANCEL_POINT`."

        Design: Corner/errors/job_cancellation_battery
        """
        _cust, _ja, _jb, jc, _jd1 = self._setup(api)
        resp = api.cancel_job(jc["id"], {}, _PM)
        validate_error(resp, ApiErrorId.ERR_JOB_PAST_CANCEL_POINT)

    def test_cancel_locked_gang_member_rejected(self, api):
        """PRD §3.11: "A job that is a member of a `LOCKED` or `CONSUMED` gang
        cannot be cancelled — the attempt is rejected with
        `ERR_JOB_IN_LOCKED_GANG`."

        Design: Corner/errors/job_cancellation_battery
        """
        _cust, _ja, _jb, _jc, jd1 = self._setup(api)
        resp = api.cancel_job(jd1["id"], {}, _PM)
        validate_error(resp, ApiErrorId.ERR_JOB_IN_LOCKED_GANG)


class TestBinderySequence:
    def test_bindery_out_of_order_rejected(self, api):
        """PRD §3.8: "every ticket of the same job with a lower `sequence_no`
        must already be `COMPLETE` — completing out of order is rejected with
        `ERR_BINDERY_SEQUENCE`. When the completing ticket is the last
        non-`COMPLETE` ticket of the job, the job transitions `BINDERY →
        READY_TO_SHIP`."

        Design: Corner/state_machines/bindery_out_of_order_rejected
        """
        cust = create_customer(name="B Cust")
        stock, _po = create_received_stock(name="70U", grade="UNCOATED",
                                           cost_per_sheet_cents=5, sheets=5000)
        _est, job, _run, _press = create_job_in_bindery(
            cust["id"], minimal_signature(stock["id"], make_ready_cents=50000),
            quantity_ordered=1000, job_name="BJ")
        t1 = get_success_data(api.create_bindery_ticket(
            {"job_id": job["id"], "operation": "FOLD", "sequence_no": 1}, _PM))
        t2 = get_success_data(api.create_bindery_ticket(
            {"job_id": job["id"], "operation": "STITCH", "sequence_no": 2}, _PM))
        r_bad = api.complete_bindery_ticket(t2["id"], {"pieces_completed": 1000}, _PM)
        validate_error(r_bad, ApiErrorId.ERR_BINDERY_SEQUENCE)
        validate_success(api.complete_bindery_ticket(t1["id"], {"pieces_completed": 1000}, _PM), 200)
        r_ok = api.complete_bindery_ticket(t2["id"], {"pieces_completed": 990}, _PM)
        validate_success(r_ok, 200)
        job_after = get_success_data(api.get_job(job["id"], _PM))
        assert job_after["production_status"] == "READY_TO_SHIP"
