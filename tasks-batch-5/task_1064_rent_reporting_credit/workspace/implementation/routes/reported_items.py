from flask import Blueprint, request

import store
import calc
from common import (ApiError, authorize, ok_object, ok_array, serialize, paginate,
                    sorted_list, get_body, optional_str, require_tenant_owner)

bp = Blueprint("reported_items", __name__)

GET_ROLES = ["Tenant", "ComplianceAnalyst", "ComplianceOfficer", "PlatformAdmin"]


def _load_item(rid):
    r = store.reported_items.get(rid)
    if r is None:
        raise ApiError("ERR_REPORTED_ITEM_NOT_FOUND", "reported item not found")
    return r


@bp.get("/api/reported-items/<rid>")
def get_item(rid):
    uid, role = authorize(GET_ROLES)
    r = _load_item(rid)
    require_tenant_owner(role, uid, r["tenant_id"])
    return ok_object(serialize(r))


@bp.get("/api/reported-items")
def list_items():
    uid, role = authorize(GET_ROLES)
    f_payment = request.args.get("rent_payment_id")
    f_tenant = request.args.get("tenant_id")
    f_lease = request.args.get("lease_id")
    f_supersedes = request.args.get("supersedes_item_id")
    f_status = request.args.get("status")

    def pred(r):
        if role == "Tenant" and r["tenant_id"] != uid:
            return False
        if f_payment is not None and r["rent_payment_id"] != f_payment:
            return False
        if f_tenant is not None and r["tenant_id"] != f_tenant:
            return False
        if f_lease is not None and r["lease_id"] != f_lease:
            return False
        if f_supersedes is not None and r["supersedes_item_id"] != f_supersedes:
            return False
        if f_status is not None and r["status"] != f_status:
            return False
        return True

    items = sorted_list(store.reported_items, pred)
    page, pagination = paginate(items)
    return ok_array([serialize(x) for x in page], pagination)


@bp.post("/api/reported-items/<rid>/retract")
def retract_item(rid):
    uid, role = authorize(["ComplianceOfficer"])
    r = _load_item(rid)
    get_body()  # optional reason ignored (audit-only)
    if r["status"] != "REPORTED":
        raise ApiError("ERR_INVALID_STATE", "item is not in REPORTED state")
    r["status"] = "RETRACTED"
    r["bureau_statuses"] = {b: "DELETED" for b in store.BUREAUS}
    store.touch(r)
    calc.recompute_tenant(r["tenant_id"])
    return ok_object(serialize(r))
