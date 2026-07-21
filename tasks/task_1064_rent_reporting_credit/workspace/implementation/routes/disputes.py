from datetime import timedelta
from flask import Blueprint, request

import store
import calc
from common import (ApiError, authorize, ok_object, ok_array, serialize, paginate,
                    sorted_list, get_body, require_enum, require_int, optional_str,
                    require_tenant_owner)
from routes.enrollments import _resolve_fk

bp = Blueprint("disputes", __name__)

GET_ROLES = ["Tenant", "ComplianceAnalyst", "ComplianceOfficer", "PlatformAdmin"]


def _load_dispute(did):
    d = store.disputes.get(did)
    if d is None:
        raise ApiError("ERR_DISPUTE_NOT_FOUND", "dispute not found")
    return d


def _reinstate_item(item):
    item["status"] = "REPORTED"
    item["bureau_statuses"] = {b: "FURNISHED" for b in store.BUREAUS}
    store.touch(item)


@bp.post("/api/disputes")
def file_dispute():
    uid, role = authorize(["Tenant"])
    body = get_body()
    item = _resolve_fk(body, "reported_item_id", store.reported_items, "ERR_REPORTED_ITEM_NOT_FOUND")
    require_tenant_owner(role, uid, item["tenant_id"])
    reason_code = require_enum(body, "reason_code",
                              ["NOT_MINE", "INCORRECT_AMOUNT", "INCORRECT_STATUS", "PAID_ON_TIME"])
    # state: item must be REPORTED
    if item["status"] != "REPORTED":
        raise ApiError("ERR_ITEM_NOT_DISPUTABLE", "reported item is not disputable")
    # dispute window
    if store.clock_now() > item["created_at"] + timedelta(days=store.DISPUTE_WINDOW_DAYS):
        raise ApiError("ERR_DISPUTE_WINDOW_CLOSED", "dispute window has closed")

    d = store.base_fields()
    d.update({
        "reported_item_id": item["id"],
        "tenant_id": uid,
        "reason_code": reason_code,
        "status": "OPEN",
        "analyst_user_id": None,
        "officer_user_id": None,
        "investigation_deadline": None,
        "resolution_note": None,
    })
    store.disputes[d["id"]] = d

    item["status"] = "DISPUTED"
    store.touch(item)
    return ok_object(serialize(d), 201)


@bp.get("/api/disputes/<did>")
def get_dispute(did):
    uid, role = authorize(GET_ROLES)
    d = _load_dispute(did)
    require_tenant_owner(role, uid, d["tenant_id"])
    return ok_object(serialize(d))


@bp.get("/api/disputes")
def list_disputes():
    uid, role = authorize(GET_ROLES)
    f_item = request.args.get("reported_item_id")
    f_tenant = request.args.get("tenant_id")
    f_status = request.args.get("status")

    def pred(d):
        if role == "Tenant" and d["tenant_id"] != uid:
            return False
        if f_item is not None and d["reported_item_id"] != f_item:
            return False
        if f_tenant is not None and d["tenant_id"] != f_tenant:
            return False
        if f_status is not None and d["status"] != f_status:
            return False
        return True

    items = sorted_list(store.disputes, pred)
    page, pagination = paginate(items)
    return ok_array([serialize(x) for x in page], pagination)


@bp.post("/api/disputes/<did>/investigate")
def investigate_dispute(did):
    uid, role = authorize(["ComplianceAnalyst"])
    d = _load_dispute(did)
    if d["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", "dispute is not OPEN")
    d["status"] = "INVESTIGATING"
    d["analyst_user_id"] = uid
    d["investigation_deadline"] = store.clock_now() + timedelta(days=store.DISPUTE_INVESTIGATION_DAYS)
    store.touch(d)
    return ok_object(serialize(d))


@bp.post("/api/disputes/<did>/resolve")
def resolve_dispute(did):
    uid, role = authorize(["ComplianceOfficer"])
    d = _load_dispute(did)
    body = get_body()
    resolution = require_enum(body, "resolution", ["CORRECTED", "UPHELD"])
    corrected_on_time = None
    corrected_amount = None
    if resolution == "CORRECTED":
        # corrected_on_time and corrected_amount_cents are optional corrected
        # values; when a field is omitted the superseding tradeline inherits the
        # original's value for that field.
        if "corrected_on_time" in body and body["corrected_on_time"] is not None:
            cot = body["corrected_on_time"]
            if not isinstance(cot, bool):
                raise ApiError("ERR_INVALID_REQUEST", "corrected_on_time must be boolean")
            corrected_on_time = cot
        if "corrected_amount_cents" in body and body["corrected_amount_cents"] is not None:
            corrected_amount = require_int(body, "corrected_amount_cents")
            if corrected_amount < 0:
                raise ApiError("ERR_INVALID_REQUEST", "corrected_amount_cents must be >= 0")
    note = optional_str(body, "note")

    if d["status"] != "INVESTIGATING":
        raise ApiError("ERR_INVALID_STATE", "dispute is not INVESTIGATING")
    if uid == d["analyst_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", "resolver must differ from investigator")

    item = store.reported_items.get(d["reported_item_id"])
    d["officer_user_id"] = uid
    d["resolution_note"] = note

    if resolution == "CORRECTED":
        d["status"] = "RESOLVED_CORRECTED"
        item["status"] = "CORRECTED"
        store.touch(item)
        _create_superseding(item, corrected_on_time, corrected_amount)
    else:  # UPHELD
        d["status"] = "RESOLVED_UPHELD"
        _reinstate_item(item)

    store.touch(d)
    calc.recompute_tenant(item["tenant_id"])
    return ok_object(serialize(d))


def _create_superseding(original, on_time, amount):
    if on_time is None:
        on_time = original["on_time"]
    if amount is None:
        amount = original["amount_reported_cents"]
    item = store.base_fields()
    item.update({
        "rent_payment_id": original["rent_payment_id"],
        "tenant_id": original["tenant_id"],
        "lease_id": original["lease_id"],
        "supersedes_item_id": original["id"],
        "period_month": original["period_month"],
        "on_time": on_time,
        "amount_reported_cents": amount,
        "source": original["source"],
        "status": "REPORTED",
        "bureau_statuses": {b: "FURNISHED" for b in store.BUREAUS},
    })
    store.reported_items[item["id"]] = item
    return item


@bp.post("/api/disputes/<did>/withdraw")
def withdraw_dispute(did):
    uid, role = authorize(["Tenant"])
    d = _load_dispute(did)
    require_tenant_owner(role, uid, d["tenant_id"])
    if d["status"] not in ("OPEN", "INVESTIGATING"):
        raise ApiError("ERR_INVALID_STATE", "dispute is not OPEN or INVESTIGATING")
    d["status"] = "WITHDRAWN"
    store.touch(d)
    item = store.reported_items.get(d["reported_item_id"])
    if item is not None and item["status"] == "DISPUTED":
        _reinstate_item(item)
    calc.recompute_tenant(d["tenant_id"])
    return ok_object(serialize(d))
