from flask import Blueprint
from core import (db, ApiError, auth, caller, body, ok, ok_list, touch,
                  as_enum, as_str, paginate, sort_seq)
import serial

bp = Blueprint("autopay", __name__)


def get_mandate_or_404(mid):
    m = db.autopay_mandates.get(mid)
    if m is None:
        raise ApiError("ERR_MANDATE_NOT_FOUND", 404, "Autopay mandate not found.")
    return m


def get_renter_or_404(rid):
    r = db.renters.get(rid)
    if r is None:
        raise ApiError("ERR_RENTER_NOT_FOUND", 404, "Renter not found.")
    return r


@bp.get("/api/renters/<rid>/autopay-mandate")
@auth("Renter", "PlatformAdmin")
def get_renter_mandate(rid):
    r = get_renter_or_404(rid)
    uid, role = caller()
    if role == "Renter" and r["id"] != uid:
        raise ApiError("ERR_OWNERSHIP_VIOLATION", 403, "Not your resource.")
    items = sort_seq([m for m in db.autopay_mandates.values() if m["renter_id"] == rid])
    page, limit, offset, total = paginate(items)
    return ok_list([serial.mandate_out(m) for m in page], limit, offset, total)


@bp.get("/api/autopay-mandates/<mid>")
@auth("Renter", "PlatformAdmin")
def get_mandate(mid):
    m = get_mandate_or_404(mid)
    uid, role = caller()
    if role == "Renter" and m["renter_id"] != uid:
        raise ApiError("ERR_OWNERSHIP_VIOLATION", 403, "Not your mandate.")
    return ok(serial.mandate_out(m))


@bp.patch("/api/autopay-mandates/<mid>")
@auth("Renter")
def patch_mandate(mid):
    b = body()
    new_status = as_enum(b, "status", {"PAUSED", "ACTIVE", "REVOKED"})
    method_ref = as_str(b, "method_ref", required=False)
    m = get_mandate_or_404(mid)
    uid, role = caller()
    if m["renter_id"] != uid:
        raise ApiError("ERR_OWNERSHIP_VIOLATION", 403, "Not your mandate.")

    cur = m["status"]
    renter = db.renters.get(m["renter_id"])

    # allowed transitions
    valid = {
        ("PAUSED", "ACTIVE"), ("PAUSED", "REVOKED"),
        ("ACTIVE", "PAUSED"), ("ACTIVE", "REVOKED"),
    }
    if (cur, new_status) not in valid:
        raise ApiError("ERR_INVALID_STATE", 409, "Mandate cannot transition.")

    if new_status == "ACTIVE":
        # activation requires a non-null method_ref (supplied now or already stored)
        if method_ref is not None:
            m["method_ref"] = method_ref
        if m["method_ref"] is None:
            raise ApiError("ERR_VALIDATION", 400,
                           "method_ref is required to activate the mandate.")
        m["status"] = "ACTIVE"
        if renter is not None:
            renter["autopay_enabled"] = True
            touch(renter)
    else:
        if method_ref is not None:
            m["method_ref"] = method_ref
        m["status"] = new_status
        if new_status in ("PAUSED", "REVOKED") and cur == "ACTIVE":
            if renter is not None:
                renter["autopay_enabled"] = False
                touch(renter)

    touch(m)
    return ok(serial.mandate_out(m))
