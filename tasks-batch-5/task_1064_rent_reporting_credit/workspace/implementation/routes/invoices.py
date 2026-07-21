from flask import Blueprint, request

import store
from common import (ApiError, authorize, ok_object, ok_array, serialize, paginate,
                    sorted_list, get_body, require_tenant_owner)

bp = Blueprint("invoices", __name__)


def _load_invoice(iid):
    inv = store.invoices.get(iid)
    if inv is None:
        raise ApiError("ERR_INVOICE_NOT_FOUND", "invoice not found")
    return inv


def _invoice_tenant(inv):
    e = store.enrollments.get(inv["enrollment_id"])
    return e["tenant_id"] if e else None


@bp.get("/api/invoices/<iid>")
def get_invoice(iid):
    uid, role = authorize(["Tenant", "PlatformAdmin"])
    inv = _load_invoice(iid)
    require_tenant_owner(role, uid, _invoice_tenant(inv))
    return ok_object(serialize(inv))


@bp.get("/api/invoices")
def list_invoices():
    uid, role = authorize(["Tenant", "PlatformAdmin"])
    f_enrollment = request.args.get("enrollment_id")
    f_brr = request.args.get("back_report_request_id")
    f_kind = request.args.get("kind")
    f_status = request.args.get("status")

    def pred(inv):
        if role == "Tenant" and _invoice_tenant(inv) != uid:
            return False
        if f_enrollment is not None and inv["enrollment_id"] != f_enrollment:
            return False
        if f_brr is not None and inv["back_report_request_id"] != f_brr:
            return False
        if f_kind is not None and inv["kind"] != f_kind:
            return False
        if f_status is not None and inv["status"] != f_status:
            return False
        return True

    items = sorted_list(store.invoices, pred)
    page, pagination = paginate(items)
    return ok_array([serialize(x) for x in page], pagination)


@bp.post("/api/invoices/<iid>/pay")
def pay_invoice(iid):
    uid, role = authorize(["Tenant", "PlatformAdmin"])
    inv = _load_invoice(iid)
    require_tenant_owner(role, uid, _invoice_tenant(inv))
    get_body()
    if inv["status"] != "DUE":
        raise ApiError("ERR_INVALID_STATE", "invoice is not DUE")

    now = store.clock_now()
    inv["status"] = "PAID"
    inv["paid_at"] = now
    store.touch(inv)

    if inv["kind"] == "SUBSCRIPTION":
        e = store.enrollments.get(inv["enrollment_id"])
        if e is not None and e["status"] == "PENDING_PAYMENT":
            e["status"] = "ACTIVE"
            e["current_period_start"] = now
            e["current_period_end"] = store.add_one_month(now)
            store.touch(e)

    return ok_object(serialize(inv))
