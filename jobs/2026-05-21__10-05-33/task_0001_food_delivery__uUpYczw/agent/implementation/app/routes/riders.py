"""Rider endpoints."""
from __future__ import annotations

from flask import Blueprint

from .. import cascade
from ..auth import require_role
from ..envelope import envelope_object, expect_json_body
from ..errors import ApiError
from ..ids import new_uuid
from ..store import get_clock, get_store
from ..validators import req_str

bp = Blueprint("riders", __name__, url_prefix="/api")


RIDER_STATUSES = {"OFFLINE", "AVAILABLE", "ON_DELIVERY", "SUSPENDED"}


def _ensure_rider(store, rid):
    rec = store.riders.get(rid)
    if not rec:
        raise ApiError("ERR_NOT_FOUND", f"Rider {rid} not found")
    return rec


def _new_rider(name, phone, clock):
    now = clock.now_iso()
    return {
        "id": new_uuid(),
        "name": name,
        "phone": phone,
        "status": "OFFLINE",
        "on_time_rate": 1.0,
        "acceptance_rate": 1.0,
        "rating": 5.0,
        "wallet_balance_cents": 0,
        "bonus_tier": "BRONZE",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }


@bp.post("/riders")
def register_rider():
    require_role({"PlatformAdmin"})
    body = expect_json_body()
    name = req_str(body, "name").strip()
    phone = req_str(body, "phone").strip()
    if not name or not phone:
        raise ApiError("ERR_VALIDATION", "name/phone required")
    store = get_store()
    with store.lock:
        if phone in store.rider_phones:
            raise ApiError("ERR_VALIDATION", "rider phone already in use")
        rec = _new_rider(name, phone, get_clock())
        store.riders[rec["id"]] = rec
        store.rider_phones.add(phone)
    return envelope_object(rec, status=201)


@bp.get("/riders/<rid>")
def read_rider(rid):
    uid, role = require_role({"PlatformAdmin", "Rider", "CustomerService"})
    store = get_store()
    with store.lock:
        rec = _ensure_rider(store, rid)
        if role == "Rider" and uid != rec["id"]:
            raise ApiError("ERR_FORBIDDEN", "Rider may only read own record")
    return envelope_object(rec)


@bp.post("/riders/<rid>/go-online")
def go_online(rid):
    uid, _ = require_role({"Rider"})
    store = get_store()
    with store.lock:
        rec = _ensure_rider(store, rid)
        if uid != rec["id"]:
            raise ApiError("ERR_FORBIDDEN", "Rider may only act on self")
        if rec["status"] != "OFFLINE":
            raise ApiError("ERR_INVALID_STATE", "rider not OFFLINE")
        rec["status"] = "AVAILABLE"
        cascade.touch(rec, get_clock())
    return envelope_object(rec)


@bp.post("/riders/<rid>/go-offline")
def go_offline(rid):
    uid, _ = require_role({"Rider"})
    store = get_store()
    with store.lock:
        rec = _ensure_rider(store, rid)
        if uid != rec["id"]:
            raise ApiError("ERR_FORBIDDEN", "Rider may only act on self")
        if rec["status"] != "AVAILABLE":
            raise ApiError("ERR_INVALID_STATE", "rider not AVAILABLE")
        # No live assignments allowed
        for a in store.assignments.values():
            if a["rider_id"] == rid and a["status"] in {"OFFERED", "ACCEPTED", "PICKED_UP"}:
                raise ApiError("ERR_INVALID_STATE", "rider has active assignments")
        rec["status"] = "OFFLINE"
        cascade.touch(rec, get_clock())
    return envelope_object(rec)


@bp.post("/riders/<rid>/suspend")
def suspend_rider(rid):
    require_role({"PlatformAdmin"})
    store = get_store()
    with store.lock:
        rec = _ensure_rider(store, rid)
        if rec["status"] != "AVAILABLE":
            raise ApiError("ERR_INVALID_STATE", "rider not AVAILABLE")
        if not (rec["on_time_rate"] < 0.70 or rec["acceptance_rate"] < 0.50):
            raise ApiError("ERR_SUSPEND_CRITERIA_NOT_MET", "rider performance OK")
        rec["status"] = "SUSPENDED"
        cascade.touch(rec, get_clock())
    return envelope_object(rec)
