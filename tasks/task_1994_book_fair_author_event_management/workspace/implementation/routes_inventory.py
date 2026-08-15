"""Stock lines, preorders, and register sales."""

from flask import Blueprint

import db
from errors import fail
from middleware import ALL_ROLES, require_roles
from response import success, success_list
from routes_core import get_or_404
from services import (
    D,
    cancel_preorder,
    new_entity,
    price_within_band,
    recompute_availability,
    rhu,
    touch,
)
from util import (
    get_body,
    list_filtered,
    page,
    pagination_params,
    v_int,
    v_enum,
    v_str,
    validate_body,
)

bp = Blueprint("inventory", __name__)


# ---------------------------------------------------------------------------
# Stock lines
# ---------------------------------------------------------------------------

@bp.post("/stock-lines")
@require_roles("Organizer")
def create_stock_line():
    data = get_body()
    fair_id = data.get("fair_id")
    if isinstance(fair_id, str) and fair_id not in db.fairs:
        fail("ERR_NOT_FOUND", "fair_id references no existing Fair")
    agreement_id = data.get("agreement_id")
    if isinstance(agreement_id, str) and agreement_id not in db.agreements:
        fail("ERR_NOT_FOUND", "agreement_id references no existing ConsignmentAgreement")
    vals = validate_body(
        data,
        [
            ("fair_id", True, v_str),
            ("agreement_id", True, v_str),
            ("isbn", True, v_str),
            ("title", True, v_str),
            ("list_price_cents", True, v_int(1)),
            ("line_type", True, v_enum("FRONTLIST", "BACKLIST")),
            ("qty_committed", True, v_int(1)),
        ],
    )
    agreement = db.agreements[vals["agreement_id"]]
    if agreement["fair_id"] != vals["fair_id"]:
        fail("ERR_LINE_FAIR_MISMATCH", "Agreement belongs to a different fair")
    line = new_entity(
        fair_id=vals["fair_id"],
        agreement_id=vals["agreement_id"],
        isbn=vals["isbn"],
        title=vals["title"],
        list_price_cents=vals["list_price_cents"],
        line_type=vals["line_type"],
        qty_committed=vals["qty_committed"],
        qty_delivered=0,
        qty_held_preorder=0,
        qty_sold=0,
        qty_damaged=0,
        qty_returned_shipped=0,
        qty_returned_credited=0,
        qty_on_hand_counted=None,
        qty_available_for_sale=0,
        status="QUOTED",
    )
    db.stock_lines[line["id"]] = line
    return success(line, 201)


@bp.get("/stock-lines")
@require_roles(*ALL_ROLES)
def list_stock_lines():
    limit, offset = pagination_params()
    items = list_filtered(
        db.stock_lines,
        [
            ("fair_id", "fair_id"),
            ("agreement_id", "agreement_id"),
            ("status", "status"),
            ("line_type", "line_type"),
        ],
    )
    items, total = page(items, limit, offset)
    return success_list(items, total, limit, offset)


@bp.get("/stock-lines/<sid>")
@require_roles(*ALL_ROLES)
def get_stock_line(sid):
    return success(get_or_404(db.stock_lines, sid, "StockLine"))


@bp.post("/stock-lines/<sid>/commit")
@require_roles("Organizer")
def commit_stock_line(sid):
    line = get_or_404(db.stock_lines, sid, "StockLine")
    validate_body(get_body(), [])
    if line["status"] != "QUOTED":
        fail("ERR_INVALID_STATE", "StockLine is not in QUOTED")
    agreement = db.agreements[line["agreement_id"]]
    if agreement["status"] != "ACCEPTED":
        fail("ERR_AGREEMENT_NOT_ACCEPTED", "Line's agreement is not ACCEPTED")
    fair = db.fairs[line["fair_id"]]
    if fair["status"] not in ("SCHEDULED", "STOCKING"):
        fail("ERR_INVALID_STATE", "Line's fair must be SCHEDULED or STOCKING")
    line["status"] = "COMMITTED"
    touch(line)
    return success(line)


