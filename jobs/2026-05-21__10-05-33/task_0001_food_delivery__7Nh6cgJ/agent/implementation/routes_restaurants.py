"""Restaurant + restaurant-action endpoints."""

from __future__ import annotations

from typing import Any

from flask import request

from auth import require_role
from envelope import list_success, success
from errors import APIError
from resources import check_version, make_versioned, touch
from store import STORE
from validation import get_body, parse_pagination, require_number, require_str

VALID_STATUSES = {"PENDING_APPROVAL", "ACTIVE", "SUSPENDED", "CLOSED"}


def _serialize(r: dict) -> dict:
    return {
        "id": r["id"],
        "name": r["name"],
        "address": r["address"],
        "lat": r["lat"],
        "lng": r["lng"],
        "status": r["status"],
        "commission_rate_override": r.get("commission_rate_override"),
        "pending_settlement_cents": r["pending_settlement_cents"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def _validate_commission_rate(value: Any) -> float | None:
    if value is None:
        return None
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise APIError("ERR_VALIDATION", "commission_rate_override must be a decimal in [0.05, 0.35].")
    rate = float(value)
    if rate < 0.05 or rate > 0.35:
        raise APIError("ERR_VALIDATION", "commission_rate_override must be in [0.05, 0.35].")
    return rate


def _validate_lat_lng(body: dict) -> tuple[float, float]:
    lat = require_number(body, "lat")
    lng = require_number(body, "lng")
    if lat < -90 or lat > 90:
        raise APIError("ERR_VALIDATION", "lat must be in [-90, 90].")
    if lng < -180 or lng > 180:
        raise APIError("ERR_VALIDATION", "lng must be in [-180, 180].")
    return lat, lng


def register(app):
    @app.post("/api/restaurants")
    def register_restaurant():
        require_role({"PlatformAdmin"})
        body = get_body()
        name = require_str(body, "name", min_length=1, max_length=120)
        address = require_str(body, "address")
        lat, lng = _validate_lat_lng(body)
        commission_rate = _validate_commission_rate(body.get("commission_rate_override"))

        with STORE.lock:
            # Uniqueness among active restaurants — but PRD says "unique among active restaurants",
            # interpret as no existing non-CLOSED restaurant shares the name.
            for r in STORE.restaurants.values():
                if r["name"] == name and r["status"] != "CLOSED":
                    raise APIError("ERR_VALIDATION", "Restaurant name already in use.")
            restaurant = make_versioned({
                "name": name,
                "address": address,
                "lat": lat,
                "lng": lng,
                "status": "PENDING_APPROVAL",
                "commission_rate_override": commission_rate,
                "pending_settlement_cents": 0,
            })
            STORE.restaurants[restaurant["id"]] = restaurant
            return success(_serialize(restaurant), status=201)

    @app.get("/api/restaurants")
    def list_restaurants():
        require_role({"PlatformAdmin", "Customer", "Restaurant", "Rider", "CustomerService"})
        limit, offset = parse_pagination()
        status_filter = request.args.get("status")
        with STORE.lock:
            items = list(STORE.restaurants.values())
            if status_filter is not None:
                if status_filter not in VALID_STATUSES:
                    raise APIError("ERR_VALIDATION", "Invalid status filter.")
                items = [r for r in items if r["status"] == status_filter]
            items.sort(key=lambda r: r["created_at"])
            page = items[offset:offset + limit]
            return list_success([_serialize(r) for r in page], limit, offset, len(items))

    @app.get("/api/restaurants/<rid>")
    def read_restaurant(rid: str):
        require_role({"PlatformAdmin", "Customer", "Restaurant", "Rider", "CustomerService"})
        with STORE.lock:
            r = STORE.restaurants.get(rid)
            if r is None:
                raise APIError("ERR_NOT_FOUND", "No such restaurant.")
            return success(_serialize(r))

    @app.patch("/api/restaurants/<rid>")
    def patch_restaurant(rid: str):
        user_id, role = require_role({"PlatformAdmin", "Restaurant"})
        body = get_body()
        with STORE.lock:
            r = STORE.restaurants.get(rid)
            if r is None:
                raise APIError("ERR_NOT_FOUND", "No such restaurant.")
            if role == "Restaurant" and user_id != r["id"]:
                raise APIError("ERR_FORBIDDEN")
            allowed_keys = {"address", "lat", "lng", "commission_rate_override", "version"}
            unknown = set(body.keys()) - allowed_keys
            if unknown:
                raise APIError("ERR_VALIDATION", f"Unknown/immutable field(s): {sorted(unknown)}")
            check_version(r, body.get("version"))
            if "address" in body:
                if not isinstance(body["address"], str) or not body["address"]:
                    raise APIError("ERR_VALIDATION", "address must be a non-empty string.")
                r["address"] = body["address"]
            if "lat" in body or "lng" in body:
                lat = body.get("lat", r["lat"])
                lng = body.get("lng", r["lng"])
                if not isinstance(lat, (int, float)) or isinstance(lat, bool) \
                        or not isinstance(lng, (int, float)) or isinstance(lng, bool):
                    raise APIError("ERR_VALIDATION", "lat/lng must be numeric.")
                if lat < -90 or lat > 90 or lng < -180 or lng > 180:
                    raise APIError("ERR_VALIDATION", "lat/lng out of range.")
                r["lat"] = float(lat)
                r["lng"] = float(lng)
            if "commission_rate_override" in body:
                r["commission_rate_override"] = _validate_commission_rate(body["commission_rate_override"])
            touch(r)
            return success(_serialize(r))

    @app.post("/api/restaurants/<rid>/approve")
    def approve_restaurant(rid: str):
        require_role({"PlatformAdmin"})
        with STORE.lock:
            r = STORE.restaurants.get(rid)
            if r is None:
                raise APIError("ERR_NOT_FOUND", "No such restaurant.")
            if r["status"] != "PENDING_APPROVAL":
                raise APIError("ERR_INVALID_STATE", "Restaurant is not in PENDING_APPROVAL.")
            r["status"] = "ACTIVE"
            touch(r)
            return success(_serialize(r))

    @app.post("/api/restaurants/<rid>/suspend")
    def suspend_restaurant(rid: str):
        require_role({"PlatformAdmin"})
        with STORE.lock:
            r = STORE.restaurants.get(rid)
            if r is None:
                raise APIError("ERR_NOT_FOUND", "No such restaurant.")
            if r["status"] != "ACTIVE":
                raise APIError("ERR_INVALID_STATE", "Only ACTIVE restaurants can be suspended.")
            r["status"] = "SUSPENDED"
            touch(r)
            # Fan-out cancellation of PLACED orders.
            for order in STORE.orders.values():
                if order["restaurant_id"] == rid and order["status"] == "PLACED":
                    order["status"] = "CANCELLED"
                    prev = order["payment_status"]
                    if prev in ("UNPAID", "AUTHORIZED"):
                        order["payment_status"] = "VOIDED"
                    touch(order)
            return success(_serialize(r))

    @app.post("/api/restaurants/<rid>/reinstate")
    def reinstate_restaurant(rid: str):
        require_role({"PlatformAdmin"})
        with STORE.lock:
            r = STORE.restaurants.get(rid)
            if r is None:
                raise APIError("ERR_NOT_FOUND", "No such restaurant.")
            if r["status"] != "SUSPENDED":
                raise APIError("ERR_INVALID_STATE", "Only SUSPENDED restaurants can be reinstated.")
            r["status"] = "ACTIVE"
            touch(r)
            return success(_serialize(r))

    @app.post("/api/restaurants/<rid>/settle")
    def settle_restaurant(rid: str):
        require_role({"PlatformAdmin"})
        with STORE.lock:
            r = STORE.restaurants.get(rid)
            if r is None:
                raise APIError("ERR_NOT_FOUND", "No such restaurant.")
            r["pending_settlement_cents"] = 0
            touch(r)
            return success(_serialize(r))
