"""TradeIn + TradeInLine endpoints."""
from flask import Blueprint, request

import db
from models import base_fields, touch
from middleware import authenticate
from validators import (
    get_body, require_int, require_enum, require_grade, get_pagination,
    paginate, sorted_by_created, lookup,
)
from response import success, success_list
from errors import (
    err, ERR_INVALID_REQUEST, ERR_NOT_RESOURCE_OWNER, ERR_INVALID_STATE,
    ERR_INSPECTION_INCOMPLETE, ERR_INSUFFICIENT_CREDIT,
)
from services import public, public_list, recompute_tier
from routes.inventory import make_inventory_item
import calculations as calc

bp = Blueprint("tradeins", __name__)

FORMATS = {"VINYL", "CD", "CASSETTE"}
PAYOUT_METHODS = {"CREDIT", "CASH"}


def _lines(tid):
    return [l for l in db.db.trade_in_lines.values() if l["trade_in_id"] == tid]


def _owner_check(role, user_id, customer_id):
    if role == "Customer" and user_id != customer_id:
        raise err(ERR_NOT_RESOURCE_OWNER, "Customer does not own this resource")


@bp.route("/shop/trade-ins", methods=["POST"])
def create_tradein():
    user_id, role = authenticate({"Customer"})
    body = get_body()
    customer_id = body.get("customer_id")
    if not isinstance(customer_id, str) or not customer_id:
        raise err(ERR_INVALID_REQUEST, "customer_id required")
    payout = body.get("payout_method", "CREDIT")
    if payout is None:
        payout = "CREDIT"
    if payout not in PAYOUT_METHODS:
        raise err(ERR_INVALID_REQUEST, "payout_method must be CREDIT or CASH")
    lookup(db.db.customers, customer_id)
    _owner_check(role, user_id, customer_id)
    ti = base_fields()
    ti.update({
        "customer_id": customer_id,
        "payout_method": payout,
        "status": "DRAFT",
        "provisional_value_cents": 0,
        "final_value_cents": 0,
    })
    db.db.trade_ins[ti["id"]] = ti
    return success(public(ti), 201)


@bp.route("/shop/trade-ins/<tid>", methods=["GET"])
def read_tradein(tid):
    authenticate({"Customer", "Grader", "Manager"})
    ti = lookup(db.db.trade_ins, tid)
    return success(public(ti), 200)


@bp.route("/shop/trade-ins", methods=["GET"])
def list_tradeins():
    authenticate({"Customer", "Grader", "Manager"})
    limit, offset = get_pagination()
    customer_id = request.args.get("customer_id")
    status = request.args.get("status")
    items = list(db.db.trade_ins.values())
    if customer_id is not None:
        items = [t for t in items if t["customer_id"] == customer_id]
    if status is not None:
        items = [t for t in items if t["status"] == status]
    items = sorted_by_created(items)
    page, total = paginate(items, limit, offset)
    return success_list(public_list(page), limit, offset, total)


@bp.route("/shop/trade-ins/<tid>/lines", methods=["POST"])
def add_tradein_line(tid):
    user_id, role = authenticate({"Customer"})
    ti = lookup(db.db.trade_ins, tid)
    _owner_check(role, user_id, ti["customer_id"])
    if ti["status"] != "DRAFT":
        raise err(ERR_INVALID_STATE, "Trade-in is not DRAFT")
    body = get_body()
    fmt = require_enum(body, "format", FORMATS)
    claimed = require_grade(body, "claimed_grade")
    base_value = require_int(body, "base_value_cents")
    if base_value <= 0:
        raise err(ERR_INVALID_REQUEST, "base_value_cents must be > 0")
    line = base_fields()
    line.update({
        "trade_in_id": tid,
        "format": fmt,
        "claimed_grade": claimed,
        "inspected_grade": None,
        "base_value_cents": base_value,
    })
    db.db.trade_in_lines[line["id"]] = line
    return success(public(line), 201)


@bp.route("/shop/trade-ins/<tid>/lines", methods=["GET"])
def list_tradein_lines(tid):
    authenticate({"Customer", "Grader", "Manager"})
    lookup(db.db.trade_ins, tid)
    limit, offset = get_pagination()
    items = sorted_by_created(_lines(tid))
    page, total = paginate(items, limit, offset)
    return success_list(public_list(page), limit, offset, total)


@bp.route("/shop/trade-ins/<tid>/submit", methods=["POST"])
def submit_tradein(tid):
    user_id, role = authenticate({"Customer"})
    ti = lookup(db.db.trade_ins, tid)
    _owner_check(role, user_id, ti["customer_id"])
    if ti["status"] != "DRAFT":
        raise err(ERR_INVALID_STATE, "Trade-in is not DRAFT")
    lines = _lines(tid)
    if len(lines) < 1:
        raise err(ERR_INVALID_STATE, "Trade-in has no lines")
    grades = [(l["claimed_grade"], l["base_value_cents"]) for l in lines]
    ti["provisional_value_cents"] = calc.trade_in_value(grades, ti["payout_method"], final=False)
    ti["status"] = "SUBMITTED"
    touch(ti)
    return success(public(ti), 200)


