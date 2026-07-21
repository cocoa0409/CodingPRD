from flask import Blueprint, request

import store
import calc
import common
from common import (ApiError, authorize, ok_object, ok_array, serialize, paginate,
                    sorted_list, get_body, require_enum, optional_str,
                    require_tenant_owner, month_index, current_month_str)
from routes.enrollments import _resolve_fk
from routes.rent_payments import _furnish_item

bp = Blueprint("back_reports", __name__)

GET_ROLES = ["Tenant", "ComplianceAnalyst", "ComplianceOfficer", "PlatformAdmin"]


def _load_request(bid):
    b = store.back_report_requests.get(bid)
    if b is None:
        raise ApiError("ERR_BACK_REPORT_NOT_FOUND", "back-report request not found")
    return b


def _fee_invoice(request_id):
    for inv in store.invoices.values():
        if inv["kind"] == "BACK_REPORT" and inv["back_report_request_id"] == request_id:
            return inv
    return None


def _recorded_payment(lease_id, month):
    cands = [p for p in store.rent_payments.values()
             if p["lease_id"] == lease_id and p["period_month"] == month and p["status"] == "RECORDED"]
    cands.sort(key=lambda p: p["_seq"])
    return cands[0] if cands else None


@bp.post("/api/back-report-requests")
def create_request():
    uid, role = authorize(["Tenant", "PlatformAdmin"])
    body = get_body()
    lease = _resolve_fk(body, "lease_id", store.leases, "ERR_LEASE_NOT_FOUND")
    require_tenant_owner(role, uid, lease["tenant_id"])

    rm = body.get("requested_months")
    if not isinstance(rm, list) or len(rm) == 0 or not all(
            isinstance(m, str) and common._valid_month(m) for m in rm):
        raise ApiError("ERR_INVALID_REQUEST", "requested_months must be a non-empty list of YYYY-MM")

    # §3.6 admissibility order: limit -> months valid -> covered
    if len(rm) > store.BACK_REPORT_MAX_MONTHS:
        raise ApiError("ERR_BACK_REPORT_LIMIT_EXCEEDED", "too many requested months")

    cur = month_index(current_month_str())
    for m in rm:
        midx = month_index(m)
        if midx > cur or (cur - midx) > store.BACK_REPORT_MAX_MONTHS:
            raise ApiError("ERR_BACK_REPORT_MONTHS_INVALID", "month out of allowed window")
        if _recorded_payment(lease["id"], m) is None:
            raise ApiError("ERR_BACK_REPORT_MONTHS_INVALID", "no RECORDED payment for month " + m)
    for m in rm:
        if calc.month_covered(lease["id"], m):
            raise ApiError("ERR_PERIOD_ALREADY_COVERED", "month already covered: " + m)

    enrollment = calc.tenant_enrollment(lease["tenant_id"])
    included = 0
    if enrollment is not None:
        plan = store.plans.get(enrollment["plan_id"])
        if plan is not None:
            included = plan["back_reporting_included_months"]
    billable, fee = calc.back_report_fee(len(rm), included)

    b = store.base_fields()
    b.update({
        "lease_id": lease["id"],
        "requested_months": list(rm),
        "billable_months": billable,
        "fee_cents": fee,
        "status": "PENDING",
    })
    store.back_report_requests[b["id"]] = b

    inv = store.base_fields()
    inv.update({
        "enrollment_id": enrollment["id"] if enrollment else None,
        "back_report_request_id": b["id"],
        "kind": "BACK_REPORT",
        "amount_cents": fee,
        "period_month": None,
        "status": "DUE",
        "paid_at": None,
    })
    store.invoices[inv["id"]] = inv

    return ok_object(serialize(b), 201)


@bp.get("/api/back-report-requests/<bid>")
def get_request(bid):
    uid, role = authorize(GET_ROLES)
    b = _load_request(bid)
    if role == "Tenant":
        lease = store.leases.get(b["lease_id"])
        require_tenant_owner(role, uid, lease["tenant_id"] if lease else None)
    return ok_object(serialize(b))


@bp.get("/api/back-report-requests")
def list_requests():
    uid, role = authorize(GET_ROLES)
    f_lease = request.args.get("lease_id")
    f_status = request.args.get("status")

    def pred(b):
        if role == "Tenant":
            lease = store.leases.get(b["lease_id"])
            if lease is None or lease["tenant_id"] != uid:
                return False
        if f_lease is not None and b["lease_id"] != f_lease:
            return False
        if f_status is not None and b["status"] != f_status:
            return False
        return True

    items = sorted_list(store.back_report_requests, pred)
    page, pagination = paginate(items)
    return ok_array([serialize(x) for x in page], pagination)


@bp.post("/api/back-report-requests/<bid>/decision")
def decide_request(bid):
    uid, role = authorize(["ComplianceOfficer"])
    b = _load_request(bid)
    body = get_body()
    decision = require_enum(body, "decision", ["APPROVED", "REJECTED"])
    optional_str(body, "note")

    if b["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", "request is not PENDING")

    lease = store.leases.get(b["lease_id"])
    if decision == "APPROVED":
        enrollment = calc.tenant_enrollment(lease["tenant_id"]) if lease else None
        if enrollment is None or enrollment["status"] != "ACTIVE":
            raise ApiError("ERR_ENROLLMENT_INACTIVE", "enrollment is not ACTIVE")
        inv = _fee_invoice(b["id"])
        if inv is None or inv["status"] != "PAID":
            raise ApiError("ERR_INVOICE_UNPAID", "back-report fee invoice is not PAID")
        for m in b["requested_months"]:
            if calc.month_covered(b["lease_id"], m):
                raise ApiError("ERR_PERIOD_ALREADY_COVERED", "month became covered: " + m)
        b["status"] = "APPROVED"
        store.touch(b)
    else:  # REJECTED
        b["status"] = "REJECTED"
        store.touch(b)
        inv = _fee_invoice(b["id"])
        if inv is not None and inv["status"] == "DUE":
            inv["status"] = "VOID"
            store.touch(inv)

    return ok_object(serialize(b))


@bp.post("/api/back-report-requests/<bid>/complete")
def complete_request(bid):
    uid, role = authorize(["ComplianceAnalyst"])
    b = _load_request(bid)
    get_body()
    if b["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", "request is not APPROVED")
    lease = store.leases.get(b["lease_id"])
    if lease is None or lease["verification_status"] != "VERIFIED":
        raise ApiError("ERR_LEASE_NOT_VERIFIED", "lease is not verified")

    for m in b["requested_months"]:
        payment = _recorded_payment(lease["id"], m)
        if payment is None:
            continue
        _furnish_item(payment, lease, source="BACK_REPORT", on_time=payment["on_time"],
                      amount=payment["amount_paid_cents"], supersedes=None)
        payment["status"] = "REPORTED"
        store.touch(payment)

    b["status"] = "COMPLETED"
    store.touch(b)
    calc.recompute_tenant(lease["tenant_id"])
    return ok_object(serialize(b))
