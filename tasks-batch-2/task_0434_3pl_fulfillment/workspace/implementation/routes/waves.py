"""Wave endpoints and lifecycle (PRD §3.3, §3.4)."""
from flask import Blueprint, request

from db import store, new_id, stamp_create, touch
from errors import err
from middleware import get_auth, require_roles
from response import success
from common import (
    get_client, get_order, get_wave,
    get_json_body, parse_pagination, paginate,
)
from serializers import serialize_wave
from services import order_ops

bp = Blueprint("waves", __name__)

READ_ROLES = {"WavePlanner", "ClientUser", "BillingClerk"}


@bp.route("/waves", methods=["GET"])
def list_waves():
    _, role = get_auth()
    require_roles(role, READ_ROLES)
    limit, offset = parse_pagination()
    items = list(store.waves.values())
    client_id = request.args.get("client_id")
    if client_id is not None:
        items = [w for w in items if w["client_id"] == client_id]
    page, meta = paginate(items, limit, offset)
    return success([serialize_wave(r) for r in page], pagination=meta)


@bp.route("/waves/<wave_id>", methods=["GET"])
def get_one_wave_flat(wave_id):
    _, role = get_auth()
    require_roles(role, READ_ROLES)
    rec = get_wave(wave_id)
    return success(serialize_wave(rec))


@bp.route("/clients/<client_id>/waves", methods=["POST"])
def create_wave(client_id):
    _, role = get_auth()
    require_roles(role, {"WavePlanner"})
    get_client(client_id)
    rec = stamp_create({
        "id": new_id(),
        "client_id": client_id,
        "status": "BUILDING",
    })
    store.waves[rec["id"]] = rec
    return success(serialize_wave(rec), status=201)


@bp.route("/clients/<client_id>/waves", methods=["GET"])
def list_client_waves(client_id):
    _, role = get_auth()
    require_roles(role, READ_ROLES)
    get_client(client_id)
    limit, offset = parse_pagination()
    items = [w for w in store.waves.values() if w["client_id"] == client_id]
    page, meta = paginate(items, limit, offset)
    return success([serialize_wave(r) for r in page], pagination=meta)


def _resolve_wave(client_id, wave_id):
    get_client(client_id)
    rec = get_wave(wave_id)
    if rec["client_id"] != client_id:
        raise err("ERR_CLIENT_OWNERSHIP_MISMATCH", "Wave not owned by path client")
    return rec


@bp.route("/clients/<client_id>/waves/<wave_id>", methods=["GET"])
def get_client_wave(client_id, wave_id):
    _, role = get_auth()
    require_roles(role, READ_ROLES)
    rec = _resolve_wave(client_id, wave_id)
    return success(serialize_wave(rec))


@bp.route("/clients/<client_id>/waves/<wave_id>/add-order", methods=["POST"])
def add_order_to_wave(client_id, wave_id):
    _, role = get_auth()
    require_roles(role, {"WavePlanner"})
    wave = _resolve_wave(client_id, wave_id)
    body = get_json_body()

    order_id = body.get("order_id")
    if not isinstance(order_id, str) or order_id == "":
        raise err("ERR_INVALID_REQUEST", "order_id is required")

    order = get_order(order_id)
    if order["client_id"] != client_id:
        raise err("ERR_CLIENT_OWNERSHIP_MISMATCH", "Order not owned by path client")

    if wave["status"] != "BUILDING":
        raise err("ERR_WAVE_NOT_BUILDING", "Wave is not BUILDING")
    if order["status"] != "IMPORTED":
        raise err("ERR_ORDER_NOT_IMPORTED", "Order is not IMPORTED")

    order["wave_id"] = wave_id
    touch(order)
    touch(wave)
    return success(serialize_wave(wave))


@bp.route("/clients/<client_id>/waves/<wave_id>/release", methods=["POST"])
def release_wave(client_id, wave_id):
    _, role = get_auth()
    require_roles(role, {"WavePlanner"})
    wave = _resolve_wave(client_id, wave_id)

    if wave["status"] != "BUILDING":
        raise err("ERR_WAVE_NOT_BUILDING", "Wave is not BUILDING")

    members = [o for o in store.orders.values() if o["wave_id"] == wave_id]
    if len(members) == 0:
        raise err("ERR_WAVE_EMPTY", "Wave has no member orders")

    # Coverage check across ALL member orders before reserving anything (atomic).
    # Accumulate per-SKU demand across all members and compare to available pool.
    demand = {}
    for order in members:
        for line in order["lines"]:
            key = (order["client_id"], line["sku_id"])
            demand[key] = demand.get(key, 0) + line["qty"]
    for (cid, sku_id), qty in demand.items():
        if order_ops.available_for_client_sku(cid, sku_id) < qty:
            raise err("ERR_INSUFFICIENT_INVENTORY", "Insufficient available inventory at release")

    # Reserve member orders in deterministic created_at order.
    members_sorted = sorted(members, key=lambda o: (o["created_at"], o["_seq"]))
    for order in members_sorted:
        order_ops.reserve_order(order)
        # IMPORTED -> RESERVED -> PICKING
        order["status"] = "PICKING"
        touch(order)

    wave["status"] = "RELEASED"
    touch(wave)
    return success(serialize_wave(wave))


@bp.route("/clients/<client_id>/waves/<wave_id>/cancel", methods=["POST"])
def cancel_wave(client_id, wave_id):
    _, role = get_auth()
    require_roles(role, {"WavePlanner"})
    wave = _resolve_wave(client_id, wave_id)

    if wave["status"] != "BUILDING":
        raise err("ERR_WAVE_NOT_BUILDING", "Wave is not BUILDING")

    # Detach every member order (wave_id := null); orders stay IMPORTED.
    for order in store.orders.values():
        if order["wave_id"] == wave_id:
            order["wave_id"] = None
            touch(order)

    wave["status"] = "CANCELLED"
    touch(wave)
    return success(serialize_wave(wave))