@bp.post("/stock-lines/<sid>/deliver")
@require_roles("Organizer")
def deliver_stock_line(sid):
    line = get_or_404(db.stock_lines, sid, "StockLine")
    vals = validate_body(get_body(), [("qty_delivered", True, v_int(0))])
    if line["status"] != "COMMITTED":
        fail("ERR_INVALID_STATE", "StockLine is not in COMMITTED")
    fair = db.fairs[line["fair_id"]]
    if fair["status"] not in ("STOCKING", "OPEN"):
        fail("ERR_INVALID_STATE", "Line's fair must be STOCKING or OPEN")
    if vals["qty_delivered"] > line["qty_committed"]:
        fail("ERR_OVER_DELIVERY", "qty_delivered exceeds qty_committed")
    line["qty_delivered"] = vals["qty_delivered"]
    line["status"] = "DELIVERED"
    recompute_availability(line)
    touch(line)
    if line["line_type"] == "BACKLIST":
        agreement = db.agreements[line["agreement_id"]]
        amount = D(line["qty_delivered"]) * D(line["list_price_cents"]) * (
            1 - D(agreement["discount_pct"])
        )
        fair["firm_purchases_cents"] += rhu(amount)
        touch(fair)
    return success(line)


@bp.post("/stock-lines/<sid>/damage")
@require_roles("Organizer")
def damage_stock_line(sid):
    line = get_or_404(db.stock_lines, sid, "StockLine")
    vals = validate_body(get_body(), [("qty", True, v_int(1))])
    if line["status"] != "DELIVERED":
        fail("ERR_INVALID_STATE", "Damage can only be recorded against a DELIVERED line")
    fair = db.fairs[line["fair_id"]]
    if fair["status"] not in ("OPEN", "RECONCILING"):
        fail("ERR_INVALID_STATE", "Damage write-off requires the fair to be OPEN or RECONCILING")
    on_hand = (
        line["qty_delivered"]
        - line["qty_sold"]
        - line["qty_damaged"]
        - line["qty_returned_shipped"]
        - line["qty_held_preorder"]
    )
    if vals["qty"] > on_hand:
        fail("ERR_DAMAGE_EXCEEDS_ON_HAND", "Damage qty exceeds unsold, unheld on-hand copies")
    line["qty_damaged"] += vals["qty"]
    recompute_availability(line)
    touch(line)
    return success(line)


# ---------------------------------------------------------------------------
# Preorders
# ---------------------------------------------------------------------------

@bp.post("/preorders")
@require_roles("Cashier")
def create_preorder():
    data = get_body()
    fair_id = data.get("fair_id")
    if isinstance(fair_id, str) and fair_id not in db.fairs:
        fail("ERR_NOT_FOUND", "fair_id references no existing Fair")
    stock_line_id = data.get("stock_line_id")
    if isinstance(stock_line_id, str) and stock_line_id not in db.stock_lines:
        fail("ERR_NOT_FOUND", "stock_line_id references no existing StockLine")
    vals = validate_body(
        data,
        [
            ("fair_id", True, v_str),
            ("stock_line_id", True, v_str),
            ("customer_name", True, v_str),
            ("qty", True, v_int(1)),
        ],
    )
    line = db.stock_lines[vals["stock_line_id"]]
    # Referential (20) is checked before the intake window (28).
    if line["fair_id"] != vals["fair_id"]:
        fail("ERR_LINE_FAIR_MISMATCH", "Stock line belongs to a different fair")
    fair = db.fairs[vals["fair_id"]]
    if fair["status"] not in ("SCHEDULED", "STOCKING"):
        fail("ERR_PREORDER_WINDOW_CLOSED", "Preorder intake requires the fair to be SCHEDULED or STOCKING")
    preorder = new_entity(
        fair_id=vals["fair_id"],
        stock_line_id=vals["stock_line_id"],
        customer_name=vals["customer_name"],
        qty=vals["qty"],
        fulfillment_price_cents=None,
        status="PLACED",
    )
    db.preorders[preorder["id"]] = preorder
    return success(preorder, 201)


@bp.get("/preorders")
@require_roles(*ALL_ROLES)
def list_preorders():
    limit, offset = pagination_params()
    items = list_filtered(
        db.preorders,
        [("fair_id", "fair_id"), ("stock_line_id", "stock_line_id"), ("status", "status")],
    )
    items, total = page(items, limit, offset)
    return success_list(items, total, limit, offset)


@bp.get("/preorders/<pid>")
@require_roles(*ALL_ROLES)
def get_preorder(pid):
    return success(get_or_404(db.preorders, pid, "Preorder"))


