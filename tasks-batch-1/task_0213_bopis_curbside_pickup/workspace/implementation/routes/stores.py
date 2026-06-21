"""Store endpoints + store-scoped reverse-navigation lists."""

from flask import Blueprint, request

from db import db, stamp_common
from errors import err
from middleware import require_auth, get_json_body
from response import object_response, array_response
from services.common import (
    require_str, require_int, get_or_404, parse_pagination, paginate,
    ser_store, ser_slot, ser_inventory, ser_checkin, ser_hold,
)

bp = Blueprint("stores", __name__)


@bp.post("/stores")
def create_store():
    require_auth({"PlatformAdmin"})
    body = get_json_body()
    name = require_str(body, "name")
    state_code = require_str(body, "state_code")
    if len(state_code) != 2:
        raise err("ERR_INVALID_REQUEST", "state_code must be exactly 2 characters")
    curbside_spaces = require_int(body, "curbside_spaces")
    if curbside_spaces < 1:
        raise err("ERR_INVALID_REQUEST", "curbside_spaces must be >= 1")
    hold_window_minutes = 120
    if "hold_window_minutes" in body and body["hold_window_minutes"] is not None:
        hold_window_minutes = require_int(body, "hold_window_minutes")
        if hold_window_minutes < 1:
            raise err("ERR_INVALID_REQUEST", "hold_window_minutes must be >= 1")

    rec = {
        "name": name,
        "state_code": state_code,
        "curbside_spaces": curbside_spaces,
        "hold_window_minutes": hold_window_minutes,
        "active_curbside_count": 0,
    }
    stamp_common(rec)
    db.stores[rec["id"]] = rec
    return object_response(ser_store(rec), 201)


@bp.get("/stores/<sid>")
def get_store(sid):
    require_auth({"Customer", "StorePicker", "StoreAssociate",
                  "StoreManager", "PlatformAdmin"})
    rec = get_or_404(db.stores, sid)
    return object_response(ser_store(rec))


@bp.get("/stores/<sid>/pickup-slots")
def list_store_slots(sid):
    require_auth({"Customer", "StorePicker", "StoreManager", "PlatformAdmin"})
    get_or_404(db.stores, sid)
    limit, offset = parse_pagination(request.args)
    items = [s for s in db.pickup_slots.values() if s["store_id"] == sid]
    page, total = paginate(items, limit, offset)
    return array_response([ser_slot(s) for s in page], limit, offset, total)


@bp.get("/stores/<sid>/inventory")
def list_store_inventory(sid):
    require_auth({"Customer", "StorePicker", "StoreManager", "PlatformAdmin"})
    get_or_404(db.stores, sid)
    limit, offset = parse_pagination(request.args)
    items = [i for i in db.store_inventory.values() if i["store_id"] == sid]
    page, total = paginate(items, limit, offset)
    return array_response([ser_inventory(i) for i in page], limit, offset, total)


@bp.get("/stores/<sid>/curbside-checkins")
def list_store_checkins(sid):
    require_auth({"StoreAssociate", "StoreManager", "PlatformAdmin"})
    get_or_404(db.stores, sid)
    limit, offset = parse_pagination(request.args)
    items = [c for c in db.curbside_checkins.values() if c["store_id"] == sid]
    page, total = paginate(items, limit, offset)
    return array_response([ser_checkin(c) for c in page], limit, offset, total)


@bp.get("/stores/<sid>/holds")
def list_store_holds(sid):
    require_auth({"StorePicker", "StoreAssociate", "StoreManager", "PlatformAdmin"})
    get_or_404(db.stores, sid)
    limit, offset = parse_pagination(request.args)
    items = [h for h in db.holds.values() if h["store_id"] == sid]
    page, total = paginate(items, limit, offset)
    return array_response([ser_hold(h) for h in page], limit, offset, total)
