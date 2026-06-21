"""Stylists and styling appointments (PRD §3.4)."""
from flask import Blueprint, request

import errors
from db import db, stamp_new, touch
from errors import err
from middleware import authenticate, require_role, get_json_body
from response import success, list_success
from services.common import (
    get_or_404, require_str, require_int, require_enum, validate_interval,
    parse_pagination, paginate, serialize, serialize_list,
)

bp = Blueprint("stylists", __name__)


def _appointments_collide(s1, e1, s2, e2, buffer_minutes):
    """Closed-buffer overlap: the cleanup gap is enforced on both sides, so two
    appointments collide unless separated by at least buffer_minutes."""
    return s1 < e2 + buffer_minutes and s2 < e1 + buffer_minutes


# --- Stylists ---

@bp.post("/stylists")
def create_stylist():
    _, role = authenticate()
    require_role(role, {"StoreManager"})
    body = get_json_body()
    boutique_id = require_str(body, "boutique_id")
    full_name = require_str(body, "full_name")
    buffer_minutes = require_int(body, "buffer_minutes", required=False, default=15)
    if buffer_minutes < 0:
        raise err(errors.ERR_INVALID_REQUEST, "buffer_minutes must be >= 0")
    get_or_404("boutique", boutique_id)
    rec = stamp_new({
        "boutique_id": boutique_id,
        "full_name": full_name,
        "buffer_minutes": buffer_minutes,
        "status": "ACTIVE",
    })
    db.stylists[rec["id"]] = rec
    return success(serialize(rec), 201)


@bp.get("/stylists/<rid>")
def get_stylist(rid):
    _, role = authenticate()
    require_role(role, {"StoreManager", "StoreAssociate", "Customer"})
    rec = get_or_404("stylist", rid)
    return success(serialize(rec))


@bp.get("/stylists")
def list_stylists():
    _, role = authenticate()
    require_role(role, {"StoreManager", "StoreAssociate", "Customer"})
    limit, offset = parse_pagination()
    items = list(db.stylists.values())
    boutique_id = request.args.get("boutique_id")
    if boutique_id is not None:
        items = [s for s in items if s["boutique_id"] == boutique_id]
    window, total = paginate(items, limit, offset)
    return list_success(serialize_list(window), limit, offset, total)


@bp.post("/stylists/<rid>/status")
def set_stylist_status(rid):
    _, role = authenticate()
    require_role(role, {"StoreManager"})
    stylist = get_or_404("stylist", rid)
    body = get_json_body()
    status = require_enum(body, "status", {"ACTIVE", "OFF"})
    stylist["status"] = status
    touch(stylist)
    return success(serialize(stylist))


# --- Styling appointments ---

@bp.post("/styling-appointments")
def create_appointment():
    user_id, role = authenticate()
    require_role(role, {"StoreAssociate", "Customer"})
    body = get_json_body()
    stylist_id = require_str(body, "stylist_id")
    customer_id = require_str(body, "customer_id")
    get_or_404("stylist", stylist_id)
    customer = get_or_404("customer", customer_id)
    if role == "Customer" and user_id != customer["id"]:
        raise err(errors.ERR_NOT_RESOURCE_OWNER, "not the resource owner")
    start_minute = require_int(body, "start_minute")
    end_minute = require_int(body, "end_minute")
    validate_interval(start_minute, end_minute)
    rec = stamp_new({
        "stylist_id": stylist_id,
        "customer_id": customer_id,
        "start_minute": start_minute,
        "end_minute": end_minute,
        "status": "REQUESTED",
    })
    db.styling_appointments[rec["id"]] = rec
    return success(serialize(rec), 201)


@bp.get("/styling-appointments/<rid>")
def get_appointment(rid):
    _, role = authenticate()
    require_role(role, {"StoreManager", "StoreAssociate", "Customer"})
    rec = get_or_404("styling_appointment", rid)
    return success(serialize(rec))


@bp.get("/stylists/<rid>/appointments")
def list_stylist_appointments(rid):
    _, role = authenticate()
    require_role(role, {"StoreManager", "StoreAssociate", "Customer"})
    get_or_404("stylist", rid)
    limit, offset = parse_pagination()
    items = [a for a in db.styling_appointments.values() if a["stylist_id"] == rid]
    window, total = paginate(items, limit, offset)
    return list_success(serialize_list(window), limit, offset, total)


@bp.get("/styling-appointments")
def list_appointments():
    _, role = authenticate()
    require_role(role, {"StoreManager", "StoreAssociate", "Customer"})
    limit, offset = parse_pagination()
    items = list(db.styling_appointments.values())
    customer_id = request.args.get("customer_id")
    if customer_id is not None:
        items = [a for a in items if a["customer_id"] == customer_id]
    window, total = paginate(items, limit, offset)
    return list_success(serialize_list(window), limit, offset, total)


@bp.post("/styling-appointments/<rid>/confirm")
def confirm_appointment(rid):
    _, role = authenticate()
    require_role(role, {"StoreAssociate"})
    appt = get_or_404("styling_appointment", rid)
    if appt["status"] != "REQUESTED":
        raise err(errors.ERR_INVALID_STATE, "confirm requires REQUESTED")
    stylist = db.stylists[appt["stylist_id"]]
    # Stylist-active check (priority 10) BEFORE double-booking (priority 11).
    if stylist["status"] != "ACTIVE":
        raise err(errors.ERR_STYLIST_NOT_ACTIVE, "stylist is not active")
    buffer_minutes = stylist["buffer_minutes"]
    for other in db.styling_appointments.values():
        if other["id"] == appt["id"]:
            continue
        if other["stylist_id"] != stylist["id"]:
            continue
        if other["status"] != "CONFIRMED":
            continue
        if _appointments_collide(
            appt["start_minute"], appt["end_minute"],
            other["start_minute"], other["end_minute"], buffer_minutes,
        ):
            raise err(errors.ERR_STYLIST_DOUBLE_BOOKED, "appointment collides within buffer")
    appt["status"] = "CONFIRMED"
    touch(appt)
    return success(serialize(appt))


@bp.post("/styling-appointments/<rid>/cancel")
def cancel_appointment(rid):
    user_id, role = authenticate()
    require_role(role, {"StoreAssociate", "Customer"})
    appt = get_or_404("styling_appointment", rid)
    if role == "Customer" and user_id != appt["customer_id"]:
        raise err(errors.ERR_NOT_RESOURCE_OWNER, "not the resource owner")
    if appt["status"] not in ("REQUESTED", "CONFIRMED"):
        raise err(errors.ERR_INVALID_STATE, "cancel requires REQUESTED or CONFIRMED")
    appt["status"] = "CANCELLED"
    touch(appt)
    return success(serialize(appt))


@bp.post("/styling-appointments/<rid>/complete")
def complete_appointment(rid):
    _, role = authenticate()
    require_role(role, {"StoreAssociate"})
    appt = get_or_404("styling_appointment", rid)
    if appt["status"] != "CONFIRMED":
        raise err(errors.ERR_INVALID_STATE, "complete requires CONFIRMED")
    appt["status"] = "COMPLETED"
    touch(appt)
    return success(serialize(appt))


@bp.post("/styling-appointments/<rid>/no-show")
def no_show_appointment(rid):
    _, role = authenticate()
    require_role(role, {"StoreAssociate"})
    appt = get_or_404("styling_appointment", rid)
    if appt["status"] != "CONFIRMED":
        raise err(errors.ERR_INVALID_STATE, "no-show requires CONFIRMED")
    appt["status"] = "NO_SHOW"
    touch(appt)
    return success(serialize(appt))
