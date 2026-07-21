from flask import Blueprint, request

import store
import calc
from common import (ApiError, authorize, ok_object, ok_array, serialize, paginate,
                    sorted_list, get_body, require_month, require_iso, optional_iso,
                    require_int, require_landlord_owner, require_tenant_owner)
from routes.enrollments import _resolve_fk

bp = Blueprint("rent_payments", __name__)


@bp.post("/api/rent-payments")
def create_rent_payment():
    uid, role = authorize(["Landlord", "PlatformAdmin"])
    body = get_body()
    lease = _resolve_fk(body, "lease_id", store.leases, "ERR_LEASE_NOT_FOUND")
    require_landlord_owner(role, uid, lease["landlord_id"])

    period_month = require_month(body, "period_month")
    due_date = require_iso(body, "due_date")
    paid_date = optional_iso(body, "paid_date")
    amount_paid_cents = require_int(body, "amount_paid_cents")
    if amount_paid_cents < 0:
        raise ApiError("ERR_INVALID_REQUEST", "amount_paid_cents must be >= 0")
    expected_version = require_int(body, "expected_lease_version")

    # OCC (priority 9)
    if expected_version != lease["version"]:
        raise ApiError("ERR_STALE_VERSION", "stale lease version")

    on_time = calc.compute_on_time(paid_date, due_date)
    p = store.base_fields()
    p.update({
        "lease_id": lease["id"],
        "period_month": period_month,
        "due_date": due_date,
        "paid_date": paid_date,
        "amount_paid_cents": amount_paid_cents,
        "on_time": on_time,
        "status": "RECORDED",
    })
    store.rent_payments[p["id"]] = p
    store.touch(lease)  # a successful recording advances the lease version
    return ok_object(serialize(p), 201)


def _load_payment(pid):
    p = store.rent_payments.get(pid)
    if p is None:
        raise ApiError("ERR_PAYMENT_NOT_FOUND", "rent payment not found")
    return p


@bp.get("/api/rent-payments/<pid>")
def get_rent_payment(pid):
    uid, role = authorize(["Tenant", "Landlord", "PlatformAdmin"])
    p = _load_payment(pid)
    lease = store.leases.get(p["lease_id"])
    if role == "Tenant":
        require_tenant_owner(role, uid, lease["tenant_id"] if lease else None)
    elif role == "Landlord":
        require_landlord_owner(role, uid, lease["landlord_id"] if lease else None)
    return ok_object(serialize(p))


@bp.get("/api/rent-payments")
def list_rent_payments():
    uid, role = authorize(["Tenant", "Landlord", "PlatformAdmin"])
    lease_id = request.args.get("lease_id")
    status = request.args.get("status")

    def owned(p):
        lease = store.leases.get(p["lease_id"])
        if lease is None:
            return False
        if role == "Tenant":
            return lease["tenant_id"] == uid
        if role == "Landlord":
            return lease["landlord_id"] == uid
        return True

    def pred(p):
        if not owned(p):
            return False
        if lease_id is not None and p["lease_id"] != lease_id:
            return False
        if status is not None and p["status"] != status:
            return False
        return True

    items = sorted_list(store.rent_payments, pred)
    page, pagination = paginate(items)
    return ok_array([serialize(x) for x in page], pagination)


@bp.post("/api/rent-payments/<pid>/report")
def report_payment(pid):
    uid, role = authorize(["ComplianceAnalyst", "PlatformAdmin"])
    p = _load_payment(pid)
    lease = store.leases.get(p["lease_id"])

    # §3.5 checks in order
    if p["status"] != "RECORDED":
        raise ApiError("ERR_INVALID_STATE", "payment is not RECORDED")
    if lease is None or lease["verification_status"] != "VERIFIED":
        raise ApiError("ERR_LEASE_NOT_VERIFIED", "lease is not verified")
    if calc.month_covered(lease["id"], p["period_month"]):
        raise ApiError("ERR_PERIOD_ALREADY_COVERED", "month already covered")
    enrollment = calc.tenant_enrollment(lease["tenant_id"])
    if enrollment is None or enrollment["status"] != "ACTIVE":
        raise ApiError("ERR_ENROLLMENT_INACTIVE", "enrollment is not ACTIVE")

    item = _furnish_item(p, lease, source="MONTHLY", on_time=p["on_time"],
                         amount=p["amount_paid_cents"], supersedes=None)
    p["status"] = "REPORTED"
    store.touch(p)
    calc.recompute_tenant(lease["tenant_id"])
    return ok_object(serialize(item), 201)


def _furnish_item(payment, lease, source, on_time, amount, supersedes):
    item = store.base_fields()
    item.update({
        "rent_payment_id": payment["id"],
        "tenant_id": lease["tenant_id"],
        "lease_id": lease["id"],
        "supersedes_item_id": supersedes,
        "period_month": payment["period_month"],
        "on_time": on_time,
        "amount_reported_cents": amount,
        "source": source,
        "status": "REPORTED",
        "bureau_statuses": {b: "FURNISHED" for b in store.BUREAUS},
    })
    store.reported_items[item["id"]] = item
    return item