@bp.post("/preorders/<pid>/fulfill")
@require_roles("Cashier")
def fulfill_preorder(pid):
    preorder = get_or_404(db.preorders, pid, "Preorder")
    validate_body(get_body(), [])
    if preorder["status"] != "ALLOCATED":
        fail("ERR_INVALID_STATE", "Preorder is not in ALLOCATED")
    fair = db.fairs[preorder["fair_id"]]
    if fair["status"] != "OPEN":
        fail("ERR_FAIR_NOT_OPEN", "Preorder fulfillment requires the fair to be OPEN")
    line = db.stock_lines[preorder["stock_line_id"]]
    price = preorder["qty"] * line["list_price_cents"]
    preorder["fulfillment_price_cents"] = price
    preorder["status"] = "FULFILLED"
    touch(preorder)
    line["qty_held_preorder"] -= preorder["qty"]
    line["qty_sold"] += preorder["qty"]
    recompute_availability(line)
    touch(line)
    fair["gross_sales_cents"] += price
    touch(fair)
    return success(preorder)


@bp.post("/preorders/<pid>/cancel")
@require_roles("Cashier")
def cancel_preorder_endpoint(pid):
    preorder = get_or_404(db.preorders, pid, "Preorder")
    validate_body(get_body(), [])
    if preorder["status"] not in ("PLACED", "ALLOCATED"):
        fail("ERR_INVALID_STATE", "Preorder cannot be cancelled from its current state")
    fair = db.fairs[preorder["fair_id"]]
    if fair["status"] in ("RECONCILING", "SETTLED", "CANCELLED"):
        fail("ERR_INVALID_STATE", "Preorder cannot be cancelled while the fair is closing or closed")
    cancel_preorder(preorder)
    return success(preorder)


# ---------------------------------------------------------------------------
# Sales
# ---------------------------------------------------------------------------

def _parse_sale_lines(raw):
    if not isinstance(raw, list) or len(raw) == 0:
        fail("ERR_VALIDATION", "lines must be a non-empty array")
    parsed = []
    for item in raw:
        if not isinstance(item, dict):
            fail("ERR_VALIDATION", "each sale line must be an object")
        unknown = sorted(set(item.keys()) - {"stock_line_id", "qty", "unit_price_cents"})
        if unknown:
            fail("ERR_VALIDATION", "Unknown line field(s): %s" % ", ".join(unknown))
        if "stock_line_id" not in item or not isinstance(item["stock_line_id"], str):
            fail("ERR_VALIDATION", "line stock_line_id must be a string")
        parsed.append(item)
    return parsed


@bp.post("/sales")
@require_roles("Cashier")
def create_sale():
    data = get_body()
    fair_id = data.get("fair_id")
    if isinstance(fair_id, str) and fair_id not in db.fairs:
        fail("ERR_NOT_FOUND", "fair_id references no existing Fair")
    raw_lines = data.get("lines")
    line_items = _parse_sale_lines(raw_lines) if isinstance(raw_lines, list) else None
    if line_items:
        for item in line_items:
            if item["stock_line_id"] not in db.stock_lines:
                fail("ERR_NOT_FOUND", "line stock_line_id references no existing StockLine")
    if "fair_id" not in data or not isinstance(data.get("fair_id"), str):
        fail("ERR_VALIDATION", "fair_id must be a string")
    if line_items is None:
        fail("ERR_VALIDATION", "lines must be a non-empty array")
    unknown = sorted(set(data.keys()) - {"fair_id", "lines"})
    if unknown:
        fail("ERR_VALIDATION", "Unknown field(s): %s" % ", ".join(unknown))
    lines = []
    for item in line_items:
        qty = item.get("qty")
        if not isinstance(qty, int) or isinstance(qty, bool) or qty <= 0:
            fail("ERR_VALIDATION", "line qty must be a positive integer")
        unit = item.get("unit_price_cents")
        if unit is not None and (not isinstance(unit, int) or isinstance(unit, bool)):
            fail("ERR_VALIDATION", "line unit_price_cents must be an integer")
        lines.append({"stock_line_id": item["stock_line_id"], "qty": qty, "unit_price_cents": unit})
    fair = db.fairs[data["fair_id"]]
    # Referential (20) before fiscal band (21).
    for line in lines:
        stock = db.stock_lines[line["stock_line_id"]]
        if stock["fair_id"] != fair["id"]:
            fail("ERR_LINE_FAIR_MISMATCH", "Stock line belongs to a different fair")
    total = 0
    for line in lines:
        stock = db.stock_lines[line["stock_line_id"]]
        if line["unit_price_cents"] is None:
            line["unit_price_cents"] = stock["list_price_cents"]
        if not price_within_band(stock, line["unit_price_cents"]):
            fail("ERR_PRICE_BEYOND_MARKDOWN", "unit_price_cents outside the markdown band")
        total += line["qty"] * line["unit_price_cents"]
    sale = new_entity(
        fair_id=fair["id"],
        lines=lines,
        total_cents=total,
        tendered_amount_cents=None,
        change_cents=None,
        status="DRAFT",
    )
    db.sales[sale["id"]] = sale
    return success(sale, 201)


