"""Bill endpoints (PRD §3.6)."""
from flask import Blueprint, request

from db import now, sort_default, stamp_new, store, touch
from errors import (ERR_ACCOUNT_NOT_FOUND, ERR_BILL_NOT_FOUND,
                    ERR_CHART_NOT_CODED, ERR_INVALID_REQUEST,
                    ERR_INVALID_STATE, fail)
from middleware import ALL_ROLES, require_roles
from response import ok_obj, paginate
from services.core import bill_for_account, case_for_chart, chart_for_account, ser_bill
from validators import body, has, req_dt, req_int

bp = Blueprint("bills", __name__)


def get_bill_or_404(bill_id):
    b = store.bills.get(bill_id)
    if b is None:
        fail(404, ERR_BILL_NOT_FOUND, f"Bill {bill_id} does not exist")
    return b


@bp.route("/bills", methods=["POST"])
def create_bill():
    require_roles("BillingClerk")
    b = body()
    if not has(b, "account_id"):
        fail(400, ERR_INVALID_REQUEST, "account_id is required")
    account = store.accounts.get(b["account_id"])
    if account is None:
        fail(404, ERR_ACCOUNT_NOT_FOUND,
             f"PatientAccount {b['account_id']} does not exist")
    if bill_for_account(account["id"]) is not None:
        fail(400, ERR_INVALID_REQUEST, "One bill per account")
    chart = chart_for_account(account["id"])
    status = "DRAFT"
    expected = 0
    if chart is not None and chart["status"] == "CODED":
        case = case_for_chart(chart["id"])
        status = "READY"
        expected = case["expected_reimbursement_cents"] if case is not None else 0
    bill = stamp_new({
        "account_id": account["id"],
        "status": status,
        "expected_reimbursement_cents": expected,
        "billed_amount_cents": None,
        "paid_amount_cents": None,
        "net_receivable_cents": None,
        "finalized_at": None,
        "paid_at": None,
    })
    store.bills[bill["id"]] = bill
    return ok_obj(ser_bill(bill), 201)


@bp.route("/bills/<id>", methods=["GET"])
def get_bill(id):
    require_roles(*ALL_ROLES)
    return ok_obj(ser_bill(get_bill_or_404(id)), 200)


@bp.route("/bills", methods=["GET"])
def list_bills():
    require_roles(*ALL_ROLES)
    items = list(store.bills.values())
    account_id = request.args.get("account_id")
    if account_id is not None:
        items = [b for b in items if b["account_id"] == account_id]
    status = request.args.get("status")
    if status is not None:
        items = [b for b in items if b["status"] == status]
    return paginate([ser_bill(b) for b in sort_default(items)])


@bp.route("/bills/<id>/finalize", methods=["POST"])
def finalize_bill(id):
    require_roles("BillingClerk")
    bill = get_bill_or_404(id)
    if bill["status"] != "READY":
        fail(409, ERR_INVALID_STATE,
             f"Cannot finalize a bill in state {bill['status']}")
    chart = chart_for_account(bill["account_id"])
    if chart is None or chart["status"] != "CODED":
        fail(409, ERR_CHART_NOT_CODED, "Chart is not CODED")
    bill["billed_amount_cents"] = bill["expected_reimbursement_cents"]
    bill["finalized_at"] = now()
    bill["status"] = "FINAL_BILLED"
    touch(bill)
    case = case_for_chart(chart["id"])
    if case is not None and case["status"] == "GROUPED":
        case["status"] = "LOCKED"
        touch(case)
    return ok_obj(ser_bill(bill), 200)


@bp.route("/bills/<id>/record-payment", methods=["POST"])
def record_payment(id):
    require_roles("BillingClerk")
    bill = get_bill_or_404(id)
    if bill["status"] != "FINAL_BILLED":
        fail(409, ERR_INVALID_STATE,
             f"Cannot record payment on a bill in state {bill['status']}")
    b = body()
    paid_amount = req_int(b, "paid_amount_cents")
    paid_at = req_dt(b, "paid_at")
    bill["paid_amount_cents"] = paid_amount
    bill["paid_at"] = paid_at
    bill["net_receivable_cents"] = bill["billed_amount_cents"] - paid_amount
    bill["status"] = "PAID"
    touch(bill)
    return ok_obj(ser_bill(bill), 200)
