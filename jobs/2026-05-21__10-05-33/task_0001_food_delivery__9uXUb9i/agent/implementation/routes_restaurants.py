"""Restaurant lifecycle endpoints (PRD §3.1, §3.8)."""
from __future__ import annotations

from flask import Blueprint, g

from auth import require_roles
from common import (
    get_json_body,
    optional_number,
    optional_str,
    paginate,
    parse_pagination,
    require_str,
    require_number,
    validate_commission_rate,
    validate_lat_lng,
)
from envelope import success
from errors import ApiError
from serializers import serialize_restaurant
import store
from store import gen_id, iso_z, lock, now


bp = Blueprint("restaurants", __name__, url_prefix="/api/restaurants")


def _find_restaurant(rid: str) -> dict:
    r = store.restaurants.get(rid)
    if not r:
        raise ApiError("ERR_NOT_FOUND", "Restaurant not found.")
    return r


def _check_version(resource: dict, body: dict) -> None:
    if "version" in body and body["version"] is not None:
        if body["version"] != resource["version"]:
            raise ApiError("ERR_VERSION_CONFLICT", "Resource version mismatch.")


@bp.post("")
@require_roles("PlatformAdmin")
def register_restaurant():
    body = get_json_body()
    name = require_str(body, "name", max_len=120)
    address = require_str(body, "address")
    lat = require_number(body, "lat")
    lng = require_number(body, "lng")
    validate_lat_lng(lat, lng)
    override = optional_number(body, "commission_rate_override")
    if override is not None:
        validate_commission_rate(override)

    with lock():
        # Name unique among active restaurants
        for r in store.restaurants.values():
            if r["status"] != "CLOSED" and r["name"] == name:
                # Per PRD "unique among active restaurants"; we treat any
                # non-closed restaurant as occupying the name.
                raise ApiError("ERR_VALIDATION", "Restaurant name is not unique.")
        t = now()
        rid = gen_id()
        rec = {
            "id": rid,
            "name": name,
            "address": address,
            "lat": lat,
            "lng": lng,
            "status": "PENDING_APPROVAL",
            "commission_rate_override": override,
            "pending_settlement_cents": 0,
            "created_at": iso_z(t),
            "updated_at": iso_z(t),
            "version": 1,
        }
        store.restaurants[rid] = rec
    return success(serialize_restaurant(rec), status=201)


@bp.get("")
@require_roles("PlatformAdmin", "Customer", "Restaurant", "Rider", "CustomerService")
def list_restaurants():
    from flask import request
    status_filter = request.args.get("status")
    limit, offset = parse_pagination()
    with lock():
        items = list(store.restaurants.values())
    if status_filter is not None:
        items = [r for r in items if r["status"] == status_filter]
    items.sort(key=lambda r: r["created_at"])
    window, meta = paginate(items, limit, offset)
    return success([serialize_restaurant(r) for r in window], list_meta=meta)


@bp.get("/<rid>")
@require_roles("PlatformAdmin", "Customer", "Restaurant", "Rider", "CustomerService")
def read_restaurant(rid: str):
    r = _find_restaurant(rid)
    return success(serialize_restaurant(r))


@bp.patch("/<rid>")
@require_roles("PlatformAdmin", "Restaurant")
def patch_restaurant(rid: str):
    r = _find_restaurant(rid)
    body = get_json_body()

    # Identity match (step 5 of validation pipeline)
    if g.role == "Restaurant" and g.user_id != r["id"]:
        raise ApiError("ERR_FORBIDDEN", "Restaurant identity mismatch.")

    changes = {}
    if "address" in body:
        v = body["address"]
        if not isinstance(v, str) or not v.strip():
            raise ApiError("ERR_VALIDATION", "address must be a non-empty string.")
        changes["address"] = v
    if "lat" in body or "lng" in body:
        lat = body.get("lat", r["lat"])
        lng = body.get("lng", r["lng"])
        if not isinstance(lat, (int, float)) or isinstance(lat, bool):
            raise ApiError("ERR_VALIDATION", "lat must be a number.")
        if not isinstance(lng, (int, float)) or isinstance(lng, bool):
            raise ApiError("ERR_VALIDATION", "lng must be a number.")
        validate_lat_lng(float(lat), float(lng))
        changes["lat"] = float(lat)
        changes["lng"] = float(lng)
    if "commission_rate_override" in body:
        v = body["commission_rate_override"]
        if v is None:
            changes["commission_rate_override"] = None
        else:
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise ApiError("ERR_VALIDATION", "commission_rate_override must be a number or null.")
            validate_commission_rate(float(v))
            changes["commission_rate_override"] = float(v)
    if "name" in body:
        # Name is immutable; reject the attempt explicitly
        raise ApiError("ERR_VALIDATION", "name is immutable after creation.")

    _check_version(r, body)

    if not changes:
        return success(serialize_restaurant(r))

    with lock():
        r.update(changes)
        r["updated_at"] = iso_z(now())
        r["version"] += 1
    return success(serialize_restaurant(r))


@bp.post("/<rid>/approve")
@require_roles("PlatformAdmin")
def approve_restaurant(rid: str):
    r = _find_restaurant(rid)
    if r["status"] != "PENDING_APPROVAL":
        raise ApiError("ERR_INVALID_STATE", "Restaurant cannot be approved from current state.")
    with lock():
        r["status"] = "ACTIVE"
        r["updated_at"] = iso_z(now())
        r["version"] += 1
    return success(serialize_restaurant(r))


@bp.post("/<rid>/suspend")
@require_roles("PlatformAdmin")
def suspend_restaurant(rid: str):
    r = _find_restaurant(rid)
    if r["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "Only ACTIVE restaurants can be suspended.")
    with lock():
        r["status"] = "SUSPENDED"
        r["updated_at"] = iso_z(now())
        r["version"] += 1
        # Fan out cancellation to PLACED orders.
        for o in store.orders.values():
            if o["restaurant_id"] == r["id"] and o["status"] == "PLACED":
                o["status"] = "CANCELLED"
                # payment_status moves AUTHORIZED/UNPAID -> VOIDED
                if o["payment_status"] in ("AUTHORIZED", "UNPAID"):
                    o["payment_status"] = "VOIDED"
                o["updated_at"] = iso_z(now())
                o["version"] += 1
    return success(serialize_restaurant(r))


@bp.post("/<rid>/reinstate")
@require_roles("PlatformAdmin")
def reinstate_restaurant(rid: str):
    r = _find_restaurant(rid)
    if r["status"] != "SUSPENDED":
        raise ApiError("ERR_INVALID_STATE", "Only SUSPENDED restaurants can be reinstated.")
    with lock():
        r["status"] = "ACTIVE"
        r["updated_at"] = iso_z(now())
        r["version"] += 1
    return success(serialize_restaurant(r))


@bp.post("/<rid>/settle")
@require_roles("PlatformAdmin")
def settle_restaurant(rid: str):
    r = _find_restaurant(rid)
    with lock():
        r["pending_settlement_cents"] = 0
        r["updated_at"] = iso_z(now())
        r["version"] += 1
    return success(serialize_restaurant(r))