@bp.route("/shop/trade-ins/<tid>/start-inspection", methods=["POST"])
def start_inspection(tid):
    authenticate({"Grader"})
    ti = lookup(db.db.trade_ins, tid)
    if ti["status"] != "SUBMITTED":
        raise err(ERR_INVALID_STATE, "Trade-in is not SUBMITTED")
    ti["status"] = "UNDER_INSPECTION"
    touch(ti)
    return success(public(ti), 200)


@bp.route("/shop/trade-in-lines/<lid>", methods=["PATCH"])
def set_inspected_grade(lid):
    authenticate({"Grader"})
    line = lookup(db.db.trade_in_lines, lid)
    ti = db.db.trade_ins.get(line["trade_in_id"])
    if ti is None or ti["status"] != "UNDER_INSPECTION":
        raise err(ERR_INVALID_STATE, "Trade-in is not UNDER_INSPECTION")
    body = get_body()
    grade = require_grade(body, "inspected_grade")
    line["inspected_grade"] = grade
    touch(line)
    return success(public(line), 200)


@bp.route("/shop/trade-ins/<tid>/approve", methods=["POST"])
def approve_tradein(tid):
    authenticate({"Grader"})
    ti = lookup(db.db.trade_ins, tid)
    if ti["status"] != "UNDER_INSPECTION":
        raise err(ERR_INVALID_STATE, "Trade-in is not UNDER_INSPECTION")
    lines = _lines(tid)
    if any(l["inspected_grade"] is None for l in lines):
        raise err(ERR_INSPECTION_INCOMPLETE, "Every line must have inspected_grade")
    grades = [(l["inspected_grade"], l["base_value_cents"]) for l in lines]
    final_value = calc.trade_in_value(grades, ti["payout_method"], final=True)
    ti["final_value_cents"] = final_value
    ti["status"] = "APPROVED"
    customer = db.db.customers[ti["customer_id"]]
    if ti["payout_method"] == "CREDIT":
        customer["store_credit_cents"] += final_value
        touch(customer)
    # create one AVAILABLE used InventoryItem per line at inspected grade
    created = []
    for l in lines:
        # need a product for the used copy; trade-in lines are format-only, no product_id.
        # Per scaffold, created item is a used copy at inspected_grade for the line's format.
        # There is no product FK on TradeInLine, so we cannot attach a product.
        item = _make_used_item_for_line(l)
        created.append(item["id"])
    ti["created_item_ids"] = created
    touch(ti)
    return success(public(ti), 200)


def _make_used_item_for_line(line):
    """Create a used InventoryItem for an approved trade-in line.

    TradeInLine has no product FK, so we mint a lightweight product-less copy is
    impossible; instead we create a product-less placeholder is not allowed.
    We attach to a synthetic product per line is overkill. Since the item MUST
    reference a product_id (FK), and the line carries no product, we create the
    item with product_id referencing None is invalid. We therefore create a
    minimal Product for the traded media so list_price can be computed.
    """
    # Create a backing product for the traded media (base = base_value_cents).
    prod = base_fields()
    prod.update({
        "artist": "",
        "title": "",
        "format": line["format"],
        "base_price_cents": line["base_value_cents"],
        "is_rsd_exclusive": False,
        "catalog_status": "DRAFT",
    })
    db.db.products[prod["id"]] = prod
    item = make_inventory_item(prod["id"], True, line["inspected_grade"], None)
    item["trade_in_id"] = line["trade_in_id"]
    return item


@bp.route("/shop/trade-ins/<tid>/reject", methods=["POST"])
def reject_tradein(tid):
    authenticate({"Grader"})
    ti = lookup(db.db.trade_ins, tid)
    if ti["status"] != "UNDER_INSPECTION":
        raise err(ERR_INVALID_STATE, "Trade-in is not UNDER_INSPECTION")
    ti["status"] = "REJECTED"
    touch(ti)
    return success(public(ti), 200)


@bp.route("/shop/trade-ins/<tid>/reverse", methods=["POST"])
def reverse_tradein(tid):
    authenticate({"Manager"})
    ti = lookup(db.db.trade_ins, tid)
    if ti["status"] != "APPROVED":
        raise err(ERR_INVALID_STATE, "Trade-in is not APPROVED")
    created = ti.get("created_item_ids", [])
    # no created item may be RESERVED or SOLD
    for iid in created:
        item = db.db.inventory_items.get(iid)
        if item is not None and item["status"] in ("RESERVED", "SOLD"):
            raise err(ERR_INVALID_STATE, "A created copy is RESERVED or SOLD")
    customer = db.db.customers[ti["customer_id"]]
    # PRD §3.6: reversal permitted only when store_credit_cents >= final_value_cents;
    # debit store_credit_cents by final_value_cents (conserves credit).
    clawback = ti["final_value_cents"]
    if customer["store_credit_cents"] < clawback:
        raise err(ERR_INSUFFICIENT_CREDIT, "Insufficient credit to claw back")
    customer["store_credit_cents"] -= clawback
    touch(customer)
    # void created items
    for iid in created:
        db.db.inventory_items.pop(iid, None)
    ti["status"] = "REVERSED"
    touch(ti)
    return success(public(ti), 200)
