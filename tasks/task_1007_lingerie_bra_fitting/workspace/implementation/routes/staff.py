"""Fitter and FittingRoom endpoints."""
from flask import Blueprint

import store
import api as h
import serialize as s

bp = Blueprint("staff", __name__)


def _bool(body, field, default):
    v = body.get(field, default)
    if not isinstance(v, bool):
        raise h.ApiError("ERR_VALIDATION", f"{field} must be boolean")
    return v


@bp.post("/boutique/fitters")
def create_fitter():
    h.require_role("StoreManager")
    body = h.get_body()
    h.require_fields(body, ["full_name"])
    if not isinstance(body["full_name"], str):
        raise h.ApiError("ERR_VALIDATION", "full_name must be a string")
    rec = store.new_record({
        "full_name": body["full_name"],
        "post_surgical_certified": _bool(body, "post_surgical_certified", False),
        "is_active": _bool(body, "is_active", True),
    })
    store.fitters[rec["id"]] = rec
    return h.success(s.fitter_out(rec), status=201)


@bp.get("/boutique/fitters/<fid>")
def get_fitter(fid):
    h.require_role("Customer", "Fitter", "StoreManager", "BillingClerk")
    rec = h.lookup("fitters", fid)
    return h.success(s.fitter_out(rec))


@bp.post("/boutique/rooms")
def create_room():
    h.require_role("StoreManager")
    body = h.get_body()
    h.require_fields(body, ["room_name", "capacity"])
    if not isinstance(body["room_name"], str):
        raise h.ApiError("ERR_VALIDATION", "room_name must be a string")
    capacity = h.require_int(body, "capacity", minimum=1)
    rec = store.new_record({
        "room_name": body["room_name"],
        "capacity": capacity,
        "is_private": _bool(body, "is_private", False),
        "is_active": _bool(body, "is_active", True),
    })
    store.rooms[rec["id"]] = rec
    return h.success(s.room_out(rec), status=201)


@bp.get("/boutique/rooms/<rid>")
def get_room(rid):
    h.require_role("Customer", "Fitter", "StoreManager", "BillingClerk")
    rec = h.lookup("rooms", rid)
    return h.success(s.room_out(rec))
