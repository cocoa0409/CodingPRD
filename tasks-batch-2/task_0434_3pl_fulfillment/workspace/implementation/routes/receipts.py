"""Receipt endpoints and lifecycle (PRD §3.2)."""
from flask import Blueprint, request

from db import store, new_id, stamp_create, touch
from errors import err
from middleware import get_auth, require_roles
from response import success
from common import (
    get_client, get_sku, get_bin, get_receipt,
    get_json_body, parse_pagination, paginate,
)
from serializers import serialize_receipt
from services.inventory import bin_occupied_cc, bin_holds_other_client, find_or_create_lot

bp = Blueprint("receipts", __name__)

READ_ROLES = {"ReceivingClerk", "ClientUser", "BillingClerk"}


def _filter_receipts(items):
    for key in ("client_id", "sku_id", "bin_id"):
        val = request.args.get(key)
        if val is not None:
            items = [r for r in items if r.get(key) == val]
    return items


@bp.route("/receipts", methods=["GET"])
def list_receipts():
    _, role = get_auth()
    require_roles(role, READ_ROLES)
    limit, offset = parse_pagination()
    items = _filter_receipts(list(store.receipts.values()))
    page, meta = paginate(items, limit, offset)
    return success([serialize_receipt(r) for r in page], pagination=meta)


@bp.route("/receipts/<receipt_id>", methods=["GET"])
def get_one_receipt_flat(receipt_id):
    _, role = get_auth()
    require_roles(role, READ_ROLES)
    rec = get_receipt(receipt_id)
    return success(serialize_receipt(rec))


@bp.route("/clients/<client_id>/receipts", methods=["POST"])
def announce_receipt(client_id):
    _, role = get_auth()
    require_roles(role, {"ReceivingClerk"})
    client = get_client(client_id)
    body = get_json_body()

    sku_id = body.get("sku_id")
    bin_id = body.get("bin_id")
    if not isinstance(sku_id, str) or sku_id == "":
        raise err("ERR_INVALID_REQUEST", "sku_id is required")
    if not isinstance(bin_id, str) or bin_id == "":
        raise err("ERR_INVALID_REQUEST", "bin_id is required")

    expected_qty = body.get("expected_qty")
    if isinstance(expected_qty, bool) or not isinstance(expected_qty, int):
        raise err("ERR_INVALID_REQUEST", "expected_qty must be an integer")
    if expected_qty <= 0:
        raise err("ERR_INVALID_REQUEST", "expected_qty must be > 0")

    # Existence of FK resources (priority 4).
    sku = get_sku(sku_id)
    bin_rec = get_bin(bin_id)

    # Cross-ownership: SKU must belong to path client (priority 7).
    if sku["client_id"] != client_id:
        raise err("ERR_CLIENT_OWNERSHIP_MISMATCH", "SKU not owned by path client")

    # Business: suspended client / discontinued SKU.
    if client["status"] == "SUSPENDED":
        raise err("ERR_CLIENT_SUSPENDED", "Client is suspended")
    if sku["status"] == "DISCONTINUED":
        raise err("ERR_SKU_DISCONTINUED", "SKU is discontinued")

    rec = stamp_create({
        "id": new_id(),
        "client_id": client_id,
        "sku_id": sku_id,
        "bin_id": bin_id,
        "expected_qty": expected_qty,
        "received_qty": 0,
        "status": "ANNOUNCED",
    })
    store.receipts[rec["id"]] = rec
    return success(serialize_receipt(rec), status=201)


@bp.route("/clients/<client_id>/receipts", methods=["GET"])
def list_client_receipts(client_id):
    _, role = get_auth()
    require_roles(role, READ_ROLES)
    get_client(client_id)
    limit, offset = parse_pagination()
    items = [r for r in store.receipts.values() if r["client_id"] == client_id]
    items = _filter_receipts(items)
    page, meta = paginate(items, limit, offset)
    return success([serialize_receipt(r) for r in page], pagination=meta)


def _resolve_receipt(client_id, receipt_id):
    get_client(client_id)
    rec = get_receipt(receipt_id)
    if rec["client_id"] != client_id:
        raise err("ERR_CLIENT_OWNERSHIP_MISMATCH", "Receipt not owned by path client")
    return rec


