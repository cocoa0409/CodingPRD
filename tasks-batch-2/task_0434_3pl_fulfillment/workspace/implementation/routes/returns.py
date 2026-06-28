"""Return endpoints and lifecycle (PRD §3.9)."""
from flask import Blueprint, request

from db import store, new_id, stamp_create, touch
from errors import err
from middleware import get_auth, require_roles
from response import success
from common import (
    get_client, get_order, get_sku, get_bin, get_return,
    get_json_body, parse_pagination, paginate,
)
from serializers import serialize_return
from services.inventory import bin_occupied_cc, bin_holds_other_client, find_restock_lot

bp = Blueprint("returns", __name__)

READ_ROLES = {"ReturnsClerk", "ClientUser", "BillingClerk"}


def _shipped_units_for_sku(order, sku_id):
    return sum(line["qty"] for line in order["lines"] if line["sku_id"] == sku_id)


def _filter_returns(items):
    for key in ("order_id", "sku_id", "bin_id"):
        val = request.args.get(key)
        if val is not None:
            items = [r for r in items if r.get(key) == val]
    return items


@bp.route("/returns", methods=["GET"])
def list_returns_flat():
    _, role = get_auth()
    require_roles(role, READ_ROLES)
    limit, offset = parse_pagination()
    items = _filter_returns(list(store.returns.values()))
    page, meta = paginate(items, limit, offset)
    return success([serialize_return(r) for r in page], pagination=meta)


@bp.route("/returns/<return_id>", methods=["GET"])
def get_one_return_flat(return_id):
    _, role = get_auth()
    require_roles(role, READ_ROLES)
    rec = get_return(return_id)
    return success(serialize_return(rec))


@bp.route("/clients/<client_id>/returns", methods=["POST"])
def open_return(client_id):
    _, role = get_auth()
    require_roles(role, {"ReturnsClerk"})
    get_client(client_id)
    body = get_json_body()

    order_id = body.get("order_id")
    sku_id = body.get("sku_id")
    bin_id = body.get("bin_id")
    if not isinstance(order_id, str) or order_id == "":
        raise err("ERR_INVALID_REQUEST", "order_id is required")
    if not isinstance(sku_id, str) or sku_id == "":
        raise err("ERR_INVALID_REQUEST", "sku_id is required")
    if not isinstance(bin_id, str) or bin_id == "":
        raise err("ERR_INVALID_REQUEST", "bin_id is required")

    qty = body.get("qty")
    if isinstance(qty, bool) or not isinstance(qty, int):
        raise err("ERR_INVALID_REQUEST", "qty must be an integer")
    if qty <= 0:
        raise err("ERR_INVALID_REQUEST", "qty must be > 0")

    # FK existence.
    order = get_order(order_id)
    sku = get_sku(sku_id)
    bin_rec = get_bin(bin_id)

    # Cross-ownership: order & sku belong to the path client.
    if order["client_id"] != client_id:
        raise err("ERR_CLIENT_OWNERSHIP_MISMATCH", "Order not owned by path client")
    if sku["client_id"] != client_id:
        raise err("ERR_CLIENT_OWNERSHIP_MISMATCH", "SKU not owned by path client")

    # Order must be SHIPPED.
    if order["status"] != "SHIPPED":
        raise err("ERR_ORDER_NOT_SHIPPED", "Order is not SHIPPED")

    # SKU must have been shipped on the order, and qty must not exceed shipped.
    shipped = _shipped_units_for_sku(order, sku_id)
    if shipped <= 0:
        raise err("ERR_RETURN_QTY_EXCEEDS_SHIPPED", "SKU was not shipped on this order")
    if qty > shipped:
        raise err("ERR_RETURN_QTY_EXCEEDS_SHIPPED", "Return qty exceeds shipped units")

    rec = stamp_create({
        "id": new_id(),
        "order_id": order_id,
        "client_id": client_id,
        "sku_id": sku_id,
        "bin_id": bin_id,
        "qty": qty,
        "grade": None,
        "status": "REQUESTED",
    })
    store.returns[rec["id"]] = rec
    return success(serialize_return(rec), status=201)


