"""Transfer endpoints (PRD §3.10)."""
from flask import Blueprint, request

from db import DB
from middleware import auth_context, require_role
from common import (
    stamp_create, touch, public_view, get_json_body, as_int, as_str,
    parse_pagination, paginate,
)
from response import success, success_list
from errors import (
    err, ERR_NOT_FOUND, ERR_REFERENCE_NOT_FOUND, ERR_INVALID_STATE,
    ERR_STALE_VERSION, ERR_INSUFFICIENT_STOCK,
)
from services.inventory import recompute, find_item

bp = Blueprint("transfers", __name__)


@bp.route("/transfers", methods=["POST"])
def create_transfer():
    _, role = auth_context()
    require_role(role, {"InventoryClerk", "StoreManager"})
    body = get_json_body()
    from_store_id = as_str(body, "from_store_id")
    to_store_id = as_str(body, "to_store_id")
    product_id = as_str(body, "product_id")
    quantity = as_int(body, "quantity", minimum=1)
    with DB.lock:
        if from_store_id not in DB.stores:
            raise err(ERR_REFERENCE_NOT_FOUND, "from_store_id not found")
        if to_store_id not in DB.stores:
            raise err(ERR_REFERENCE_NOT_FOUND, "to_store_id not found")
        if product_id not in DB.products:
            raise err(ERR_REFERENCE_NOT_FOUND, "product_id not found")
        transfer = {
            "from_store_id": from_store_id,
            "to_store_id": to_store_id,
            "product_id": product_id,
            "quantity": quantity,
            "received_qty": None,
            "status": "REQUESTED",
        }
        stamp_create(transfer)
        DB.transfers[transfer["id"]] = transfer
        return success(public_view(transfer), status=201)


@bp.route("/transfers/<transfer_id>", methods=["GET"])
def get_transfer(transfer_id):
    _, role = auth_context()
    require_role(role, {"StoreManager", "InventoryClerk"})
    with DB.lock:
        transfer = DB.transfers.get(transfer_id)
        if transfer is None:
            raise err(ERR_NOT_FOUND, "Transfer not found")
        return success(public_view(transfer))


@bp.route("/transfers", methods=["GET"])
def list_transfers():
    _, role = auth_context()
    require_role(role, {"StoreManager", "InventoryClerk"})
    limit, offset = parse_pagination()
    from_store_id = request.args.get("from_store_id")
    to_store_id = request.args.get("to_store_id")
    product_id = request.args.get("product_id")
    status = request.args.get("status")
    with DB.lock:
        recs = list(DB.transfers.values())
        if from_store_id is not None:
            recs = [r for r in recs if r["from_store_id"] == from_store_id]
        if to_store_id is not None:
            recs = [r for r in recs if r["to_store_id"] == to_store_id]
        if product_id is not None:
            recs = [r for r in recs if r["product_id"] == product_id]
        if status is not None:
            recs = [r for r in recs if r["status"] == status]
        items, total = paginate(recs, limit, offset)
        return success_list(items, limit, offset, total)


@bp.route("/transfers/<transfer_id>/dispatch", methods=["POST"])
def dispatch_transfer(transfer_id):
    _, role = auth_context()
    require_role(role, {"InventoryClerk"})
    body = get_json_body()
    expected = as_int(body, "expected_transfer_version")
    with DB.lock:
        transfer = DB.transfers.get(transfer_id)
        if transfer is None:
            raise err(ERR_NOT_FOUND, "Transfer not found")
        # OCC (priority 7) precedes state check (priority 8) (PRD §2.7, §3.13)
        if expected != transfer["version"]:
            raise err(ERR_STALE_VERSION, "Stale transfer version")
        if transfer["status"] != "REQUESTED":
            raise err(ERR_INVALID_STATE, "Transfer is not REQUESTED")
        # stock availability (priority 14)
        src = find_item(DB, transfer["from_store_id"], transfer["product_id"])
        if src is None or src["available_qty"] < transfer["quantity"]:
            raise err(ERR_INSUFFICIENT_STOCK, "Insufficient available stock at source")
        src["reserved_qty"] += transfer["quantity"]
        recompute(src)
        transfer["status"] = "DISPATCHED"
        touch(transfer)
        return success(public_view(transfer))


@bp.route("/transfers/<transfer_id>/receive", methods=["POST"])
def receive_transfer(transfer_id):
    _, role = auth_context()
    require_role(role, {"InventoryClerk"})
    body = get_json_body()
    with DB.lock:
        transfer = DB.transfers.get(transfer_id)
        if transfer is None:
            raise err(ERR_NOT_FOUND, "Transfer not found")
        # received_qty between 0 and quantity inclusive (PRD §3.10)
        received_qty = as_int(body, "received_qty", minimum=0,
                              maximum=transfer["quantity"])
        if transfer["status"] != "DISPATCHED":
            raise err(ERR_INVALID_STATE, "Transfer is not DISPATCHED")
        dest = find_item(DB, transfer["to_store_id"], transfer["product_id"])
        if dest is None:
            raise err(ERR_REFERENCE_NOT_FOUND, "Destination inventory item does not exist")
        src = find_item(DB, transfer["from_store_id"], transfer["product_id"])
        # source: on_hand and reserved each decremented by original quantity
        src["on_hand_qty"] -= transfer["quantity"]
        src["reserved_qty"] -= transfer["quantity"]
        recompute(src)
        # destination: on_hand increased by received_qty; shrinkage written off
        dest["on_hand_qty"] += received_qty
        recompute(dest)
        transfer["received_qty"] = received_qty
        transfer["status"] = "RECEIVED"
        touch(transfer)
        return success(public_view(transfer))


@bp.route("/transfers/<transfer_id>/reject", methods=["POST"])
def reject_transfer(transfer_id):
    _, role = auth_context()
    require_role(role, {"InventoryClerk"})
    with DB.lock:
        transfer = DB.transfers.get(transfer_id)
        if transfer is None:
            raise err(ERR_NOT_FOUND, "Transfer not found")
        if transfer["status"] != "DISPATCHED":
            raise err(ERR_INVALID_STATE, "Transfer is not DISPATCHED")
        src = find_item(DB, transfer["from_store_id"], transfer["product_id"])
        src["reserved_qty"] -= transfer["quantity"]
        recompute(src)
        transfer["status"] = "REJECTED"
        touch(transfer)
        return success(public_view(transfer))


@bp.route("/transfers/<transfer_id>/cancel", methods=["POST"])
def cancel_transfer(transfer_id):
    _, role = auth_context()
    require_role(role, {"InventoryClerk", "StoreManager"})
    with DB.lock:
        transfer = DB.transfers.get(transfer_id)
        if transfer is None:
            raise err(ERR_NOT_FOUND, "Transfer not found")
        if transfer["status"] != "REQUESTED":
            raise err(ERR_INVALID_STATE, "Transfer is not REQUESTED")
        transfer["status"] = "CANCELLED"
        touch(transfer)
        return success(public_view(transfer))
