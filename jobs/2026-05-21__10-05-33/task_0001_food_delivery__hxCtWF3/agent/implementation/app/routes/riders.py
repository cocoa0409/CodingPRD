"""Rider registration and lifecycle."""
from flask import request

from ..auth import parse_headers, require_role
from ..envelope import success
from ..errors import fail
from ..resource import stamp_new, bump
from ..server import store


def register(app, prefix):
    app.add_url_rule("/api/riders", endpoint=f"{prefix}.create", view_func=create, methods=["POST"])
    app.add_url_rule("/api/riders/<rid>", endpoint=f"{prefix}.read", view_func=read, methods=["GET"])
    app.add_url_rule("/api/riders/<rid>/go-online", endpoint=f"{prefix}.go_online", view_func=go_online, methods=["POST"])
    app.add_url_rule("/api/riders/<rid>/go-offline", endpoint=f"{prefix}.go_offline", view_func=go_offline, methods=["POST"])
    app.add_url_rule("/api/riders/<rid>/suspend", endpoint=f"{prefix}.suspend", view_func=suspend, methods=["POST"])


def create():
    parse_headers()
    require_role("PlatformAdmin")
    body = request.get_json(silent=True) or {}
    name = body.get("name")
    phone = body.get("phone")
    if not isinstance(name, str) or not name.strip():
        raise fail("ERR_VALIDATION", "name required")
    if not isinstance(phone, str) or not phone.strip():
        raise fail("ERR_VALIDATION", "phone required")
    if phone in store.rider_phone:
        raise fail("ERR_VALIDATION", "rider phone already registered")
    rec = stamp_new()
    rec.update({
        "name": name,
        "phone": phone,
        "status": "OFFLINE",
        "on_time_rate": 1.0,
        "acceptance_rate": 1.0,
        "rating": 5.0,
        "wallet_balance_cents": 0,
        "bonus_tier": "BRONZE",
        "completed_deliveries": 0,
        "_recent_on_time": [],   # list[bool], cap 30
        "_recent_offers": [],    # list[bool], cap 30 (True=ACCEPTED)
        "_recent_ratings": [],   # list[float], cap 30
    })
    store.riders[rec["id"]] = rec
    store.rider_phone[phone] = rec["id"]
    return success(rec, status=201)


def _public(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def read(rid):
    user_id, role = parse_headers()
    require_role("PlatformAdmin", "Rider", "CustomerService")
    r = store.riders.get(rid)
    if not r:
        raise fail("ERR_NOT_FOUND")
    if role == "Rider" and user_id != r["id"]:
        raise fail("ERR_FORBIDDEN")
    return success(_public(r))


def _load_rider_for_action(rid):
    user_id, role = parse_headers()
    r = store.riders.get(rid)
    if not r:
        raise fail("ERR_NOT_FOUND")
    return user_id, role, r


def go_online(rid):
    user_id, role, r = _load_rider_for_action(rid)
    require_role("Rider")
    if user_id != r["id"]:
        raise fail("ERR_FORBIDDEN")
    if r["status"] != "OFFLINE":
        raise fail("ERR_INVALID_STATE")
    r["status"] = "AVAILABLE"
    bump(r)
    return success(_public(r))


def go_offline(rid):
    user_id, role, r = _load_rider_for_action(rid)
    require_role("Rider")
    if user_id != r["id"]:
        raise fail("ERR_FORBIDDEN")
    if r["status"] != "AVAILABLE":
        raise fail("ERR_INVALID_STATE")
    for a in store.assignments.values():
        if a["rider_id"] == r["id"] and a["status"] in ("OFFERED", "ACCEPTED", "PICKED_UP"):
            raise fail("ERR_INVALID_STATE")
    r["status"] = "OFFLINE"
    bump(r)
    return success(_public(r))


def suspend(rid):
    parse_headers()
    require_role("PlatformAdmin")
    r = store.riders.get(rid)
    if not r:
        raise fail("ERR_NOT_FOUND")
    if r["status"] != "AVAILABLE":
        raise fail("ERR_INVALID_STATE")
    if not (r["on_time_rate"] < 0.70 or r["acceptance_rate"] < 0.50):
        raise fail("ERR_SUSPEND_CRITERIA_NOT_MET")
    r["status"] = "SUSPENDED"
    bump(r)
    return success(_public(r))
