from __future__ import annotations

from flask import Blueprint, g, request

from .. import projections, resolvers
from ..auth import require_role
from ..clock import iso_now
from ..entities import bump, init_versioned
from ..envelope import (
    err_forbidden,
    err_invalid_state,
    err_validation,
    success,
    success_list,
)
from ..occ import check as occ_check
from ..store import store
from ..validators import (
    get_json,
    optional_int,
    optional_number,
    optional_str,
    pagination_params,
    require_number,
    require_str,
)

bp = Blueprint("restaurants", __name__)


def _serialize(r: dict) -> dict:
    return projections.restaurant(r)


@bp.route("/api/restaurants", methods=["POST"])
def register_restaurant():
    require_role("PlatformAdmin")
    body = get_json()

    name = require_str(body, "name", max_len=120)
    if len(name) > 120 or not name.strip():
        raise err_validation("name must be non-empty and at most 120 chars")
    # Uniqueness among active restaurants (i.e., not CLOSED): per PRD it's "unique among active".
    # Treat as unique across non-CLOSED. We compare case-sensitively as spec doesn't say otherwise.
    for r in store.restaurants.values():
        if r.get("name") == name and r.get("status") != "CLOSED":
            raise err_validation("name must be unique among active restaurants")

    address = require_str(body, "address", max_len=500)
    lat = require_number(body, "lat", minv=-90, maxv=90)
    lng = require_number(body, "lng", minv=-180, maxv=180)
    rate = optional_number(body, "commission_rate_override", minv=0.05, maxv=0.35)

    r = init_versioned("Restaurant")
    r.update(
        {
            "name": name,
            "address": address,
            "lat": lat,
            "lng": lng,
            "status": "PENDING_APPROVAL",
            "commission_rate_override": rate,
            "pending_settlement_cents": 0,
        }
    )
    store.restaurants[r["id"]] = r
    return success(_serialize(r), status=201)


@bp.route("/api/restaurants", methods=["GET"])
def list_restaurants():
    require_role("PlatformAdmin", "Customer", "Restaurant", "Rider", "CustomerService")
    limit, offset = pagination_params()
    status_filter = request.args.get("status")
    items = list(store.restaurants.values())
    if status_filter:
        items = [r for r in items if r["status"] == status_filter]
    items.sort(key=lambda r: r["created_at"])
    total = len(items)
    page = items[offset : offset + limit]
    return success_list([_serialize(r) for r in page], limit, offset, total)


@bp.route("/api/restaurants/<rid>", methods=["GET"])
def read_restaurant(rid: str):
    require_role("PlatformAdmin", "Customer", "Restaurant", "Rider", "CustomerService")
    r = resolvers.restaurant(rid)
    return success(_serialize(r))


@bp.route("/api/restaurants/<rid>", methods=["PATCH"])
def patch_restaurant(rid: str):
    require_role("PlatformAdmin", "Restaurant")
    r = resolvers.restaurant(rid)
    # Identity check for Restaurant role
    if g.user_role == "Restaurant" and g.user_id != r["id"]:
        raise err_forbidden("Restaurant identity mismatch")
    body = get_json()
    # Validate version OCC last per validation pipeline; but we validate fields first
    new_address = optional_str(body, "address", max_len=500)
    new_lat = optional_number(body, "lat", minv=-90, maxv=90)
    new_lng = optional_number(body, "lng", minv=-180, maxv=180)
    # commission_rate_override may be set to null explicitly
    rate_supplied = "commission_rate_override" in body
    new_rate = body.get("commission_rate_override") if rate_supplied else None
    if rate_supplied and new_rate is not None:
        if isinstance(new_rate, bool) or not isinstance(new_rate, (int, float)):
            raise err_validation("commission_rate_override must be a number or null")
        if not (0.05 <= float(new_rate) <= 0.35):
            raise err_validation("commission_rate_override out of range")
        new_rate = float(new_rate)
    # OCC
    occ_check(r, body.get("version"))

    if new_address is not None:
        r["address"] = new_address
    if new_lat is not None:
        r["lat"] = new_lat
    if new_lng is not None:
        r["lng"] = new_lng
    if rate_supplied:
        r["commission_rate_override"] = new_rate
    bump(r)
    return success(_serialize(r))


def _admin_action_setup(rid: str) -> dict:
    require_role("PlatformAdmin")
    return resolvers.restaurant(rid)


@bp.route("/api/restaurants/<rid>/approve", methods=["POST"])
def approve_restaurant(rid: str):
    r = _admin_action_setup(rid)
    if r["status"] != "PENDING_APPROVAL":
        raise err_invalid_state(
            f"Cannot approve restaurant in state {r['status']}"
        )
    r["status"] = "ACTIVE"
    bump(r)
    return success(_serialize(r))


@bp.route("/api/restaurants/<rid>/suspend", methods=["POST"])
def suspend_restaurant(rid: str):
    r = _admin_action_setup(rid)
    if r["status"] != "ACTIVE":
        raise err_invalid_state(
            f"Cannot suspend restaurant in state {r['status']}"
        )
    r["status"] = "SUSPENDED"
    bump(r)
    # Fan out cancellation to PLACED orders
    from ..order_logic import cancel_order_due_to_suspend
    for o in list(store.orders.values()):
        if o["restaurant_id"] == r["id"] and o["status"] == "PLACED":
            cancel_order_due_to_suspend(o)
    return success(_serialize(r))


@bp.route("/api/restaurants/<rid>/reinstate", methods=["POST"])
def reinstate_restaurant(rid: str):
    r = _admin_action_setup(rid)
    if r["status"] != "SUSPENDED":
        raise err_invalid_state(
            f"Cannot reinstate restaurant in state {r['status']}"
        )
    r["status"] = "ACTIVE"
    bump(r)
    return success(_serialize(r))


@bp.route("/api/restaurants/<rid>/settle", methods=["POST"])
def settle_restaurant(rid: str):
    r = _admin_action_setup(rid)
    # Settlement does not have a stated state precondition beyond existing.
    # Spec says: at end of settlement cycle, admin settles.
    # We allow settle on any non-CLOSED restaurant (the audit marker is set).
    if r["status"] == "CLOSED":
        raise err_invalid_state("Cannot settle a CLOSED restaurant")
    r["pending_settlement_cents"] = 0
    bump(r)
    return success(_serialize(r))
