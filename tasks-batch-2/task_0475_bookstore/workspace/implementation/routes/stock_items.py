"""Cross-store StockItem reads."""
from flask import Blueprint, request

from common import parse_pagination, paginate
from db import db
from errors import err, ERR_NOT_FOUND
from middleware import authorize
from response import success_object, success_list
from serialize import stock_item_out

bp = Blueprint("stock_items", __name__)

# Read of stock items is operator-only (no Member) per PRD §4 table.
STOCK_ROLES = {"Bookseller", "InventoryManager", "StoreAdmin"}


@bp.route("/stock-items/<sid>", methods=["GET"])
def get_stock_item(sid):
    authorize(STOCK_ROLES)
    s = db.stock_items.get(sid)
    if s is None:
        raise err(ERR_NOT_FOUND, "Stock item not found")
    return success_object(stock_item_out(s), status=200)


@bp.route("/stock-items", methods=["GET"])
def list_stock_items():
    authorize(STOCK_ROLES)
    title_id = request.args.get("title_id")
    reserved_order_line_id = request.args.get("reserved_order_line_id")
    consignment_copy_id = request.args.get("consignment_copy_id")
    state = request.args.get("state")
    items = list(db.stock_items.values())
    if title_id is not None:
        items = [s for s in items if s["title_id"] == title_id]
    if reserved_order_line_id is not None:
        items = [s for s in items if s.get("reserved_order_line_id") == reserved_order_line_id]
    if consignment_copy_id is not None:
        items = [s for s in items if s.get("consignment_copy_id") == consignment_copy_id]
    if state is not None:
        items = [s for s in items if s["state"] == state]
    limit, offset = parse_pagination(request.args)
    page, total = paginate(items, limit, offset)
    return success_list([stock_item_out(s) for s in page], limit, offset, total)
