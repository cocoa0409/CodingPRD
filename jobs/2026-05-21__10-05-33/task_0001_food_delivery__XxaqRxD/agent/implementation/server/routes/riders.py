"""Rider lifecycle endpoints."""
from __future__ import annotations

from flask import Blueprint, g, request

from ..auth import require_role
from ..envelope import success_object
from ..errors import ApiError
from ..ids import new_uuid
from ..serializers import rider_out
from ..validation import ensure_dict, require_str


bp = Blueprint("riders", __name__, url_prefix="/api")


@bp.post("/riders")
def register_rider():
    require_role("PlatformAdmin")
    store = g.store
    body = ensure_dict(request.get_json(silent=True) or {})
    name = require_str(body, "name", max_len=120)
    phone = require_str(body, "phone")
    with store.lock:
        if store.find_rider_by_phone(phone):
            raise ApiError("ERR_VALIDATION", "phone already in use")
        rid = new_uuid()
        now = store.now_iso()
        r = {
            "id": rid,
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
            # internal bookkeeping (stripped by serializer)
            "_offer_outcomes": [],
            "_on_time_history": [],
            "_rating_history": [],
            "_completed_count": 0,
        }
        store.riders[rid] = r
        return success_object(store.clock, rider_out(r), status=201)


@bp.get("/riders/<rid>")
def read_rider(rid: str):
    require_role("PlatformAdmin", "Rider", "CustomerService")
    store = g.store
    r = store.riders.get(rid)
    if not r:
        raise ApiError("ERR_NOT_FOUND")
    if g.user_role == "Rider" and g.user_id != rid:
        raise ApiError("ERR_FORBIDDEN")
    return success_object(store.clock, rider_out(r))


@bp.post("/riders/<rid>/go-online")
def go_online(rid: str):
    require_role("Rider")
    store = g.store
    with store.lock:
        r = store.riders.get(rid)
        if not r:
            raise ApiError("ERR_NOT_FOUND")
        if g.user_id != rid:
            raise ApiError("ERR_FORBIDDEN")
        if r["status"] != "OFFLINE":
            raise ApiError("ERR_INVALID_STATE")
        r["status"] = "AVAILABLE"
        r["version"] += 1
        r["updated_at"] = store.now_iso()
        return success_object(store.clock, rider_out(r))


@bp.post("/riders/<rid>/go-offline")
def go_offline(rid: str):
    require_role("Rider")
    store = g.store
    with store.lock:
        r = store.riders.get(rid)
        if not r:
            raise ApiError("ERR_NOT_FOUND")
        if g.user_id != rid:
            raise ApiError("ERR_FORBIDDEN")
        if r["status"] != "AVAILABLE":
            raise ApiError("ERR_INVALID_STATE")
        # Refuse if any active assignment references this rider.
        for a in store.assignments.values():
            if a["rider_id"] == rid and a["status"] in ("OFFERED", "ACCEPTED", "PICKED_UP"):
                raise ApiError("ERR_INVALID_STATE")
        r["status"] = "OFFLINE"
        r["version"] += 1
        r["updated_at"] = store.now_iso()
        return success_object(store.clock, rider_out(r))


@bp.post("/riders/<rid>/suspend")
def suspend_rider(rid: str):
    require_role("PlatformAdmin")
    store = g.store
    with store.lock:
        r = store.riders.get(rid)
        if not r:
            raise ApiError("ERR_NOT_FOUND")
        if r["status"] != "AVAILABLE":
            raise ApiError("ERR_INVALID_STATE")
        if r["on_time_rate"] >= 0.70 and r["acceptance_rate"] >= 0.50:
            raise ApiError("ERR_SUSPEND_CRITERIA_NOT_MET")
        r["status"] = "SUSPENDED"
        r["version"] += 1
        r["updated_at"] = store.now_iso()
        return success_object(store.clock, rider_out(r))
