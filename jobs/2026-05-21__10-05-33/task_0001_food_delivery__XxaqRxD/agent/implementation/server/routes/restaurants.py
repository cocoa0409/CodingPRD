"""Restaurant lifecycle endpoints."""
from __future__ import annotations

from flask import Blueprint, g, request

from ..auth import require_role
from ..envelope import success_list, success_object
from ..errors import ApiError
from ..ids import new_uuid
from ..pagination import page_slice, parse_pagination
from ..serializers import restaurant_out
from ..validation import (
    ensure_dict,
    optional_num,
    optional_str,
    require_num,
    require_str,
)
from ..version_ctl import bump, check_version


bp = Blueprint("restaurants", __name__, url_prefix="/api")


@bp.post("/restaurants")
def register_restaurant():
    require_role("PlatformAdmin")
    body = ensure_dict(request.get_json(silent=True) or {})
    name = require_str(body, "name", max_len=120)
    address = require_str(body, "address")
    lat = require_num(body, "lat", min_val=-90.0, max_val=90.0)
    lng = require_num(body, "lng", min_val=-180.0, max_val=180.0)
    cro = optional_num(body, "commission_rate_override", min_val=0.05, max_val=0.35)

    store = g.store
    with store.lock:
        if store.find_restaurant_name_clash(name):
            raise ApiError("ERR_VALIDATION", "restaurant name already in use")
        now = store.now_iso()
        rid = new_uuid()
        r = {
            "id": rid,
            "name": name,
            "address": address,
            "lat": lat,
            "lng": lng,
            "status": "PENDING_APPROVAL",
            "commission_rate_override": cro,
            "pending_settlement_cents": 0,
            "created_at": now,
            "updated_at": now,
            "version": 1,
        }
        store.restaurants[rid] = r
        return success_object(store.clock, restaurant_out(r), status=201)


@bp.get("/restaurants")
def list_restaurants():
    require_role("PlatformAdmin", "Customer", "Restaurant", "Rider", "CustomerService")
    limit, offset = parse_pagination()
    status_filter = request.args.get("status")
    store = g.store
    rows = list(store.restaurants.values())
    if status_filter:
        rows = [r for r in rows if r["status"] == status_filter]
    page, total = page_slice(rows, limit=limit, offset=offset)
    data = [restaurant_out(r) for r in page]
    return success_list(store.clock, data, limit=limit, offset=offset, total_count=total)


@bp.get("/restaurants/<rid>")
def read_restaurant(rid: str):
    require_role("PlatformAdmin", "Customer", "Restaurant", "Rider", "CustomerService")
    store = g.store
    r = store.restaurants.get(rid)
    if not r:
        raise ApiError("ERR_NOT_FOUND")
    return success_object(store.clock, restaurant_out(r))


@bp.patch("/restaurants/<rid>")
def update_restaurant(rid: str):
    require_role("PlatformAdmin", "Restaurant")
    store = g.store
    body = ensure_dict(request.get_json(silent=True) or {})
    with store.lock:
        r = store.restaurants.get(rid)
        if not r:
            raise ApiError("ERR_NOT_FOUND")
        if g.user_role == "Restaurant" and g.user_id != rid:
            raise ApiError("ERR_FORBIDDEN")
        # OCC token sits after most checks per the pipeline.
        check_version(r, body)
        if "address" in body:
            r["address"] = require_str(body, "address")
        if "lat" in body:
            r["lat"] = require_num(body, "lat", min_val=-90.0, max_val=90.0)
        if "lng" in body:
            r["lng"] = require_num(body, "lng", min_val=-180.0, max_val=180.0)
        if "commission_rate_override" in body:
            cro = body["commission_rate_override"]
            if cro is None:
                r["commission_rate_override"] = None
            else:
                r["commission_rate_override"] = require_num(
                    body, "commission_rate_override", min_val=0.05, max_val=0.35
                )
        bump(r, store.now_iso())
        return success_object(store.clock, restaurant_out(r))


@bp.post("/restaurants/<rid>/approve")
def approve_restaurant(rid: str):
    require_role("PlatformAdmin")
    store = g.store
    with store.lock:
        r = store.restaurants.get(rid)
        if not r:
            raise ApiError("ERR_NOT_FOUND")
        if r["status"] != "PENDING_APPROVAL":
            raise ApiError("ERR_INVALID_STATE")
        r["status"] = "ACTIVE"
        bump(r, store.now_iso())
        return success_object(store.clock, restaurant_out(r))


@bp.post("/restaurants/<rid>/suspend")
def suspend_restaurant(rid: str):
    require_role("PlatformAdmin")
    store = g.store
    with store.lock:
        r = store.restaurants.get(rid)
        if not r:
            raise ApiError("ERR_NOT_FOUND")
        if r["status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE")
        r["status"] = "SUSPENDED"
        now = store.now_iso()
        bump(r, now)
        # Cascade: every PLACED order of this restaurant transitions to CANCELLED.
        for o in store.orders.values():
            if o["restaurant_id"] == rid and o["status"] == "PLACED":
                _cancel_order_for_suspension(o, now)
        return success_object(store.clock, restaurant_out(r))


@bp.post("/restaurants/<rid>/reinstate")
def reinstate_restaurant(rid: str):
    require_role("PlatformAdmin")
    store = g.store
    with store.lock:
        r = store.restaurants.get(rid)
        if not r:
            raise ApiError("ERR_NOT_FOUND")
        if r["status"] != "SUSPENDED":
            raise ApiError("ERR_INVALID_STATE")
        r["status"] = "ACTIVE"
        bump(r, store.now_iso())
        return success_object(store.clock, restaurant_out(r))


@bp.post("/restaurants/<rid>/settle")
def settle_restaurant(rid: str):
    require_role("PlatformAdmin")
    store = g.store
    with store.lock:
        r = store.restaurants.get(rid)
        if not r:
            raise ApiError("ERR_NOT_FOUND")
        if r["status"] not in ("ACTIVE", "SUSPENDED"):
            # CLOSED or PENDING_APPROVAL can't settle.
            raise ApiError("ERR_INVALID_STATE")
        r["pending_settlement_cents"] = 0
        bump(r, store.now_iso())
        return success_object(store.clock, restaurant_out(r))


def _cancel_order_for_suspension(order: dict, now_iso: str) -> None:
    """Cascade helper: cancel an order whose restaurant has been suspended."""
    prev_payment = order["payment_status"]
    order["status"] = "CANCELLED"
    if prev_payment in ("UNPAID", "AUTHORIZED"):
        order["payment_status"] = "VOIDED"
    # Bump in lock-step.
    order["version"] = order["version"] + 1
    order["updated_at"] = now_iso