@bp.route("/clients/<client_id>/returns", methods=["GET"])
def list_client_returns(client_id):
    _, role = get_auth()
    require_roles(role, READ_ROLES)
    get_client(client_id)
    limit, offset = parse_pagination()
    items = [r for r in store.returns.values() if r["client_id"] == client_id]
    items = _filter_returns(items)
    page, meta = paginate(items, limit, offset)
    return success([serialize_return(r) for r in page], pagination=meta)


def _resolve_return(client_id, return_id):
    get_client(client_id)
    rec = get_return(return_id)
    if rec["client_id"] != client_id:
        raise err("ERR_CLIENT_OWNERSHIP_MISMATCH", "Return not owned by path client")
    return rec


@bp.route("/clients/<client_id>/returns/<return_id>", methods=["GET"])
def get_client_return(client_id, return_id):
    _, role = get_auth()
    require_roles(role, READ_ROLES)
    rec = _resolve_return(client_id, return_id)
    return success(serialize_return(rec))


@bp.route("/clients/<client_id>/returns/<return_id>/grade", methods=["POST"])
def grade_return(client_id, return_id):
    _, role = get_auth()
    require_roles(role, {"ReturnsClerk"})
    rec = _resolve_return(client_id, return_id)
    body = get_json_body()

    if rec["status"] != "REQUESTED":
        raise err("ERR_RETURN_NOT_REQUESTED", "Return is not REQUESTED")

    grade = body.get("grade")
    if grade not in {"SELLABLE", "DAMAGED"}:
        raise err("ERR_INVALID_REQUEST", "grade must be SELLABLE or DAMAGED")

    if grade == "SELLABLE":
        bin_rec = get_bin(rec["bin_id"])
        sku = store.skus.get(rec["sku_id"])
        # Same bin protections as putaway: OPEN -> PALLET -> CAPACITY.
        if bin_rec["status"] != "OPEN":
            raise err("ERR_BIN_BLOCKED", "Restock bin is BLOCKED")
        if bin_rec["bin_type"] == "PALLET" and bin_holds_other_client(bin_rec["id"], client_id):
            raise err("ERR_PALLET_OCCUPIED_BY_OTHER_CLIENT", "Pallet bin holds another client's inventory")
        added_cc = rec["qty"] * (sku["unit_volume_cc"] if sku else 0)
        if bin_occupied_cc(bin_rec["id"]) + added_cc > bin_rec["capacity_cc"]:
            raise err("ERR_BIN_CAPACITY_EXCEEDED", "Restock would exceed bin capacity")

        # Create or top up a lot for (client, sku, bin).
        lot = find_restock_lot(client_id, rec["sku_id"], rec["bin_id"])
        if lot is None:
            lot = stamp_create({
                "id": new_id(),
                "client_id": client_id,
                "sku_id": rec["sku_id"],
                "bin_id": rec["bin_id"],
                "receipt_id": None,
                "on_hand_qty": rec["qty"],
                "reserved_qty": 0,
            })
            store.inventory_lots[lot["id"]] = lot
        else:
            lot["on_hand_qty"] += rec["qty"]
            touch(lot)
        touch(bin_rec)
    # DAMAGED: scrap, no inventory change.

    rec["grade"] = grade
    rec["status"] = "GRADED"
    touch(rec)
    return success(serialize_return(rec))


@bp.route("/clients/<client_id>/returns/<return_id>/close", methods=["POST"])
def close_return(client_id, return_id):
    _, role = get_auth()
    require_roles(role, {"ReturnsClerk"})
    rec = _resolve_return(client_id, return_id)

    if rec["status"] != "GRADED":
        raise err("ERR_RETURN_NOT_GRADED", "Return is not GRADED")

    rec["status"] = "CLOSED"
    touch(rec)
    return success(serialize_return(rec))
