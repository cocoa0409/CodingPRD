from flask import Blueprint, request

from ..auth import require_role
from ..envelope import success, created, list_ok
from ..errors import err
from ..pagination import parse_limit_offset, paginate
from ..repository import base_versioned, touch, check_version, body_or_empty
from ..store import store

bp = Blueprint("restaurants", __name__)


def _validate_name(name):
    if not isinstance(name, str) or not name.strip() or len(name) > 120:
        raise err("ERR_VALIDATION", "name must be 1..120 chars")


def _validate_coord(value, key, lo, hi):
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise err("ERR_VALIDATION", f"{key} must be a number")
    if value < lo or value > hi:
        raise err("ERR_VALIDATION", f"{key} out of range")


def _validate_commission_override(value):
    if value is None:
        return None
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise err("ERR_VALIDATION", "commission_rate_override must be a number")
    if value < 0.05 or value > 0.35:
        raise err("ERR_VALIDATION", "commission_rate_override must be in [0.05, 0.35]")
    return float(value)


@bp.post("/api/restaurants")
def register_restaurant():
    require_role("PlatformAdmin")
    body = body_or_empty()
    name = body.get("name")
    address = body.get("address")
    lat = body.get("lat")
    lng = body.get("lng")
    cro = body.get("commission_rate_override", None)

    _validate_name(name)
    if not isinstance(address, str) or not address.strip():
        raise err("ERR_VALIDATION", "address required")
    _validate_coord(lat, "lat", -90, 90)
    _validate_coord(lng, "lng", -180, 180)
    cro_val = _validate_commission_override(cro)

    # Uniqueness across active restaurants (visibility scope is active)
    # PRD says "unique among active restaurants" — enforced at registration only against active ones
    for r in store.restaurants.values():
        if r["name"] == name.strip() and r["status"] in ("PENDING_APPROVAL", "ACTIVE", "SUSPENDED"):
            if r["status"] == "ACTIVE":
                raise err("ERR_VALIDATION", "name not unique among active restaurants")

    r = base_versioned()
    r.update({
        "name": name.strip(),
        "address": address,
        "lat": float(lat),
        "lng": float(lng),
        "commission_rate_override": cro_val,
        "status": "PENDING_APPROVAL",
        "pending_settlement_cents": 0,
    })
    store.restaurants[r["id"]] = r
    return created(_view(r))


def _view(r):
    return {k: r[k] for k in (
        "id", "name", "address", "lat", "lng",
        "commission_rate_override", "status", "pending_settlement_cents",
        "created_at", "updated_at", "version",
    )}


def _get_restaurant_or_404(rid):
    r = store.restaurants.get(rid)
    if r is None:
        raise err("ERR_NOT_FOUND", "restaurant not found")
    return r


@bp.get("/api/restaurants")
def list_restaurants():
    require_role("PlatformAdmin", "Customer", "Restaurant", "Rider", "CustomerService")
    limit, offset = parse_limit_offset()
    status_filter = request.args.get("status")
    items = sorted(store.restaurants.values(), key=lambda x: x["created_at"])
    if status_filter:
        items = [r for r in items if r["status"] == status_filter]
    window, total = paginate(items, limit, offset)
    return list_ok([_view(x) for x in window], limit, offset, total)


@bp.get("/api/restaurants/<rid>")
def get_restaurant(rid):
    require_role("PlatformAdmin", "Customer", "Restaurant", "Rider", "CustomerService")
    r = _get_restaurant_or_404(rid)
    return success(_view(r))


@bp.patch("/api/restaurants/<rid>")
def patch_restaurant(rid):
    uid, role = require_role("PlatformAdmin", "Restaurant")
    r = _get_restaurant_or_404(rid)
    if role == "Restaurant" and r["id"] != uid:
        raise err("ERR_FORBIDDEN", "not the owning restaurant")
    body = body_or_empty()
    mutables = {}
    if "address" in body:
        if not isinstance(body["address"], str) or not body["address"].strip():
            raise err("ERR_VALIDATION", "address invalid")
        mutables["address"] = body["address"]
    if "lat" in body:
        _validate_coord(body["lat"], "lat", -90, 90)
        mutables["lat"] = float(body["lat"])
    if "lng" in body:
        _validate_coord(body["lng"], "lng", -180, 180)
        mutables["lng"] = float(body["lng"])
    if "commission_rate_override" in body:
        mutables["commission_rate_override"] = _validate_commission_override(body["commission_rate_override"])
    # name is immutable
    if "name" in body and body["name"] != r["name"]:
        raise err("ERR_VALIDATION", "name is immutable")
    check_version(r, body)
    for k, v in mutables.items():
        r[k] = v
    touch(r)
    return success(_view(r))


@bp.post("/api/restaurants/<rid>/approve")
def approve_restaurant(rid):
    require_role("PlatformAdmin")
    r = _get_restaurant_or_404(rid)
    if r["status"] != "PENDING_APPROVAL":
        raise err("ERR_INVALID_STATE", "not in PENDING_APPROVAL")
    body = body_or_empty()
    check_version(r, body)
    r["status"] = "ACTIVE"
    touch(r)
    return success(_view(r))


@bp.post("/api/restaurants/<rid>/suspend")
def suspend_restaurant(rid):
    require_role("PlatformAdmin")
    r = _get_restaurant_or_404(rid)
    if r["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "not in ACTIVE")
    body = body_or_empty()
    check_version(r, body)
    r["status"] = "SUSPENDED"
    touch(r)
    # Fan out cancellations to PLACED orders of this restaurant
    from ..domain.orders_cancel import cancel_placed_orders_for_restaurant
    cancel_placed_orders_for_restaurant(rid)
    return success(_view(r))


@bp.post("/api/restaurants/<rid>/reinstate")
def reinstate_restaurant(rid):
    require_role("PlatformAdmin")
    r = _get_restaurant_or_404(rid)
    if r["status"] != "SUSPENDED":
        raise err("ERR_INVALID_STATE", "not in SUSPENDED")
    body = body_or_empty()
    check_version(r, body)
    r["status"] = "ACTIVE"
    touch(r)
    return success(_view(r))


@bp.post("/api/restaurants/<rid>/settle")
def settle_restaurant(rid):
    require_role("PlatformAdmin")
    r = _get_restaurant_or_404(rid)
    body = body_or_empty()
    check_version(r, body)
    r["pending_settlement_cents"] = 0
    touch(r)
    return success(_view(r))
