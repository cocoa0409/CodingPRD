from flask import Blueprint, request

import store
import calc
from common import (ApiError, authorize, ok_object, ok_array, serialize, paginate,
                    sorted_list, get_body, current_month_str, require_tenant_owner)

bp = Blueprint("enrollments", __name__)


def _resolve_fk(body, field, collection, not_found_err):
    """Left-to-right FK resolution: missing -> invalid_request, unknown -> not_found."""
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        raise ApiError("ERR_INVALID_REQUEST", "missing or invalid field: " + field)
    obj = collection.get(v)
    if obj is None:
        raise ApiError(not_found_err, field + " not found")
    return obj


@bp.post("/api/enrollments")
def create_enrollment():
    uid, role = authorize(["Tenant", "PlatformAdmin"])
    body = get_body()
    # self-ownership (priority 2) when a Tenant supplies a mismatched tenant_id
    tid = body.get("tenant_id")
    if role == "Tenant" and isinstance(tid, str) and tid != uid:
        raise ApiError("ERR_UNAUTHORIZED", "tenant may only enroll themselves")
    # existence left-to-right: tenant_id, plan_id
    tenant = _resolve_fk(body, "tenant_id", store.tenants, "ERR_TENANT_NOT_FOUND")
    plan = _resolve_fk(body, "plan_id", store.plans, "ERR_PLAN_NOT_FOUND")

    e = store.base_fields()
    e.update({
        "tenant_id": tenant["id"],
        "plan_id": plan["id"],
        "status": "PENDING_PAYMENT",
        "monthly_fee_cents": plan["monthly_fee_cents"],
        "current_period_start": None,
        "current_period_end": None,
        "cancelled_at": None,
        "refund_cents": 0,
        "earned_cents": 0,
    })
    store.enrollments[e["id"]] = e

    inv = store.base_fields()
    inv.update({
        "enrollment_id": e["id"],
        "back_report_request_id": None,
        "kind": "SUBSCRIPTION",
        "amount_cents": plan["monthly_fee_cents"],
        "period_month": current_month_str(),
        "status": "DUE",
        "paid_at": None,
    })
    store.invoices[inv["id"]] = inv

    return ok_object(serialize(e), 201)


def _load_enrollment(eid):
    e = store.enrollments.get(eid)
    if e is None:
        raise ApiError("ERR_ENROLLMENT_NOT_FOUND", "enrollment not found")
    return e


@bp.get("/api/enrollments/<eid>")
def get_enrollment(eid):
    uid, role = authorize(["Tenant", "PlatformAdmin"])
    e = _load_enrollment(eid)
    require_tenant_owner(role, uid, e["tenant_id"])
    return ok_object(serialize(e))


@bp.get("/api/enrollments")
def list_enrollments():
    uid, role = authorize(["Tenant", "PlatformAdmin"])
    tenant_id = request.args.get("tenant_id")
    plan_id = request.args.get("plan_id")
    status = request.args.get("status")

    def pred(e):
        if role == "Tenant" and e["tenant_id"] != uid:
            return False
        if tenant_id is not None and e["tenant_id"] != tenant_id:
            return False
        if plan_id is not None and e["plan_id"] != plan_id:
            return False
        if status is not None and e["status"] != status:
            return False
        return True

    items = sorted_list(store.enrollments, pred)
    page, pagination = paginate(items)
    return ok_array([serialize(x) for x in page], pagination)


@bp.post("/api/enrollments/<eid>/cancel")
def cancel_enrollment(eid):
    uid, role = authorize(["Tenant"])
    e = _load_enrollment(eid)
    require_tenant_owner(role, uid, e["tenant_id"])
    if e["status"] == "CANCELLED":
        raise ApiError("ERR_INVALID_STATE", "enrollment already cancelled")

    now = store.clock_now()
    from_state = e["status"]
    e["cancelled_at"] = now

    if from_state == "ACTIVE":
        refund, earned = calc.cancellation_settlement(e, now)
        e["refund_cents"] = refund
        e["earned_cents"] = earned
    else:  # PENDING_PAYMENT
        e["refund_cents"] = 0
        e["earned_cents"] = 0

    e["status"] = "CANCELLED"
    store.touch(e)

    # VOID any DUE invoices on this enrollment
    for inv in store.invoices.values():
        if inv["enrollment_id"] == e["id"] and inv["status"] == "DUE":
            inv["status"] = "VOID"
            store.touch(inv)

    if from_state == "ACTIVE":
        calc.cascade_cancel_terminations(e["tenant_id"])

    return ok_object(serialize(e))
