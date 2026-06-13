"""Customer + Vehicle endpoints (PRD §3.1)."""
from flask import Blueprint, request

from db import store
from errors import err
from middleware import get_principal, require_roles
from response import success_array, success_object
from services.pagination import paginate
from services.records import make_record, touch
from services.serialize import (
    serialize_customer,
    serialize_reservation,
    serialize_vehicle,
)
from services.validate import require_object, require_str

bp = Blueprint("customers", __name__)


@bp.post("/customers")
def create_customer():
    _, role = get_principal()
    require_roles(role, {"FacilityAdmin"})

    body = require_object(request.get_json(silent=True) or {})
    email = require_str(body, "email")
    full_name = require_str(body, "full_name")

    # Email unique across customers, case-insensitive.
    lowered = email.lower()
    for c in store.customers.values():
        if c["email"].lower() == lowered:
            raise err("ERR_VALIDATION", "Email already registered.")

    rec = make_record(
        {
            "email": email,
            "full_name": full_name,
            "no_show_strikes": 0,
            "status": "ACTIVE",
        }
    )
    store.customers[rec["id"]] = rec
    return success_object(serialize_customer(rec), status=201)


@bp.get("/customers/<cid>")
def get_customer(cid):
    _, role = get_principal()
    require_roles(role, {"FacilityAdmin", "Customer"})
    rec = store.customers.get(cid)
    if rec is None:
        raise err("ERR_NOT_FOUND")
    return success_object(serialize_customer(rec))


@bp.post("/customers/<cid>/reinstate")
def reinstate_customer(cid):
    _, role = get_principal()
    require_roles(role, {"FacilityAdmin"})
    rec = store.customers.get(cid)
    if rec is None:
        raise err("ERR_NOT_FOUND")
    rec["status"] = "ACTIVE"
    rec["no_show_strikes"] = 0
    touch(rec)
    return success_object(serialize_customer(rec))


@bp.get("/customers/<cid>/reservations")
def list_customer_reservations(cid):
    user_id, role = get_principal()
    require_roles(role, {"FacilityAdmin", "Customer"})
    rec = store.customers.get(cid)
    if rec is None:
        raise err("ERR_NOT_FOUND")
    # Ownership: a Customer may only read their own.
    if role == "Customer" and user_id != cid:
        raise err("ERR_NOT_RESOURCE_OWNER")
    matches = [r for r in store.reservations.values() if r["customer_id"] == cid]
    page, total, limit, offset = paginate(matches)
    return success_array(
        [serialize_reservation(r) for r in page], limit, offset, total
    )


@bp.get("/customers/<cid>/vehicles")
def list_customer_vehicles(cid):
    user_id, role = get_principal()
    require_roles(role, {"FacilityAdmin", "Customer"})
    rec = store.customers.get(cid)
    if rec is None:
        raise err("ERR_NOT_FOUND")
    if role == "Customer" and user_id != cid:
        raise err("ERR_NOT_RESOURCE_OWNER")
    matches = [v for v in store.vehicles.values() if v["customer_id"] == cid]
    page, total, limit, offset = paginate(matches)
    return success_array([serialize_vehicle(v) for v in page], limit, offset, total)


# ---- Vehicles ----
@bp.post("/vehicles")
def create_vehicle():
    user_id, role = get_principal()
    require_roles(role, {"Customer", "FacilityAdmin"})

    body = require_object(request.get_json(silent=True) or {})
    customer_id = require_str(body, "customer_id")
    plate = require_str(body, "plate")
    from services.validate import optional_bool, require_enum

    size_class = require_enum(body, "size_class", {"STANDARD", "OVERSIZED"})
    is_ev = optional_bool(body, "is_ev", False)

    # Ownership precedes existence per validation priority (§1.4 priority 3 < 4).
    if role == "Customer" and user_id != customer_id:
        raise err("ERR_NOT_RESOURCE_OWNER")
    if customer_id not in store.customers:
        raise err("ERR_NOT_FOUND")

    # Plate unique within owner.
    for v in store.vehicles.values():
        if v["customer_id"] == customer_id and v["plate"] == plate:
            raise err("ERR_VALIDATION", "Plate already registered for this owner.")

    rec = make_record(
        {
            "customer_id": customer_id,
            "plate": plate,
            "size_class": size_class,
            "is_ev": is_ev,
        }
    )
    store.vehicles[rec["id"]] = rec
    return success_object(serialize_vehicle(rec), status=201)


@bp.get("/vehicles/<vid>")
def get_vehicle(vid):
    _, role = get_principal()
    require_roles(role, {"Customer", "FacilityAdmin"})
    rec = store.vehicles.get(vid)
    if rec is None:
        raise err("ERR_NOT_FOUND")
    return success_object(serialize_vehicle(rec))
