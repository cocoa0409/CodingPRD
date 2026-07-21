from flask import Blueprint, request

import store
from common import (ApiError, authorize, ok_object, ok_array, serialize, paginate,
                    sorted_list, get_body, require_str, require_int, require_iso,
                    require_enum, optional_str, require_tenant_owner, require_landlord_owner)
from routes.enrollments import _resolve_fk

bp = Blueprint("leases", __name__)


def _overlaps(a_start, a_end, b_start, b_end):
    # half-open [start, end): overlap iff a_start < b_end and b_start < a_end
    return a_start < b_end and b_start < a_end


@bp.post("/api/leases")
def create_lease():
    uid, role = authorize(["Tenant", "PlatformAdmin"])
    body = get_body()
    tid = body.get("tenant_id")
    if role == "Tenant" and isinstance(tid, str) and tid != uid:
        raise ApiError("ERR_UNAUTHORIZED", "tenant may only create their own lease")
    tenant = _resolve_fk(body, "tenant_id", store.tenants, "ERR_TENANT_NOT_FOUND")
    landlord = _resolve_fk(body, "landlord_id", store.landlords, "ERR_LANDLORD_NOT_FOUND")

    property_address = require_str(body, "property_address")
    rent_amount_cents = require_int(body, "rent_amount_cents")
    if rent_amount_cents <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "rent_amount_cents must be > 0")
    monthly_due_day = require_int(body, "monthly_due_day")
    if monthly_due_day < 1 or monthly_due_day > 28:
        raise ApiError("ERR_INVALID_REQUEST", "monthly_due_day must be 1..28")
    lease_start = require_iso(body, "lease_start")
    lease_end = require_iso(body, "lease_end")

    # overlap against non-terminal leases for same (tenant_id, property_address)
    for other in store.leases.values():
        if (other["tenant_id"] == tenant["id"]
                and other["property_address"] == property_address
                and other["verification_status"] != "TERMINATED"):
            if _overlaps(lease_start, lease_end, other["lease_start"], other["lease_end"]):
                raise ApiError("ERR_LEASE_DATE_OVERLAP", "lease term overlaps an existing lease")

    l = store.base_fields()
    l.update({
        "tenant_id": tenant["id"],
        "landlord_id": landlord["id"],
        "property_address": property_address,
        "rent_amount_cents": rent_amount_cents,
        "monthly_due_day": monthly_due_day,
        "lease_start": lease_start,
        "lease_end": lease_end,
        "verification_status": "PENDING_VERIFICATION",
    })
    store.leases[l["id"]] = l
    return ok_object(serialize(l), 201)


def _load_lease(lid):
    l = store.leases.get(lid)
    if l is None:
        raise ApiError("ERR_LEASE_NOT_FOUND", "lease not found")
    return l


@bp.get("/api/leases/<lid>")
def get_lease(lid):
    uid, role = authorize(["Tenant", "Landlord", "PlatformAdmin"])
    l = _load_lease(lid)
    if role == "Tenant":
        require_tenant_owner(role, uid, l["tenant_id"])
    elif role == "Landlord":
        require_landlord_owner(role, uid, l["landlord_id"])
    return ok_object(serialize(l))


@bp.get("/api/leases")
def list_leases():
    uid, role = authorize(["Tenant", "Landlord", "PlatformAdmin"])
    tenant_id = request.args.get("tenant_id")
    landlord_id = request.args.get("landlord_id")
    vstatus = request.args.get("verification_status")

    def pred(l):
        if role == "Tenant" and l["tenant_id"] != uid:
            return False
        if role == "Landlord" and l["landlord_id"] != uid:
            return False
        if tenant_id is not None and l["tenant_id"] != tenant_id:
            return False
        if landlord_id is not None and l["landlord_id"] != landlord_id:
            return False
        if vstatus is not None and l["verification_status"] != vstatus:
            return False
        return True

    items = sorted_list(store.leases, pred)
    page, pagination = paginate(items)
    return ok_array([serialize(x) for x in page], pagination)


@bp.post("/api/leases/<lid>/verify")
def verify_lease(lid):
    uid, role = authorize(["Landlord", "PlatformAdmin"])
    l = _load_lease(lid)
    require_landlord_owner(role, uid, l["landlord_id"])
    body = get_body()
    decision = require_enum(body, "decision", ["VERIFIED", "REJECTED"])
    optional_str(body, "note")
    if l["verification_status"] != "PENDING_VERIFICATION":
        raise ApiError("ERR_ALREADY_VERIFIED", "lease is not pending verification")
    l["verification_status"] = "VERIFIED" if decision == "VERIFIED" else "REJECTED"
    store.touch(l)
    return ok_object(serialize(l))
