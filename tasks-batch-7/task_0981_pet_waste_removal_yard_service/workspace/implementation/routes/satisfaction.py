from flask import Blueprint, request

import services as svc
from clock import now
from errors import ApiError, err_invalid_request, err_invalid_state, err_unauthorized
from middleware import (
    auth,
    get_body,
    require,
    require_enum,
    lookup,
    lookup_fk,
    parse_pagination,
    paginate,
)
from response import ok_object, ok_list

bp = Blueprint("satisfaction", __name__)

ISSUE_CATEGORIES = {"MISSED_SPOT", "LATE_ARRIVAL", "GATE_ISSUE", "PET_SAFETY", "BILLING", "OTHER"}


def _check_credit_range(amount):
    if amount < 0 or amount > 100000:
        raise ApiError("ERR_CREDIT_OUT_OF_RANGE", 422,
                       "resolution_credit_cents must be between 0 and 100000")


@bp.post("/api/satisfaction-reports")
def create_report():
    uid, _ = auth("Customer")
    data = get_body()
    customer_id = require(data, "customer_id", str)
    visit_id = require(data, "visit_id", str)
    rating = require(data, "rating", int)
    category = require_enum(data, "issue_category", ISSUE_CATEGORIES)
    if not (1 <= rating <= 5):
        raise err_invalid_request("rating must be between 1 and 5")
    customer = lookup_fk(svc.customers, customer_id, "Customer")
    visit = lookup_fk(svc.visits, visit_id, "Visit")
    if customer_id != uid:
        raise err_unauthorized("Customers may only file reports for themselves")
    sub = svc.subscriptions.get(visit["subscription_id"])
    if sub is None or sub["customer_id"] != customer_id:
        raise err_unauthorized("Visit does not belong to this customer")
    if customer["account_status"] != "ACTIVE":
        raise ApiError("ERR_ACCOUNT_NOT_ACTIVE", 409,
                       "Customer.account_status must be ACTIVE")
    rec = svc.new_record()
    rec.update(
        {
            "customer_id": customer_id,
            "visit_id": visit_id,
            "rating": rating,
            "issue_category": category,
            "report_status": "SUBMITTED",
            "resolution_credit_cents": None,
            "resolved_at": None,
        }
    )
    svc.reports[rec["id"]] = rec
    customer["satisfaction_rolling_avg"] = svc.compute_satisfaction_avg(customer["id"])
    svc.bump(customer)
    return ok_object(svc.ser_report(rec), status=201)


@bp.get("/api/satisfaction-reports/<rid>")
def get_report(rid):
    uid, role = auth("OperationsManager", "BillingAdmin", "Customer")
    rec = lookup(svc.reports, rid, "SatisfactionReport")
    if role == "Customer" and rec["customer_id"] != uid:
        raise err_unauthorized("Customers may only access their own reports")
    return ok_object(svc.ser_report(rec))


@bp.get("/api/satisfaction-reports")
def list_reports():
    uid, role = auth("OperationsManager", "BillingAdmin", "Customer")
    limit, offset = parse_pagination()
    records = list(svc.reports.values())
    if role == "Customer":
        requested = request.args.get("customer_id")
        if requested is not None and requested != uid:
            raise err_unauthorized("Customers may only list their own reports")
        records = [r for r in records if r["customer_id"] == uid]
    else:
        customer_id = request.args.get("customer_id")
        if customer_id is not None:
            records = [r for r in records if r["customer_id"] == customer_id]
    visit_id = request.args.get("visit_id")
    if visit_id is not None:
        records = [r for r in records if r["visit_id"] == visit_id]
    status = request.args.get("report_status")
    if status is not None:
        records = [r for r in records if r["report_status"] == status]
    page, total = paginate(records, limit, offset)
    return ok_list([svc.ser_report(r) for r in page], total, limit, offset)


@bp.post("/api/satisfaction-reports/<rid>/begin-review")
def begin_review(rid):
    auth("OperationsManager")
    rec = lookup(svc.reports, rid, "SatisfactionReport")
    if rec["report_status"] != "SUBMITTED":
        raise err_invalid_state("begin-review is only valid from SUBMITTED")
    rec["report_status"] = "UNDER_REVIEW"
    svc.bump(rec)
    return ok_object(svc.ser_report(rec))


@bp.post("/api/satisfaction-reports/<rid>/escalate")
def escalate(rid):
    auth("OperationsManager")
    rec = lookup(svc.reports, rid, "SatisfactionReport")
    if rec["report_status"] != "UNDER_REVIEW":
        raise err_invalid_state("escalate is only valid from UNDER_REVIEW")
    rec["report_status"] = "ESCALATED"
    svc.bump(rec)
    return ok_object(svc.ser_report(rec))


@bp.post("/api/satisfaction-reports/<rid>/resolve")
def resolve(rid):
    _, role = auth("OperationsManager", "BillingAdmin")
    data = get_body()
    credit = require(data, "resolution_credit_cents", int)
    rec = lookup(svc.reports, rid, "SatisfactionReport")
    # UNDER_REVIEW resolves via OperationsManager; ESCALATED via BillingAdmin
    if rec["report_status"] == "UNDER_REVIEW" and role == "OperationsManager":
        pass
    elif rec["report_status"] == "ESCALATED" and role == "BillingAdmin":
        pass
    else:
        raise err_invalid_state(
            "resolve is valid from UNDER_REVIEW (OperationsManager) or ESCALATED (BillingAdmin)")
    _check_credit_range(credit)
    rec["report_status"] = "RESOLVED"
    rec["resolved_at"] = now()
    rec["resolution_credit_cents"] = credit
    svc.bump(rec)
    customer = svc.customers.get(rec["customer_id"])
    if customer is not None:
        customer["credit_balance_cents"] += credit
        customer["satisfaction_rolling_avg"] = svc.compute_satisfaction_avg(customer["id"])
        svc.bump(customer)
    return ok_object(svc.ser_report(rec))
