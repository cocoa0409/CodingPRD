from flask import Blueprint

from ..auth import require_role
from ..envelope import success, created
from ..errors import err
from ..repository import base_versioned, touch, check_version, body_or_empty
from ..store import store

bp = Blueprint("riders", __name__)


def _view(r):
    return {k: r[k] for k in (
        "id", "name", "phone", "status",
        "on_time_rate", "acceptance_rate", "rating",
        "wallet_balance_cents", "bonus_tier",
        "created_at", "updated_at", "version",
    )}


@bp.post("/api/riders")
def register_rider():
    require_role("PlatformAdmin")
    body = body_or_empty()
    name = body.get("name")
    phone = body.get("phone")
    if not isinstance(name, str) or not name.strip():
        raise err("ERR_VALIDATION", "name required")
    if not isinstance(phone, str) or not phone.strip():
        raise err("ERR_VALIDATION", "phone required")
    for existing in store.riders.values():
        if existing["phone"] == phone:
            raise err("ERR_VALIDATION", "phone already in use")
    r = base_versioned()
    r.update({
        "name": name,
        "phone": phone,
        "status": "OFFLINE",
        "on_time_rate": 1.0,
        "acceptance_rate": 1.0,
        "rating": 5.0,
        "wallet_balance_cents": 0,
        "bonus_tier": "BRONZE",
    })
    store.riders[r["id"]] = r
    return created(_view(r))


@bp.get("/api/riders/<rid>")
def get_rider(rid):
    uid, role = require_role("PlatformAdmin", "Rider", "CustomerService")
    r = store.riders.get(rid)
    if r is None:
        raise err("ERR_NOT_FOUND", "rider not found")
    if role == "Rider" and r["id"] != uid:
        raise err("ERR_FORBIDDEN", "not the same rider")
    return success(_view(r))


@bp.post("/api/riders/<rid>/go-online")
def go_online(rid):
    uid, role = require_role("Rider")
    r = store.riders.get(rid)
    if r is None:
        raise err("ERR_NOT_FOUND", "rider not found")
    if r["id"] != uid:
        raise err("ERR_FORBIDDEN", "not the same rider")
    if r["status"] != "OFFLINE":
        raise err("ERR_INVALID_STATE", "not in OFFLINE")
    body = body_or_empty()
    check_version(r, body)
    r["status"] = "AVAILABLE"
    touch(r)
    return success(_view(r))


@bp.post("/api/riders/<rid>/go-offline")
def go_offline(rid):
    uid, role = require_role("Rider")
    r = store.riders.get(rid)
    if r is None:
        raise err("ERR_NOT_FOUND", "rider not found")
    if r["id"] != uid:
        raise err("ERR_FORBIDDEN", "not the same rider")
    if r["status"] != "AVAILABLE":
        raise err("ERR_INVALID_STATE", "not in AVAILABLE")
    # Block if any active assignment exists for this rider
    for a in store.assignments.values():
        if a["rider_id"] == rid and a["status"] in ("OFFERED", "ACCEPTED", "PICKED_UP"):
            raise err("ERR_INVALID_STATE", "active assignment exists")
    body = body_or_empty()
    check_version(r, body)
    r["status"] = "OFFLINE"
    touch(r)
    return success(_view(r))


@bp.post("/api/riders/<rid>/suspend")
def suspend_rider(rid):
    require_role("PlatformAdmin")
    r = store.riders.get(rid)
    if r is None:
        raise err("ERR_NOT_FOUND", "rider not found")
    if r["status"] != "AVAILABLE":
        raise err("ERR_INVALID_STATE", "not in AVAILABLE")
    body = body_or_empty()
    check_version(r, body)
    if r["on_time_rate"] >= 0.70 and r["acceptance_rate"] >= 0.50:
        raise err("ERR_SUSPEND_CRITERIA_NOT_MET", "metrics within thresholds")
    r["status"] = "SUSPENDED"
    touch(r)
    return success(_view(r))
