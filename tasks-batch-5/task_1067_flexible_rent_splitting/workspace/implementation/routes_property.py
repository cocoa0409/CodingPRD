from flask import Blueprint
from core import (db, ApiError, auth, caller, body, ok, ok_list, base_full, touch,
                  as_str, as_int, as_enum, paginate, sort_seq)
import serial

bp = Blueprint("property", __name__)

INTEG = {"PENDING", "ACTIVE", "SUSPENDED"}


def get_property_or_404(pid):
    p = db.properties.get(pid)
    if p is None:
        raise ApiError("ERR_PROPERTY_NOT_FOUND", 404, "Property not found.")
    return p


@bp.post("/api/properties")
@auth("PlatformAdmin")
def create_property():
    b = body()
    landlord_name = as_str(b, "landlord_name")
    unit_label = as_str(b, "unit_label")
    full_rent_cents = as_int(b, "full_rent_cents", positive=True)
    rent_due_day = as_int(b, "rent_due_day", minimum=1, maximum=28)
    remittance_account_ref = as_str(b, "remittance_account_ref")
    integration_status = as_enum(b, "integration_status", INTEG, required=False)
    if integration_status is None:
        integration_status = "PENDING"
    rec = base_full()
    rec.update({
        "landlord_name": landlord_name,
        "unit_label": unit_label,
        "full_rent_cents": full_rent_cents,
        "rent_due_day": rent_due_day,
        "remittance_account_ref": remittance_account_ref,
        "integration_status": integration_status,
        "status": integration_status,
    })
    db.properties[rec["id"]] = rec
    return ok(serial.property_out(rec), 201)


@bp.get("/api/properties/<pid>")
@auth("PlatformAdmin", "PropertyManager")
def get_property(pid):
    p = get_property_or_404(pid)
    uid, role = caller()
    if role == "PropertyManager" and p["id"] != uid:
        raise ApiError("ERR_OWNERSHIP_VIOLATION", 403, "Not your property.")
    return ok(serial.property_out(p))


@bp.get("/api/properties")
@auth("PlatformAdmin")
def list_properties():
    from flask import request
    status = request.args.get("status")
    items = [p for p in db.properties.values()
             if status is None or p["status"] == status]
    items = sort_seq(items)
    page, limit, offset, total = paginate(items)
    return ok_list([serial.property_out(p) for p in page], limit, offset, total)


@bp.patch("/api/properties/<pid>/integration")
@auth("PlatformAdmin")
def set_integration(pid):
    b = body()
    integration_status = as_enum(b, "integration_status", INTEG)
    p = get_property_or_404(pid)
    p["integration_status"] = integration_status
    p["status"] = integration_status
    touch(p)
    return ok(serial.property_out(p))


@bp.get("/api/properties/<pid>/remittances")
@auth("PlatformAdmin", "PropertyManager")
def property_remittances(pid):
    p = get_property_or_404(pid)
    uid, role = caller()
    if role == "PropertyManager" and p["id"] != uid:
        raise ApiError("ERR_OWNERSHIP_VIOLATION", 403, "Not your property.")
    items = sort_seq([r for r in db.remittances.values() if r["property_id"] == pid])
    page, limit, offset, total = paginate(items)
    return ok_list([serial.remittance_out(r) for r in page], limit, offset, total)
