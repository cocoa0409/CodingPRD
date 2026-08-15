"""Routes: tax bills, validation, payment scheduling (PRD §3.6)."""

from datetime import timedelta

from flask import Blueprint, request

import errors as E
from middleware import get_caller, require_role, parse_pagination
from response import ok, created, ok_list
from util import (
    get_body, req_int, req_number, lookup, stamp_new, touch,
    parse_date_field, append_audit,
)
from services import (
    run_bill_validation, recompute_payment_status, INSTALLMENT_SPACING_DAYS,
)
from serializers import bill_view

bp = Blueprint("bills", __name__)

ALL_ROLES = ("FirmAdmin", "TaxAnalyst", "SeniorManager", "AssessorClerk", "Client")


def register(app, store):

    # ------------------------------------------------------------------
    # POST /bpp/assessment-notices/<notice_id>/tax-bills
    # ------------------------------------------------------------------
    @app.post("/bpp/assessment-notices/<notice_id>/tax-bills")
    def create_bill(notice_id):
        caller = get_caller(store)
        require_role(caller, "TaxAnalyst", "SeniorManager")
        n = lookup(store.notices, notice_id, "AssessmentNotice")
        body = get_body()
        billed = req_int(body, "billed_amount_cents", min_v=1)
        tax_rate = req_number(body, "tax_rate")
        due = parse_date_field(body, "due_date")
        # state gate (priority 10)
        if n["notice_status"] not in ("ACCEPTED", "PROTESTED", "FINALIZED"):
            E.raise_err(E.ERR_BILL_NOT_ACTIONABLE,
                        "Bills may only be imported on an ACCEPTED, PROTESTED, or FINALIZED notice")
        b = {
            "notice_id": n["id"],
            "billed_amount_cents": billed,
            "tax_rate": tax_rate,
            "due_date": due,
            "validated_amount_cents": None,
            "variance_cents": None,
            "validation_status": "PENDING",
            "payment_status": "UNSCHEDULED",
            "installments": [],
            "unscheduled_amount_cents": None,
            "created_by_operator_id": caller.user_id,
            "validated_by_operator_id": None,
        }
        stamp_new(store, b)
        store.bills[b["id"]] = b
        return created(bill_view(b))

    # ------------------------------------------------------------------
    # GET /bpp/tax-bills/<bill_id>
    # ------------------------------------------------------------------
    @app.get("/bpp/tax-bills/<bill_id>")
    def get_bill(bill_id):
        caller = get_caller(store)
        require_role(caller, *ALL_ROLES)
        b = lookup(store.bills, bill_id, "TaxBill")
        return ok(bill_view(b))

    # ------------------------------------------------------------------
    # GET /bpp/assessment-notices/<notice_id>/tax-bills
    # ------------------------------------------------------------------
    @app.get("/bpp/assessment-notices/<notice_id>/tax-bills")
    def list_bills(notice_id):
        caller = get_caller(store)
        require_role(caller, *ALL_ROLES)
        lookup(store.notices, notice_id, "AssessmentNotice")
        limit, offset = parse_pagination()
        items = [b for b in store.bills.values() if b["notice_id"] == notice_id]
        vs = request.args.get("validation_status")
        if vs is not None:
            items = [b for b in items if b["validation_status"] == vs]
        ps = request.args.get("payment_status")
        if ps is not None:
            items = [b for b in items if b["payment_status"] == ps]
        items.sort(key=lambda b: b["created_at"])
        total = len(items)
        page = items[offset : offset + limit]
        return ok_list([bill_view(b) for b in page], total, limit, offset)

    # ------------------------------------------------------------------
    # POST /bpp/tax-bills/<bill_id>/validate
    # ------------------------------------------------------------------
    @app.post("/bpp/tax-bills/<bill_id>/validate")
    def validate_bill(bill_id):
        caller = get_caller(store)
        require_role(caller, "SeniorManager")
        b = lookup(store.bills, bill_id, "TaxBill")
        get_body()
        # state gate (priority 10)
        if b["validation_status"] != "PENDING":
            E.raise_err(E.ERR_BILL_NOT_ACTIONABLE, "Only a PENDING bill may be validated")
        # segregation of duties (priority 11)
        if caller.user_id == b["created_by_operator_id"]:
            E.raise_err(E.ERR_SEGREGATION_OF_DUTIES,
                        "The operator who imported the bill may not validate it")
        run_bill_validation(store, b)
        b["unscheduled_amount_cents"] = b["validated_amount_cents"]
        b["validated_by_operator_id"] = caller.user_id
        recompute_payment_status(b)
        touch(b)
        notice = store.notices[b["notice_id"]]
        rendition = store.renditions[notice["rendition_id"]]
        append_audit(store, rendition["client_id"], "BILL_VALIDATED",
                     f"Tax bill {b['id']} validated", caller.user_id)
        return ok(bill_view(b))

    # ------------------------------------------------------------------
    # POST /bpp/tax-bills/<bill_id>/payment-schedule
    # ------------------------------------------------------------------
    @app.post("/bpp/tax-bills/<bill_id>/payment-schedule")
    def create_schedule(bill_id):
        caller = get_caller(store)
        require_role(caller, "TaxAnalyst")
        b = lookup(store.bills, bill_id, "TaxBill")
        body = get_body()
        count = req_int(body, "installment_count", min_v=1, max_v=4)
        # state gate (priority 10)
        if b["validation_status"] not in ("MATCHED", "DISCREPANCY"):
            E.raise_err(E.ERR_BILL_NOT_ACTIONABLE,
                        "Payment scheduling requires a validated bill")
        if b["payment_status"] != "UNSCHEDULED":
            E.raise_err(E.ERR_BILL_NOT_ACTIONABLE,
                        "Payment scheduling requires payment_status UNSCHEDULED")
        # schedule substance (priority 29)
        if (b["validated_amount_cents"] or 0) <= 0:
            E.raise_err(E.ERR_ZERO_SCHEDULE_AMOUNT,
                        "Cannot schedule payments on a zero validated amount")

        amount = b["validated_amount_cents"]
        base = amount // count
        remainder = amount - base * count
        installments = []
        for i in range(1, count + 1):
            amt = base + remainder if i == 1 else base
            installments.append({
                "installment_no": i,
                "due_date": b["due_date"] + timedelta(days=(i - 1) * INSTALLMENT_SPACING_DAYS),
                "amount_cents": amt,
                "installment_status": "SCHEDULED",
                "paid_date": None,
            })
        b["installments"] = installments
        b["unscheduled_amount_cents"] = 0
        recompute_payment_status(b)
        touch(b)
        notice = store.notices[b["notice_id"]]
        rendition = store.renditions[notice["rendition_id"]]
        append_audit(store, rendition["client_id"], "SCHEDULE_CREATED",
                     f"Payment schedule created on bill {b['id']}", caller.user_id)
        return ok(bill_view(b))

    # ------------------------------------------------------------------
    # POST /bpp/tax-bills/<bill_id>/payment-schedule/cancel
    # ------------------------------------------------------------------
    @app.post("/bpp/tax-bills/<bill_id>/payment-schedule/cancel")
    def cancel_schedule(bill_id):
        caller = get_caller(store)
        require_role(caller, "TaxAnalyst")
        b = lookup(store.bills, bill_id, "TaxBill")
        get_body()
        if b["payment_status"] not in ("SCHEDULED", "PARTIALLY_PAID", "DELINQUENT"):
            E.raise_err(E.ERR_BILL_NOT_ACTIONABLE,
                        "Only a bill with an active schedule may be cancelled")
        for inst in b["installments"]:
            if inst["installment_status"] in ("SCHEDULED", "LATE"):
                inst["installment_status"] = "CANCELLED"
        paid_sum = sum(i["amount_cents"] for i in b["installments"] if i["installment_status"] == "PAID")
        b["unscheduled_amount_cents"] = (b["validated_amount_cents"] or 0) - paid_sum
        recompute_payment_status(b)
        touch(b)
        notice = store.notices[b["notice_id"]]
        rendition = store.renditions[notice["rendition_id"]]
        append_audit(store, rendition["client_id"], "SCHEDULE_CANCELLED",
                     f"Payment schedule cancelled on bill {b['id']}", caller.user_id)
        return ok(bill_view(b))

    # ------------------------------------------------------------------
    # POST /bpp/tax-bills/<bill_id>/pay-installment
    # ------------------------------------------------------------------
    @app.post("/bpp/tax-bills/<bill_id>/pay-installment")
    def pay_installment(bill_id):
        caller = get_caller(store)
        require_role(caller, "Client")
        b = lookup(store.bills, bill_id, "TaxBill")
        body = get_body()
        no = req_int(body, "installment_no", min_v=1)
        # Client ownership via FK chain (priority 2)
        notice = store.notices[b["notice_id"]]
        rendition = store.renditions[notice["rendition_id"]]
        if rendition["client_id"] != caller.user_id:
            E.raise_err(E.ERR_FORBIDDEN_ROLE, "Client does not own this bill")
        inst = None
        for i in b["installments"]:
            if i["installment_no"] == no:
                inst = i
                break
        if inst is None:
            E.raise_err(E.ERR_INVALID_REQUEST, f"No installment numbered {no}")
        if inst["installment_status"] not in ("SCHEDULED", "LATE"):
            E.raise_err(E.ERR_INVALID_STATE_TRANSITION,
                        "Only a SCHEDULED or LATE installment may be paid")
        inst["installment_status"] = "PAID"
        inst["paid_date"] = store.clock_date()
        recompute_payment_status(b)
        touch(b)
        append_audit(store, rendition["client_id"], "INSTALLMENT_PAID",
                     f"Installment {no} of bill {b['id']} paid", caller.user_id)
        return ok(bill_view(b))