@bp.route("/clients/<client_id>/receipts/<receipt_id>", methods=["GET"])
def get_client_receipt(client_id, receipt_id):
    _, role = get_auth()
    require_roles(role, READ_ROLES)
    rec = _resolve_receipt(client_id, receipt_id)
    return success(serialize_receipt(rec))


@bp.route("/clients/<client_id>/receipts/<receipt_id>/receive", methods=["POST"])
def receive_receipt(client_id, receipt_id):
    _, role = get_auth()
    require_roles(role, {"ReceivingClerk"})
    rec = _resolve_receipt(client_id, receipt_id)
    body = get_json_body()

    if rec["status"] != "ANNOUNCED":
        raise err("ERR_RECEIPT_NOT_ANNOUNCED", "Receipt is not ANNOUNCED")

    received_qty = body.get("received_qty")
    if isinstance(received_qty, bool) or not isinstance(received_qty, int):
        raise err("ERR_INVALID_REQUEST", "received_qty must be an integer")
    if received_qty < 0:
        raise err("ERR_INVALID_REQUEST", "received_qty must be >= 0")

    rec["received_qty"] = received_qty
    rec["status"] = "RECEIVED"
    touch(rec)
    return success(serialize_receipt(rec))


@bp.route("/clients/<client_id>/receipts/<receipt_id>/putaway", methods=["POST"])
def putaway_receipt(client_id, receipt_id):
    _, role = get_auth()
    require_roles(role, {"ReceivingClerk"})
    rec = _resolve_receipt(client_id, receipt_id)

    if rec["status"] != "RECEIVED":
        raise err("ERR_RECEIPT_NOT_RECEIVED", "Receipt is not RECEIVED")

    bin_rec = get_bin(rec["bin_id"])
    sku = get_sku(rec["sku_id"])

    # Bin OPEN required (PRD §3.2 order: OPEN -> PALLET -> CAPACITY).
    if bin_rec["status"] != "OPEN":
        raise err("ERR_BIN_BLOCKED", "Destination bin is BLOCKED")

    # Pallet exclusivity.
    if bin_rec["bin_type"] == "PALLET" and bin_holds_other_client(bin_rec["id"], client_id):
        raise err("ERR_PALLET_OCCUPIED_BY_OTHER_CLIENT", "Pallet bin holds another client's inventory")

    # Capacity (inclusive boundary).
    qty = rec["received_qty"]
    added_cc = qty * sku["unit_volume_cc"]
    if bin_occupied_cc(bin_rec["id"]) + added_cc > bin_rec["capacity_cc"]:
        raise err("ERR_BIN_CAPACITY_EXCEEDED", "Putaway would exceed bin capacity")

    # Create or top up the lot for (client, sku, bin, receipt).
    lot = find_or_create_lot(client_id, rec["sku_id"], rec["bin_id"], receipt_id)
    if lot is None:
        lot = stamp_create({
            "id": new_id(),
            "client_id": client_id,
            "sku_id": rec["sku_id"],
            "bin_id": rec["bin_id"],
            "receipt_id": receipt_id,
            "on_hand_qty": qty,
            "reserved_qty": 0,
        })
        store.inventory_lots[lot["id"]] = lot
    else:
        lot["on_hand_qty"] += qty
        touch(lot)

    # Bin occupied_cc is derived; bin record version bumps (cascade per §2.8).
    touch(bin_rec)

    rec["status"] = "PUTAWAY"
    touch(rec)
    return success(serialize_receipt(rec))


@bp.route("/clients/<client_id>/receipts/<receipt_id>/cancel", methods=["POST"])
def cancel_receipt(client_id, receipt_id):
    _, role = get_auth()
    require_roles(role, {"ReceivingClerk"})
    rec = _resolve_receipt(client_id, receipt_id)

    if rec["status"] != "ANNOUNCED":
        raise err("ERR_RECEIPT_NOT_ANNOUNCED", "Receipt is not ANNOUNCED")

    rec["status"] = "CANCELLED"
    touch(rec)
    return success(serialize_receipt(rec))