@bp.get("/sales")
@require_roles(*ALL_ROLES)
def list_sales():
    limit, offset = pagination_params()
    items = list_filtered(db.sales, [("fair_id", "fair_id"), ("status", "status")])
    items, total = page(items, limit, offset)
    return success_list(items, total, limit, offset)


@bp.get("/sales/<sid>")
@require_roles(*ALL_ROLES)
def get_sale(sid):
    return success(get_or_404(db.sales, sid, "SaleTransaction"))


@bp.post("/sales/<sid>/tender")
@require_roles("Cashier")
def tender_sale(sid):
    sale = get_or_404(db.sales, sid, "SaleTransaction")
    vals = validate_body(get_body(), [("tendered_amount_cents", True, v_int(0))])
    if sale["status"] != "DRAFT":
        fail("ERR_INVALID_STATE", "Sale is not in DRAFT")
    fair = db.fairs[sale["fair_id"]]
    # State checks run before fiscal checks (pinned workflow order).
    if fair["status"] != "OPEN":
        fail("ERR_FAIR_NOT_OPEN", "Tender requires the fair to be OPEN")
    for line in sale["lines"]:
        stock = db.stock_lines[line["stock_line_id"]]
        if stock["status"] != "DELIVERED" or stock["fair_id"] != fair["id"]:
            fail("ERR_LINE_FAIR_MISMATCH", "Every line must be DELIVERED and belong to the sale's fair")
    for line in sale["lines"]:
        stock = db.stock_lines[line["stock_line_id"]]
        if line["qty"] > stock["qty_available_for_sale"]:
            fail("ERR_STOCK_NOT_AVAILABLE", "Line qty exceeds qty_available_for_sale")
    for line in sale["lines"]:
        stock = db.stock_lines[line["stock_line_id"]]
        if not price_within_band(stock, line["unit_price_cents"]):
            fail("ERR_PRICE_BEYOND_MARKDOWN", "unit_price_cents outside the markdown band")
    if vals["tendered_amount_cents"] < sale["total_cents"]:
        fail("ERR_TENDER_SHORT", "tendered_amount_cents is less than total_cents")
    for line in sale["lines"]:
        stock = db.stock_lines[line["stock_line_id"]]
        stock["qty_sold"] += line["qty"]
        recompute_availability(stock)
        touch(stock)
    fair["gross_sales_cents"] += sale["total_cents"]
    touch(fair)
    sale["status"] = "TENDERED"
    sale["tendered_amount_cents"] = vals["tendered_amount_cents"]
    sale["change_cents"] = vals["tendered_amount_cents"] - sale["total_cents"]
    touch(sale)
    return success(sale)


@bp.post("/sales/<sid>/void")
@require_roles("Cashier")
def void_sale(sid):
    sale = get_or_404(db.sales, sid, "SaleTransaction")
    validate_body(get_body(), [])
    if sale["status"] not in ("DRAFT", "TENDERED"):
        fail("ERR_INVALID_STATE", "Sale cannot be voided from its current state")
    fair = db.fairs[sale["fair_id"]]
    if fair["status"] != "OPEN":
        fail("ERR_FAIR_NOT_OPEN", "Void requires the fair to be OPEN")
    if sale["status"] == "TENDERED":
        for line in sale["lines"]:
            stock = db.stock_lines[line["stock_line_id"]]
            stock["qty_sold"] -= line["qty"]
            recompute_availability(stock)
            touch(stock)
        fair["gross_sales_cents"] -= sale["total_cents"]
        touch(fair)
    sale["status"] = "VOIDED"
    touch(sale)
    return success(sale)
