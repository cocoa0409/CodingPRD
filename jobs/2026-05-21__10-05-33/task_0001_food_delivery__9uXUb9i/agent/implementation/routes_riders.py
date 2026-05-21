"""Rider endpoints."""
from __future__ import annotations

from flask import Blueprint, g

from auth import require_roles
from common import get_json_body, require_str
from envelope import success
from errors import ApiError
from serializers import serialize_rider
import store
from store import gen_id, iso_z, lock, now


bp = Blueprint("riders", __name__, url_prefix="/api/riders")


def _find_rider(rid: str) -> dict:
    r = store.riders.get(rid)
    if not r:
        raise ApiError("ERR_NOT_FOUND", "Rider not found.")
    return r


@bp.post("")
@require_roles("PlatformAdmin")
def register_rider():
    body = get_json_body()
    name = require_str(body, "name", max_len=120)
    phone = require_str(body, "phone", max_len=40)
    with lock():
        for r in store.riders.values():
            if r["phone"] == phone:
                raise ApiError("ERR_VALIDATION", "Phone must be unique across riders.")
        t = now()
        rid = gen_id()
        rec = {
            "id": rid,
            "name": name,
            "phone": phone,
            "status": "OFFLINE",
            "on_time_rate": 1.0,
            "acceptance_rate": 1.0,
            "rating": 5.0,
            "wallet_balance_cents": 0,
            "bonus_tier": "BRONZE",
            "created_at": iso_z(t),
            "updated_at": iso_z(t),
            "version": 1,
        }
        store.riders[rid] = rec
        store.rider_history[rid] = {"deliveries": [], "offers": [], "ratings": []}
    return success(serialize_rider(rec), status=201)


@bp.get("/<rid>")
@require_roles("PlatformAdmin", "Rider", "CustomerService")
def read_rider(rid: str):
    r = _find_rider(rid)
    if g.role == "Rider" and g.user_id != r["id"]:
        raise ApiError("ERR_FORBIDDEN", "Rider identity mismatch.")
    return success(serialize_rider(r))


@bp.post("/<rid>/go-online")
@require_roles("Rider")
def go_online(rid: str):
    r = _find_rider(rid)
    if g.user_id != r["id"]:
        raise ApiError("ERR_FORBIDDEN", "Rider identity mismatch.")
    if r["status"] != "OFFLINE":
        raise ApiError("ERR_INVALID_STATE", "Rider can only go online from OFFLINE.")
    with lock():
        r["status"] = "AVAILABLE"
        r["updated_at"] = iso_z(now())
        r["version"] += 1
    return success(serialize_rider(r))


@bp.post("/<rid>/go-offline")
@require_roles("Rider")
def go_offline(rid: str):
    r = _find_rider(rid)
    if g.user_id != r["id"]:
        raise ApiError("ERR_FORBIDDEN", "Rider identity mismatch.")
    if r["status"] != "AVAILABLE":
        raise ApiError("ERR_INVALID_STATE", "Rider can only go offline from AVAILABLE.")
    # Cannot go offline if any active assignment OFFERED/ACCEPTED/PICKED_UP
    for a in store.assignments.values():
        if a["rider_id"] == r["id"] and a["status"] in ("OFFERED", "ACCEPTED", "PICKED_UP"):
            raise ApiError("ERR_INVALID_STATE", "Cannot go offline while active assignments exist.")
    with lock():
        r["status"] = "OFFLINE"
        r["updated_at"] = iso_z(now())
        r["version"] += 1
    return success(serialize_rider(r))


@bp.post("/<rid>/suspend")
@require_roles("PlatformAdmin")
def suspend_rider(rid: str):
    r = _find_rider(rid)
    if r["status"] != "AVAILABLE":
        raise ApiError("ERR_INVALID_STATE", "Only AVAILABLE riders can be suspended.")
    if not (r["on_time_rate"] < 0.70 or r["acceptance_rate"] < 0.50):
        raise ApiError("ERR_SUSPEND_CRITERIA_NOT_MET", "Rider performance thresholds not breached.")
    with lock():
        r["status"] = "SUSPENDED"
        r["updated_at"] = iso_z(now())
        r["version"] += 1
    return success(serialize_rider(r))
