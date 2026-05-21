"""Restaurant + restaurant-level endpoints."""
from __future__ import annotations

from flask import Blueprint

from ..auth import require_role, caller
from ..envelope import envelope_object, envelope_array, expect_json_body
from ..errors import ApiError
from ..pagination import parse as parse_pagination, apply as apply_pagination
from ..store import get_store, get_clock
from ..ids import new_uuid
from ..validators import (
    req_str,
    opt_str,
    req_number,
    opt_number,
    opt_int,
)
from .. import cascade

bp = Blueprint("restaurants", __name__, url_prefix="/api")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


RESTAURANT_STATUSES = {"PENDING_APPROVAL", "ACTIVE", "SUSPENDED", "CLOSED"}


def _ensure_restaurant(store, rid):
    rec = store.restaurants.get(rid)
    if not rec:
        raise ApiError("ERR_NOT_FOUND", f"Restaurant {rid} not found")
    return rec


def _check_commission_override(value):
    if value is None:
        return None
    if not 0.05 <= value <= 0.35:
        raise ApiError("ERR_VALIDATION", "commission_rate_override out of range")
    return value


def _public_restaurant(rec):
    out = dict(rec)
    return out


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@bp.post("/restaurants")
def register_restaurant():
    require_role({"PlatformAdmin"})
    body = expect_json_body()

    name = req_str(body, "name").strip()
    if not name or len(name) > 120:
        raise ApiError("ERR_VALIDATION", "name length must be 1..120")
    address = req_str(body, "address")
    lat = req_number(body, "lat")
    lng = req_number(body, "lng")
    if not -90 <= lat <= 90 or not -180 <= lng <= 180:
        raise ApiError("ERR_VALIDATION", "lat/lng out of range")

    override = body.get("commission_rate_override")
    if override is not None:
        if isinstance(override, bool) or not isinstance(override, (int, float)):
            raise ApiError("ERR_VALIDATION", "commission_rate_override must be a number")
        _check_commission_override(float(override))
        override = float(override)

    store = get_store()
    clock = get_clock()
    with store.lock:
        # Uniqueness on name among active restaurants (PRD §3.1)
        for r in store.restaurants.values():
            if r["status"] != "CLOSED" and r["name"] == name:
                raise ApiError("ERR_VALIDATION", "restaurant name already in use")

        now = clock.now_iso()
        rec = {
            "id": new_uuid(),
            "name": name,
            "address": address,
            "lat": lat,
            "lng": lng,
            "status": "PENDING_APPROVAL",
            "commission_rate_override": override,
            "pending_settlement_cents": 0,
            "created_at": now,
            "updated_at": now,
            "version": 1,
        }
        store.restaurants[rec["id"]] = rec
    return envelope_object(_public_restaurant(rec), status=201)


@bp.get("/restaurants")
def list_restaurants():
    require_role({"PlatformAdmin", "Customer", "Restaurant", "Rider", "CustomerService"})
    limit, offset = parse_pagination()
    from flask import request
    status_filter = request.args.get("status")
    if status_filter and status_filter not in RESTAURANT_STATUSES:
        raise ApiError("ERR_VALIDATION", "invalid status filter")
    store = get_store()
    with store.lock:
        items = list(store.restaurants.values())
        if status_filter:
            items = [r for r in items if r["status"] == status_filter]
        window, total = apply_pagination(items, limit, offset)
        data = [_public_restaurant(r) for r in window]
    return envelope_array(data, limit=limit, offset=offset, total_count=total)


@bp.get("/restaurants/<rid>")
def read_restaurant(rid):
    require_role({"PlatformAdmin", "Customer", "Restaurant", "Rider", "CustomerService"})
    store = get_store()
    with store.lock:
        rec = _ensure_restaurant(store, rid)
        return envelope_object(_public_restaurant(rec))


@bp.patch("/restaurants/<rid>")
def patch_restaurant(rid):
    uid, role = require_role({"PlatformAdmin", "Restaurant"})
    body = expect_json_body()
    store = get_store()
    with store.lock:
        rec = _ensure_restaurant(store, rid)
        if role == "Restaurant" and uid != rec["id"]:
            raise ApiError("ERR_FORBIDDEN", "Restaurant may only update self")

        # OCC
        if "version" in body and body["version"] is not None:
            if body["version"] != rec["version"]:
                raise ApiError("ERR_VERSION_CONFLICT", "version mismatch")

        # Mutable fields
        if "address" in body:
            v = opt_str(body, "address")
            if v is None:
                raise ApiError("ERR_VALIDATION", "address may not be null")
            rec["address"] = v
        if "lat" in body:
            v = opt_number(body, "lat")
            if v is None or not -90 <= v <= 90:
                raise ApiError("ERR_VALIDATION", "lat invalid")
            rec["lat"] = v
        if "lng" in body:
            v = opt_number(body, "lng")
            if v is None or not -180 <= v <= 180:
                raise ApiError("ERR_VALIDATION", "lng invalid")
            rec["lng"] = v
        if "commission_rate_override" in body:
            v = body["commission_rate_override"]
            if v is None:
                rec["commission_rate_override"] = None
            else:
                if isinstance(v, bool) or not isinstance(v, (int, float)):
                    raise ApiError("ERR_VALIDATION", "commission_rate_override must be number")
                rec["commission_rate_override"] = _check_commission_override(float(v))

        # name is immutable — silently ignore? PRD says "name is immutable after creation"
        if "name" in body and body["name"] != rec["name"]:
            raise ApiError("ERR_VALIDATION", "name is immutable")

        cascade.touch(rec, get_clock())
    return envelope_object(_public_restaurant(rec))


@bp.post("/restaurants/<rid>/approve")
def approve_restaurant(rid):
    require_role({"PlatformAdmin"})
    store = get_store()
    with store.lock:
        rec = _ensure_restaurant(store, rid)
        if rec["status"] != "PENDING_APPROVAL":
            raise ApiError("ERR_INVALID_STATE", "restaurant not in PENDING_APPROVAL")
        rec["status"] = "ACTIVE"
        cascade.touch(rec, get_clock())
    return envelope_object(_public_restaurant(rec))


@bp.post("/restaurants/<rid>/suspend")
def suspend_restaurant(rid):
    require_role({"PlatformAdmin"})
    store = get_store()
    clock = get_clock()
    with store.lock:
        rec = _ensure_restaurant(store, rid)
        if rec["status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE", "restaurant not ACTIVE")
        rec["status"] = "SUSPENDED"
        cascade.touch(rec, clock)
        # Fan-out cancel of PLACED orders for this restaurant.
        for order in store.orders.values():
            if order["restaurant_id"] == rid and order["status"] == "PLACED":
                cascade.cancel_order(store, clock, order)
    return envelope_object(_public_restaurant(rec))


@bp.post("/restaurants/<rid>/reinstate")
def reinstate_restaurant(rid):
    require_role({"PlatformAdmin"})
    store = get_store()
    with store.lock:
        rec = _ensure_restaurant(store, rid)
        if rec["status"] != "SUSPENDED":
            raise ApiError("ERR_INVALID_STATE", "restaurant not SUSPENDED")
        rec["status"] = "ACTIVE"
        cascade.touch(rec, get_clock())
    return envelope_object(_public_restaurant(rec))


@bp.post("/restaurants/<rid>/settle")
def settle_restaurant(rid):
    require_role({"PlatformAdmin"})
    store = get_store()
    with store.lock:
        rec = _ensure_restaurant(store, rid)
        rec["pending_settlement_cents"] = 0
        cascade.touch(rec, get_clock())
    return envelope_object(_public_restaurant(rec))
