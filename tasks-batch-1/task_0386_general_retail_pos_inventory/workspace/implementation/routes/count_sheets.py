"""CountSheet endpoints (PRD §3.11)."""
from flask import Blueprint, request

from db import DB
from middleware import auth_context, require_role
from common import (
    stamp_create, touch, public_view, get_json_body, as_int,
    as_str, parse_pagination, paginate,
)
from response import success, success_list
from errors import (
    err, ERR_NOT_FOUND, ERR_REFERENCE_NOT_FOUND, ERR_INVALID_STATE,
    ERR_COUNT_STALE,
)
from services.inventory import recompute

bp = Blueprint("count_sheets", __name__)


@bp.route("/count-sheets", methods=["POST"])
def create_count_sheet():
    _, role = auth_context()
    require_role(role, {"InventoryClerk"})
    body = get_json_body()
    inventory_item_id = as_str(body, "inventory_item_id")
    counted_qty = as_int(body, "counted_qty", minimum=0)
    with DB.lock:
        item = DB.inventory_items.get(inventory_item_id)
        if item is None:
            raise err(ERR_REFERENCE_NOT_FOUND, "inventory_item_id not found")
        sheet = {
            "inventory_item_id": inventory_item_id,
            "counted_qty": counted_qty,
            "snapshot_on_hand_qty": item["on_hand_qty"],
            "variance_qty": None,
            "status": "DRAFT",
        }
        stamp_create(sheet)
        DB.count_sheets[sheet["id"]] = sheet
        return success(public_view(sheet), status=201)


@bp.route("/count-sheets/<sheet_id>", methods=["GET"])
def get_count_sheet(sheet_id):
    _, role = auth_context()
    require_role(role, {"StoreManager", "InventoryClerk"})
    with DB.lock:
        sheet = DB.count_sheets.get(sheet_id)
        if sheet is None:
            raise err(ERR_NOT_FOUND, "Count sheet not found")
        return success(public_view(sheet))


@bp.route("/count-sheets", methods=["GET"])
def list_count_sheets():
    _, role = auth_context()
    require_role(role, {"StoreManager", "InventoryClerk"})
    limit, offset = parse_pagination()
    inventory_item_id = request.args.get("inventory_item_id")
    status = request.args.get("status")
    with DB.lock:
        recs = list(DB.count_sheets.values())
        if inventory_item_id is not None:
            recs = [r for r in recs if r["inventory_item_id"] == inventory_item_id]
        if status is not None:
            recs = [r for r in recs if r["status"] == status]
        items, total = paginate(recs, limit, offset)
        return success_list(items, limit, offset, total)


@bp.route("/count-sheets/<sheet_id>/post", methods=["POST"])
def post_count_sheet(sheet_id):
    _, role = auth_context()
    require_role(role, {"InventoryClerk"})
    with DB.lock:
        sheet = DB.count_sheets.get(sheet_id)
        if sheet is None:
            raise err(ERR_NOT_FOUND, "Count sheet not found")
        # state check (priority 8) before count-staleness (priority 16)
        if sheet["status"] != "DRAFT":
            raise err(ERR_INVALID_STATE, "Count sheet is not DRAFT")
        item = DB.inventory_items[sheet["inventory_item_id"]]
        # ERR_COUNT_STALE: on_hand_qty moved since the sheet opened (PRD §3.11)
        if item["on_hand_qty"] != sheet["snapshot_on_hand_qty"]:
            raise err(ERR_COUNT_STALE, "Inventory moved since the sheet was opened")
        sheet["variance_qty"] = sheet["counted_qty"] - sheet["snapshot_on_hand_qty"]
        sheet["status"] = "POSTED"
        item["on_hand_qty"] = sheet["counted_qty"]
        recompute(item)
        touch(sheet)
        return success(public_view(sheet))


@bp.route("/count-sheets/<sheet_id>/discard", methods=["POST"])
def discard_count_sheet(sheet_id):
    _, role = auth_context()
    require_role(role, {"InventoryClerk"})
    with DB.lock:
        sheet = DB.count_sheets.get(sheet_id)
        if sheet is None:
            raise err(ERR_NOT_FOUND, "Count sheet not found")
        if sheet["status"] != "DRAFT":
            raise err(ERR_INVALID_STATE, "Count sheet is not DRAFT")
        sheet["status"] = "DISCARDED"
        touch(sheet)
        return success(public_view(sheet))
