"""Catalog titles and distributor stock intake."""
from flask import Blueprint, request

from common import (json_body, make_record, touch, get_str, get_enum, get_bool,
                    get_int, parse_pagination, paginate)
from db import db
from errors import (err, ERR_NOT_FOUND, ERR_DUPLICATE_ISBN, ERR_INVALID_REQUEST)
from middleware import authorize
from response import success_object, success_list
from serialize import title_out, stock_item_out
from services import recompute_title_counts

bp = Blueprint("titles", __name__)

READ_ROLES = {"Member", "Bookseller", "InventoryManager", "StoreAdmin"}
WRITE_ROLES = {"Bookseller", "InventoryManager", "StoreAdmin"}


@bp.route("/titles", methods=["POST"])
def create_title():
    authorize(WRITE_ROLES)
    body = json_body(optional=False)
    isbn13 = get_str(body, "isbn13", required=True)
    # isbn13 must be exactly 13 digits — a malformed value is ERR_INVALID_REQUEST (400)
    if not (len(isbn13) == 13 and isbn13.isdigit()):
        raise err(ERR_INVALID_REQUEST, "isbn13 must be exactly 13 digits")
    name = get_str(body, "name", required=True)
    category = get_enum(body, "category", ["BOOK", "CAFE", "SIDELINE"],
                        required=False, default="BOOK")
    list_price_cents = get_int(body, "list_price_cents", required=True, minimum=0)
    returnable = get_bool(body, "returnable", required=False, default=True)
    demand_flag = get_enum(body, "demand_flag", ["HIGH", "NORMAL"],
                           required=False, default="NORMAL")
    pod_eligible = get_bool(body, "pod_eligible", required=False, default=False)

    # Uniqueness check (after shape validation). 13-digit duplicate -> 409.
    for t in db.titles.values():
        if t["isbn13"] == isbn13:
            raise err(ERR_DUPLICATE_ISBN, "isbn13 already exists")

    rec = make_record({
        "isbn13": isbn13,
        "name": name,
        "category": category,
        "list_price_cents": list_price_cents,
        "returnable": returnable,
        "demand_flag": demand_flag,
        "pod_eligible": pod_eligible,
        "on_hand_qty": 0,
        "reserved_qty": 0,
        "status": "ACTIVE",
    })
    db.titles[rec["id"]] = rec
    return success_object(title_out(rec), status=201)


def _find_title(tid):
    t = db.titles.get(tid)
    if t is None:
        raise err(ERR_NOT_FOUND, "Title not found")
    return t


@bp.route("/titles/<tid>", methods=["GET"])
def get_title(tid):
    authorize(READ_ROLES)
    t = _find_title(tid)
    return success_object(title_out(t), status=200)


@bp.route("/titles", methods=["GET"])
def list_titles():
    authorize(READ_ROLES)
    category = request.args.get("category")
    demand_flag = request.args.get("demand_flag")
    items = list(db.titles.values())
    if category is not None:
        items = [t for t in items if t["category"] == category]
    if demand_flag is not None:
        items = [t for t in items if t["demand_flag"] == demand_flag]
    limit, offset = parse_pagination(request.args)
    page, total = paginate(items, limit, offset)
    return success_list([title_out(t) for t in page], limit, offset, total)


@bp.route("/titles/<tid>/stock-items", methods=["POST"])
def receive_stock(tid):
    authorize(WRITE_ROLES)
    t = _find_title(tid)
    body = json_body(optional=False)
    quantity = get_int(body, "quantity", required=True, minimum=1)
    cost_cents = get_int(body, "cost_cents", required=False, default=0, minimum=0)

    last = None
    for _ in range(quantity):
        si = make_record({
            "title_id": tid,
            "source": "DISTRIBUTOR",
            "cost_cents": cost_cents,
            "state": "AVAILABLE",
            "reserved_order_line_id": None,
            "consignment_copy_id": None,
        })
        db.stock_items[si["id"]] = si
        last = si
    recompute_title_counts(t, mutate=True)
    # Endpoint returns a StockItem (the scaffold output). Return the last created.
    return success_object(stock_item_out(last), status=201)


@bp.route("/titles/<tid>/stock-items", methods=["GET"])
def list_title_stock(tid):
    authorize(READ_ROLES)
    t = _find_title(tid)
    state = request.args.get("state")
    items = [s for s in db.stock_items.values() if s["title_id"] == tid]
    if state is not None:
        items = [s for s in items if s["state"] == state]
    limit, offset = parse_pagination(request.args)
    page, total = paginate(items, limit, offset)
    return success_list([stock_item_out(s) for s in page], limit, offset, total)
