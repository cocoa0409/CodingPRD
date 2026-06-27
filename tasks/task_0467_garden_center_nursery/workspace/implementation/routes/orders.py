"""Order endpoints: create, read, lines, and all state-machine transitions."""
from flask import Blueprint, request

import errors
from clock import clock
from db import db, base_versioned, touch
from errors import err
from lookups import body, get_account, get_order, get_product
from middleware import require_roles, parse_pagination, paginate
from response import ok, created, ok_list
from services import calc
from services.inventory import recompute_lot, maybe_deplete
from services.loyalty import append_event
from validation import req_int_gt, opt_bool, opt_int, req_int

bp = Blueprint("orders", __name__)


def order_view(o):
    return {
        "id": o["id"],
        "account_id": o["account_id"],
        "nursery_id": o["nursery_id"],
        "gross_total_cents": o["gross_total_cents"],
        "promo_discount_cents": o["promo_discount_cents"],
        "redemption_cents": o["redemption_cents"],
        "net_total_cents": o["net_total_cents"],
        "requested_redeem_points": o["requested_redeem_points"],
        "fulfillment_status": o["fulfillment_status"],
        "payment_status": o["payment_status"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


def line_view(ol):
    return {
        "id": ol["id"],
        "order_id": ol["order_id"],
        "product_id": ol["product_id"],
        "qty": ol["qty"],
        "unit_price_cents": ol["unit_price_cents"],
        "line_discount_cents": ol["line_discount_cents"],
        "line_net_cents": ol["line_net_cents"],
        "allocated_lot_id": ol["allocated_lot_id"],
        "status": ol["status"],
        "created_at": ol["created_at"],
        "updated_at": ol["updated_at"],
        "version": ol["version"],
    }


def _order_lines(order_id):
    lines = [ol for ol in db.order_lines.values() if ol["order_id"] == order_id]
    lines.sort(key=lambda x: x["_seq"])
    return lines


def _recompute_gross(order):
    lines = _order_lines(order["id"])
    order["gross_total_cents"] = sum(
        ol["qty"] * ol["unit_price_cents"] for ol in lines)


def _check_occ(order, data):
    """Stale-version OCC check (priority 16). expected_order_version required."""
    expected = data.get("expected_order_version")
    if not (isinstance(expected, int) and not isinstance(expected, bool)):
        err(errors.ERR_INVALID_REQUEST, "expected_order_version required (integer)")
    if expected != order["version"]:
        err(errors.ERR_STALE_VERSION, "expected_order_version does not match")


# --------------------------------------------------------------------------
# Create / read / lines
# --------------------------------------------------------------------------
@bp.post("/accounts/<account_id>/orders")
@require_roles("SalesClerk")
def create_order(account_id):
    account = get_account(account_id)
    o = base_versioned()
    o.update({
        "account_id": account_id,
        "nursery_id": account["nursery_id"],
        "gross_total_cents": 0,
        "promo_discount_cents": 0,
        "redemption_cents": 0,
        "net_total_cents": 0,
        "requested_redeem_points": 0,
        "fulfillment_status": "DRAFT",
        "payment_status": "UNPAID",
        "_redemption_points": 0,  # internal: points redeemed at confirm (for reversal)
    })
    db.orders[o["id"]] = o
    return created(order_view(o))


@bp.get("/orders/<order_id>")
@require_roles("SalesClerk", "InventoryManager")
def read_order(order_id):
    o = get_order(order_id)
    return ok(order_view(o))


@bp.post("/orders/<order_id>/lines")
@require_roles("SalesClerk")
def add_line(order_id):
    order = get_order(order_id)
    data = body()
    product_id = data.get("product_id")
    if not isinstance(product_id, str) or not product_id:
        err(errors.ERR_INVALID_REQUEST, "product_id required")
    qty = req_int_gt(data, "qty", 0)
    acknowledge = opt_bool(data, "acknowledge_hardiness_risk", False)

    # Body FK existence + same-nursery scope (priority 4)
    product = db.products.get(product_id)
    if product is None or product["nursery_id"] != order["nursery_id"]:
        err(errors.ERR_PRODUCT_NOT_FOUND, "product not found in nursery")

    # Hardiness advisory gate (priority 9) — LIVE_PLANT only
    if product["category"] == "LIVE_PLANT":
        account = db.accounts[order["account_id"]]
        zone = account["ship_to_hardiness_zone"]
        if zone < product["hardiness_min_zone"] or zone > product["hardiness_max_zone"]:
            if not acknowledge:
                err(errors.ERR_HARDINESS_ZONE_MISMATCH,
                    "planting zone outside product band")

    ol = base_versioned()
    unit_price = product["unit_price_cents"]
    ol.update({
        "order_id": order["id"],
        "product_id": product_id,
        "qty": qty,
        "unit_price_cents": unit_price,
        "line_discount_cents": 0,
        "line_net_cents": qty * unit_price,
        "allocated_lot_id": None,
        "status": "PENDING",
    })
    db.order_lines[ol["id"]] = ol

    _recompute_gross(order)
    touch(order)
    return created(line_view(ol))


@bp.get("/orders/<order_id>/lines")
@require_roles("SalesClerk", "InventoryManager")
def list_lines(order_id):
    get_order(order_id)
    limit, offset = parse_pagination()
    status = request.args.get("status")
    items = _order_lines(order_id)
    if status is not None:
        items = [ol for ol in items if ol["status"] == status]
    total = len(items)
    page = paginate(items, limit, offset)
    return ok_list([line_view(ol) for ol in page], limit, offset, total)


@bp.get("/orders/<order_id>/loyalty-events")
@require_roles("SalesClerk", "InventoryManager")
def order_loyalty_events(order_id):
    get_order(order_id)
    limit, offset = parse_pagination()
    from routes.loyalty_events import loyalty_event_view
    items = [e for e in db.loyalty_events.values()
             if e["source_kind"] == "ORDER" and e["source_ref_id"] == order_id]
    items.sort(key=lambda e: e["_seq"])
    total = len(items)
    page = paginate(items, limit, offset)
    return ok_list([loyalty_event_view(e) for e in page], limit, offset, total)


# --------------------------------------------------------------------------
# Pricing helpers (calc line_pricing + order_totals)
# --------------------------------------------------------------------------
def _applicable_promo(order, product):
    """Single best ACTIVE in-scope promo whose half-open window contains now."""
    now = clock.get()
    candidates = []
    for p in db.promotions.values():
        if p["nursery_id"] != order["nursery_id"]:
            continue
        if p["status"] != "ACTIVE":
            continue
        if not (p["category_scope"] == "ALL"
                or p["category_scope"] == product["category"]):
            continue
        if p["starts_at"] <= now < p["ends_at"]:
            candidates.append(p)
    if not candidates:
        return None
    # highest discount_pct, tie-break earliest created (_seq ascending)
    candidates.sort(key=lambda p: (-p["discount_pct"], p["_seq"]))
    return candidates[0]


def _run_line_pricing(order):
    for ol in _order_lines(order["id"]):
        product = db.products[ol["product_id"]]
        promo = _applicable_promo(order, product)
        if promo is None:
            ol["line_discount_cents"] = 0
        else:
            ol["line_discount_cents"] = calc.line_discount(
                ol["qty"], ol["unit_price_cents"], promo["discount_pct"])
        ol["line_net_cents"] = ol["qty"] * ol["unit_price_cents"] - ol["line_discount_cents"]


def _run_order_totals(order):
    lines = _order_lines(order["id"])
    gross = sum(ol["qty"] * ol["unit_price_cents"] for ol in lines)
    promo_total = sum(ol["line_discount_cents"] for ol in lines)
    requested = order["requested_redeem_points"]
    post_discount = gross - promo_total
    redemption = min(requested * calc.POINT_VALUE_CENTS, post_discount)
    if redemption < 0:
        redemption = 0
    net = max(0, gross - promo_total - redemption)
    order["gross_total_cents"] = gross
    order["promo_discount_cents"] = promo_total
    order["redemption_cents"] = redemption
    order["net_total_cents"] = net


# --------------------------------------------------------------------------
# Fulfillment dimension transitions
# --------------------------------------------------------------------------
@bp.post("/orders/<order_id>/confirm")
@require_roles("SalesClerk")
def confirm_order(order_id):
    order = get_order(order_id)
    data = body()
    requested = opt_int(data, "requested_redeem_points", 0)
    if requested < 0:
        err(errors.ERR_INVALID_REQUEST, "requested_redeem_points must be >= 0")

    # state precondition: DRAFT (priority 7). Empty-order check first per PRD §3.3.
    lines = _order_lines(order_id)
    if len(lines) < 1:
        err(errors.ERR_ORDER_EMPTY, "order has no lines")

    account = db.accounts[order["account_id"]]
    if account["status"] != "ACTIVE":
        err(errors.ERR_ACCOUNT_NOT_ACTIVE, "account not ACTIVE")

    if requested > account["points_balance"]:
        err(errors.ERR_INSUFFICIENT_POINTS, "requested redeem exceeds balance")

    _check_occ(order, data)

    order["requested_redeem_points"] = requested
    _run_line_pricing(order)
    _run_order_totals(order)

    if requested > 0:
        append_event(account, "REDEMPTION", -requested, "ORDER", order["id"])
        order["_redemption_points"] = requested
    else:
        order["_redemption_points"] = 0

    order["fulfillment_status"] = "CONFIRMED"
    touch(order)
    return ok(order_view(order))


@bp.post("/orders/<order_id>/allocate")
@require_roles("InventoryManager")
def allocate_order(order_id):
    order = get_order(order_id)
    data = body()
    if order["fulfillment_status"] != "CONFIRMED":
        err(errors.ERR_ORDER_NOT_CONFIRMED, "order not CONFIRMED")

    lines = _order_lines(order_id)

    # Feasibility (priority 13): each line satisfiable from a single AVAILABLE lot.
    # Pre-check all before committing any (atomicity). Must account for lots
    # already chosen for earlier lines in this same allocation.
    chosen = {}  # line_id -> lot
    reserved_running = {}  # lot_id -> qty tentatively reserved this allocate
    for ol in lines:
        lot = _select_lot(order, ol, reserved_running)
        if lot is None:
            err(errors.ERR_INSUFFICIENT_STOCK, "no lot can satisfy a line")
        chosen[ol["id"]] = lot
        reserved_running[lot["id"]] = reserved_running.get(lot["id"], 0) + ol["qty"]

    _check_occ(order, data)

    # Commit
    for ol in lines:
        lot = chosen[ol["id"]]
        lot["reserved_qty"] += ol["qty"]
        recompute_lot(lot)
        touch(lot)
        ol["allocated_lot_id"] = lot["id"]
        ol["status"] = "ALLOCATED"
        touch(ol)

    order["fulfillment_status"] = "ALLOCATED"
    touch(order)
    return ok(order_view(order))


def _select_lot(order, line, reserved_running):
    """lot_allocation_selector: AVAILABLE lots of product with effective qty_on_hand
    >= line.qty; oldest created_at first, tie-break smaller received_qty (FEFO).
    reserved_running accounts for lots already picked in this allocate pass."""
    product_id = line["product_id"]
    need = line["qty"]
    candidates = []
    for lot in db.inventory_lots.values():
        if lot["product_id"] != product_id:
            continue
        if lot["status"] != "AVAILABLE":
            continue
        effective = lot["qty_on_hand"] - reserved_running.get(lot["id"], 0)
        if effective >= need:
            candidates.append(lot)
    if not candidates:
        return None
    candidates.sort(key=lambda l: (l["created_at"], l["received_qty"], l["_seq"]))
    return candidates[0]


@bp.post("/orders/<order_id>/fulfill")
@require_roles("InventoryManager")
def fulfill_order(order_id):
    order = get_order(order_id)
    data = body()
    if order["fulfillment_status"] != "ALLOCATED":
        err(errors.ERR_ORDER_NOT_ALLOCATED, "order not ALLOCATED")
    if order["payment_status"] not in ("ON_ACCOUNT", "PAID"):
        err(errors.ERR_ORDER_NOT_SETTLED, "order not settled")

    # If the order has a delivery, it must be DELIVERED (priority 8).
    deliveries = [d for d in db.deliveries.values() if d["order_id"] == order_id]
    active = [d for d in deliveries if d["status"] != "CANCELLED"]
    if active and not any(d["status"] == "DELIVERED" for d in active):
        err(errors.ERR_DELIVERY_NOT_COMPLETED, "delivery not DELIVERED")

    _check_occ(order, data)

    for ol in _order_lines(order_id):
        lot = db.inventory_lots.get(ol["allocated_lot_id"])
        if lot is not None:
            lot["reserved_qty"] -= ol["qty"]
            lot["sold_qty"] += ol["qty"]
            recompute_lot(lot)
            touch(lot)
            maybe_deplete(lot)
        ol["status"] = "FULFILLED"
        touch(ol)

    # Loyalty accrual based on net_total and tier observed at fulfill time.
    account = db.accounts[order["account_id"]]
    nursery = db.nurseries[order["nursery_id"]]
    is_gold = account["loyalty_tier"] == "GOLD"
    points = calc.loyalty_accrual(
        order["net_total_cents"], nursery["loyalty_accrual_per_dollar"], is_gold)
    append_event(account, "ACCRUAL", points, "ORDER", order["id"])

    order["_fulfilled_at"] = clock.get()  # for warranty window math
    order["fulfillment_status"] = "FULFILLED"
    touch(order)
    return ok(order_view(order))


@bp.post("/orders/<order_id>/cancel")
@require_roles("SalesClerk")
def cancel_order(order_id):
    order = get_order(order_id)
    data = body()
    if order["fulfillment_status"] == "FULFILLED":
        err(errors.ERR_ORDER_ALREADY_FULFILLED, "order already fulfilled")
    if order["fulfillment_status"] == "CANCELLED":
        # already terminal; nothing in catalogue for re-cancel; treat as already-fulfilled-style guard
        err(errors.ERR_ORDER_ALREADY_FULFILLED, "order already terminal")

    _check_occ(order, data)

    # Release reservations if ALLOCATED (compensating)
    if order["fulfillment_status"] == "ALLOCATED":
        for ol in _order_lines(order_id):
            lot = db.inventory_lots.get(ol["allocated_lot_id"])
            if lot is not None:
                lot["reserved_qty"] -= ol["qty"]
                recompute_lot(lot)
                touch(lot)
            ol["status"] = "RELEASED"
            touch(ol)

    account = db.accounts[order["account_id"]]

    # Reverse on-account charge (compensating)
    if order["payment_status"] == "ON_ACCOUNT":
        account["outstanding_balance_cents"] -= order["net_total_cents"]
        if (account["status"] == "CREDIT_HOLD"
                and account["outstanding_balance_cents"] <= account["credit_limit_cents"]):
            account["status"] = "ACTIVE"
        touch(account)

    # Reverse redemption (compensating)
    if order.get("_redemption_points", 0) > 0:
        append_event(account, "REVERSAL", order["_redemption_points"],
                     "ORDER", order["id"])
        order["_redemption_points"] = 0

    # Cancel a SCHEDULED/DISPATCHED delivery (compensating)
    for d in db.deliveries.values():
        if d["order_id"] == order_id and d["status"] in ("SCHEDULED", "DISPATCHED"):
            d["status"] = "CANCELLED"
            touch(d)

    order["fulfillment_status"] = "CANCELLED"
    touch(order)
    return ok(order_view(order))


# --------------------------------------------------------------------------
# Payment dimension transitions
# --------------------------------------------------------------------------
@bp.post("/orders/<order_id>/charge-account")
@require_roles("SalesClerk")
def charge_account(order_id):
    order = get_order(order_id)
    data = body()
    if order["fulfillment_status"] not in ("CONFIRMED", "ALLOCATED"):
        err(errors.ERR_ORDER_NOT_CONFIRMED, "order not CONFIRMED/ALLOCATED")
    account = db.accounts[order["account_id"]]
    if account["account_type"] != "LANDSCAPER_B2B":
        err(errors.ERR_NOT_B2B_ACCOUNT, "account is not B2B")
    if account["outstanding_balance_cents"] + order["net_total_cents"] > account["credit_limit_cents"]:
        err(errors.ERR_CREDIT_LIMIT_EXCEEDED, "credit limit exceeded")

    _check_occ(order, data)

    order["payment_status"] = "ON_ACCOUNT"
    account["outstanding_balance_cents"] += order["net_total_cents"]
    if account["outstanding_balance_cents"] == account["credit_limit_cents"]:
        account["status"] = "CREDIT_HOLD"
    touch(account)
    touch(order)
    return ok(order_view(order))


@bp.post("/orders/<order_id>/pay")
@require_roles("SalesClerk")
def pay_order(order_id):
    order = get_order(order_id)
    data = body()
    payment = order["payment_status"]
    if payment == "UNPAID":
        if order["fulfillment_status"] not in ("CONFIRMED", "ALLOCATED"):
            err(errors.ERR_ORDER_NOT_CONFIRMED, "order not CONFIRMED/ALLOCATED")
        _check_occ(order, data)
        order["payment_status"] = "PAID"
        touch(order)
        return ok(order_view(order))
    elif payment == "ON_ACCOUNT":
        _check_occ(order, data)
        account = db.accounts[order["account_id"]]
        order["payment_status"] = "PAID"
        account["outstanding_balance_cents"] -= order["net_total_cents"]
        if (account["status"] == "CREDIT_HOLD"
                and account["outstanding_balance_cents"] <= account["credit_limit_cents"]):
            account["status"] = "ACTIVE"
        touch(account)
        touch(order)
        return ok(order_view(order))
    else:
        # already PAID; not a confirmed/allocated payment-eligible state
        err(errors.ERR_ORDER_NOT_CONFIRMED, "order already paid")


# --------------------------------------------------------------------------
# Cross-resource order-line list endpoints
# --------------------------------------------------------------------------
@bp.get("/order-lines")
@require_roles("SalesClerk", "InventoryManager")
def list_order_lines():
    limit, offset = parse_pagination()
    order_id = request.args.get("order_id")
    product_id = request.args.get("product_id")
    allocated_lot_id = request.args.get("allocated_lot_id")
    status = request.args.get("status")
    items = list(db.order_lines.values())
    if order_id is not None:
        items = [ol for ol in items if ol["order_id"] == order_id]
    if product_id is not None:
        items = [ol for ol in items if ol["product_id"] == product_id]
    if allocated_lot_id is not None:
        items = [ol for ol in items if ol["allocated_lot_id"] == allocated_lot_id]
    if status is not None:
        items = [ol for ol in items if ol["status"] == status]
    items.sort(key=lambda ol: ol["_seq"])
    total = len(items)
    page = paginate(items, limit, offset)
    return ok_list([line_view(ol) for ol in page], limit, offset, total)


@bp.get("/order-lines/<line_id>")
@require_roles("SalesClerk", "InventoryManager")
def read_order_line(line_id):
    from lookups import get_order_line
    ol = get_order_line(line_id)
    return ok(line_view(ol))
