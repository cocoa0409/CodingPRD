"""SalesOrder, OrderLine, Allocation: selling to wholesale buyers."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

from db import store, new_record, touch, now
from errors import (
    ApiError,
    ERR_ORDER_NOT_FOUND,
    ERR_ORDER_LINE_NOT_FOUND,
    ERR_ALLOCATION_NOT_FOUND,
    ERR_CUSTOMER_NOT_FOUND,
    ERR_SPECIES_NOT_FOUND,
    ERR_LOT_NOT_FOUND,
    ERR_OWNERSHIP_MISMATCH,
    ERR_INVALID_REQUEST,
    ERR_ORDER_INVALID_STATE,
    ERR_ORDER_EMPTY,
    ERR_QUOTE_NOT_PUBLISHED,
    ERR_CREDIT_LIMIT_EXCEEDED,
    ERR_STALE_VERSION,
    ERR_LOT_INVALID_STATE,
    ERR_LOT_ON_HOLD,
    ERR_SHELF_LIFE_INSUFFICIENT,
    ERR_INSUFFICIENT_LOT_QUANTITY,
    ERR_LINE_OVER_ALLOCATION,
    ERR_SPECIES_MISMATCH,
    ERR_ALLOCATION_INVALID_STATE,
)
from middleware import auth, require
from response import ok, ok_list
from services.calc import ZERO, q2, cents, standing_quote
from services.cascades import (
    order_lines_of,
    recompute_line,
    recompute_exposure,
    fulfill_check,
    regress_order,
    release_allocation,
)
from util import (
    body,
    req_str,
    req_int,
    opt_int,
    req_num,
    req_enum,
    opt_bool,
    req_date,
    apply_filters,
)

bp = Blueprint("orders", __name__)

GRADES = {"GRADE_A", "GRADE_B", "GRADE_C"}
CANCELLABLE_STATES = {"DRAFT", "SUBMITTED", "CONFIRMED"}


def _get_order(rid):
    rec = store.orders.get(rid)
    if rec is None:
        raise ApiError(ERR_ORDER_NOT_FOUND, 404, "SalesOrder id does not exist")
    return rec


def _get_order_line(rid):
    rec = store.order_lines.get(rid)
    if rec is None:
        raise ApiError(ERR_ORDER_LINE_NOT_FOUND, 404, "OrderLine id does not exist")
    return rec


def _get_allocation(rid):
    rec = store.allocations.get(rid)
    if rec is None:
        raise ApiError(ERR_ALLOCATION_NOT_FOUND, 404, "Allocation id does not exist")
    return rec


def _check_customer_owns(role, uid, order):
    if role == "Customer" and order["customer_id"] != uid:
        raise ApiError(
            ERR_OWNERSHIP_MISMATCH, 403,
            "Customer may act only on its own orders",
        )


# ---------------------------------------------------------------------------
# SalesOrder
# ---------------------------------------------------------------------------
@bp.post("/sales-orders")
def create_order():
    uid, role = auth()
    require(role, {"Customer", "OperationsManager"})
    b = body()
    # Ownership (priority 3) precedes shape/existence (priority 4).
    if role == "Customer" and b.get("customer_id") != uid:
        raise ApiError(
            ERR_OWNERSHIP_MISMATCH, 403,
            "Customer may create orders only for its own account",
        )
    customer_id = req_str(b, "customer_id")
    required_delivery_date = req_date(b, "required_delivery_date")
    if customer_id not in store.customers:
        raise ApiError(ERR_CUSTOMER_NOT_FOUND, 404, "Customer id does not exist")
    rec = new_record({
        "customer_id": customer_id,
        "required_delivery_date": required_delivery_date,
        "status": "DRAFT",
        "total_cents": 0,
        "confirmed_at": None,
    })
    store.orders[rec["id"]] = rec
    return ok(rec, 201)


@bp.get("/sales-orders")
def list_orders():
    auth()
    page, total, limit, offset = apply_filters(
        list(store.orders.values()),
        ["customer_id", "status"],
    )
    return ok_list(page, total, limit, offset)


@bp.get("/sales-orders/<rid>")
def get_order(rid):
    auth()
    return ok(_get_order(rid))


@bp.post("/sales-orders/<rid>/submit")
def submit_order(rid):
    uid, role = auth()
    require(role, {"Customer"})
    order = _get_order(rid)
    _check_customer_owns(role, uid, order)
    if order["status"] != "DRAFT":
        raise ApiError(ERR_ORDER_INVALID_STATE, 409, "Order is not in DRAFT")
    if not order_lines_of(order["id"]):
        raise ApiError(ERR_ORDER_EMPTY, 422, "Submit requires at least one OrderLine")
    order["status"] = "SUBMITTED"
    touch(order)
    return ok(order)


@bp.post("/sales-orders/<rid>/confirm")
def confirm_order(rid):
    _, role = auth()
    require(role, {"OperationsManager"})
    order = _get_order(rid)
    if order["status"] != "SUBMITTED":
        raise ApiError(ERR_ORDER_INVALID_STATE, 409, "Order is not in SUBMITTED")
    customer = store.customers[order["customer_id"]]
    lines = sorted(order_lines_of(order["id"]), key=lambda l: (l["created_at"], l["_seq"]))
    # Resolve every line's standing quote and price it before committing any
    # change (quote resolution, then the credit gate — both fiscal).
    priced = []
    for line in lines:
        quote = standing_quote(line["species_id"], line["requested_grade"])
        if quote is None:
            raise ApiError(
                ERR_QUOTE_NOT_PUBLISHED, 422,
                "No PUBLISHED quote resolvable for a line's species and grade",
            )
        unit_price = quote["price_per_kg_cents"]
        line_total = cents(
            line["requested_qty_kg"] * unit_price * (Decimal("1") - customer["discount_pct"])
        )
        priced.append((line, unit_price, line_total))
    total_cents = sum(t for _, _, t in priced)
    if customer["credit_exposure_cents"] + total_cents > customer["credit_limit_cents"]:
        raise ApiError(
            ERR_CREDIT_LIMIT_EXCEEDED, 402,
            "Confirm would push credit exposure beyond credit_limit_cents",
        )
    for line, unit_price, line_total in priced:
        line["unit_price_cents"] = unit_price
        line["line_total_cents"] = line_total
        touch(line)
    order["total_cents"] = total_cents
    order["confirmed_at"] = now()
    order["status"] = "CONFIRMED"
    touch(order)
    recompute_exposure(customer)
    return ok(order)


@bp.post("/sales-orders/<rid>/cancel")
def cancel_order(rid):
    uid, role = auth()
    require(role, {"Customer", "OperationsManager"})
    order = _get_order(rid)
    _check_customer_owns(role, uid, order)
    if order["status"] not in CANCELLABLE_STATES:
        raise ApiError(
            ERR_ORDER_INVALID_STATE, 409,
            "Order cannot be cancelled from %s" % order["status"],
        )
    if order["status"] == "CONFIRMED":
        # Release every RESERVED/COMMITTED allocation back to available.
        affected = []
        for line in order_lines_of(order["id"]):
            for alloc in store.allocations.values():
                if alloc["order_line_id"] == line["id"] and alloc["status"] in ("RESERVED", "COMMITTED"):
                    lot = store.lots[alloc["inventory_lot_id"]]
                    line_id = release_allocation(alloc, lot, "available")
                    if line_id:
                        affected.append(line_id)
                    touch(lot)
        for line_id in dict.fromkeys(affected):
            recompute_line(store.order_lines[line_id])
        customer = store.customers[order["customer_id"]]
        order["status"] = "CANCELLED"
        touch(order)
        recompute_exposure(customer)
    else:
        order["status"] = "CANCELLED"
        touch(order)
        customer = store.customers[order["customer_id"]]
        recompute_exposure(customer)
    return ok(order)


@bp.post("/sales-orders/<rid>/invoice")
def invoice_order(rid):
    _, role = auth()
    require(role, {"OperationsManager"})
    order = _get_order(rid)
    if order["status"] != "FULFILLED":
        raise ApiError(ERR_ORDER_INVALID_STATE, 409, "Order is not in FULFILLED")
    order["status"] = "INVOICED"
    touch(order)
    return ok(order)


# ---------------------------------------------------------------------------
# OrderLine
# ---------------------------------------------------------------------------
@bp.post("/order-lines")
def create_order_line():
    uid, role = auth()
    require(role, {"Customer", "OperationsManager"})
    b = body()
    # Ownership (priority 3): a Customer acts only on its own orders. If the
    # order does not exist there is nothing to own; existence check (404)
    # applies below.
    if role == "Customer":
        order_for_ownership = store.orders.get(b.get("sales_order_id") or "")
        if order_for_ownership is not None:
            _check_customer_owns(role, uid, order_for_ownership)
    sales_order_id = req_str(b, "sales_order_id")
    species_id = req_str(b, "species_id")
    requested_grade = req_enum(b, "requested_grade", GRADES)
    requested_qty_kg = req_num(b, "requested_qty_kg")
    if requested_qty_kg <= ZERO:
        raise ApiError(ERR_INVALID_REQUEST, 400, "requested_qty_kg must be > 0")
    min_remaining = opt_int(b, "min_remaining_shelf_life_hours", 0)
    if min_remaining < 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, "min_remaining_shelf_life_hours must be >= 0")
    allow_substitution = opt_bool(b, "allow_substitution", False)
    # Body FK resolution order: species_id before sales_order_id.
    if species_id not in store.species:
        raise ApiError(ERR_SPECIES_NOT_FOUND, 404, "Species id does not exist")
    order = store.orders.get(sales_order_id)
    if order is None:
        raise ApiError(ERR_ORDER_NOT_FOUND, 404, "SalesOrder id does not exist")
    if order["status"] != "DRAFT":
        raise ApiError(ERR_ORDER_INVALID_STATE, 409, "Order is not in DRAFT")
    rec = new_record({
        "sales_order_id": sales_order_id,
        "species_id": species_id,
        "requested_grade": requested_grade,
        "requested_qty_kg": q2(requested_qty_kg),
        "min_remaining_shelf_life_hours": min_remaining,
        "allow_substitution": allow_substitution,
        "unit_price_cents": 0,
        "line_total_cents": 0,
        "allocated_qty_kg": ZERO,
        "committed_qty_kg": ZERO,
    })
    store.order_lines[rec["id"]] = rec
    return ok(rec, 201)


@bp.get("/order-lines")
def list_order_lines():
    auth()
    page, total, limit, offset = apply_filters(
        list(store.order_lines.values()),
        ["sales_order_id", "species_id"],
    )
    return ok_list(page, total, limit, offset)


@bp.get("/order-lines/<rid>")
def get_order_line(rid):
    auth()
    return ok(_get_order_line(rid))


# ---------------------------------------------------------------------------
# Allocation
# ---------------------------------------------------------------------------
@bp.post("/allocations")
def create_allocation():
    _, role = auth()
    require(role, {"InventoryPlanner"})
    b = body()
    order_line_id = req_str(b, "order_line_id")
    inventory_lot_id = req_str(b, "inventory_lot_id")
    qty_kg = req_num(b, "qty_kg")
    if qty_kg <= ZERO:
        raise ApiError(ERR_INVALID_REQUEST, 400, "qty_kg must be > 0")
    transit_hours = req_int(b, "transit_hours")
    if transit_hours < 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, "transit_hours must be >= 0")
    expected_sales_order_version = req_int(b, "expected_sales_order_version")
    # Body FK resolution order: order_line_id before inventory_lot_id.
    line = store.order_lines.get(order_line_id)
    if line is None:
        raise ApiError(ERR_ORDER_LINE_NOT_FOUND, 404, "OrderLine id does not exist")
    lot = store.lots.get(inventory_lot_id)
    if lot is None:
        raise ApiError(ERR_LOT_NOT_FOUND, 404, "InventoryLot id does not exist")
    order = store.orders[line["sales_order_id"]]
    # OCC (priority 5) precedes state checks (priority 6).
    if expected_sales_order_version != order["version"]:
        raise ApiError(ERR_STALE_VERSION, 412, "expected_sales_order_version is stale")
    # State: lot lifecycle ACTIVE; order CONFIRMED.
    if lot["lifecycle_status"] != "ACTIVE":
        raise ApiError(ERR_LOT_INVALID_STATE, 409, "Lot lifecycle is not ACTIVE")
    if order["status"] != "CONFIRMED":
        raise ApiError(ERR_ORDER_INVALID_STATE, 409, "Order is not in CONFIRMED")
    # Safety: quarantined lots cannot be allocated.
    if lot["hold_status"] == "ON_HOLD":
        raise ApiError(ERR_LOT_ON_HOLD, 409, "Lot is ON_HOLD")
    qty = q2(qty_kg)
    # Temporal: shelf-life gate — remaining hours must be at least the line
    # floor plus transit; exact equality passes.
    remaining = lot["expires_at"] - now()
    required = timedelta(hours=line["min_remaining_shelf_life_hours"] + transit_hours)
    if remaining < required:
        raise ApiError(
            ERR_SHELF_LIFE_INSUFFICIENT, 422,
            "Lot remaining shelf life is below the requirement plus transit",
        )
    # Constraints (in the PRD 2.8 item-9 listing order): lot quantity, line
    # over-allocation, species match.
    if lot["available_weight_kg"] < qty:
        raise ApiError(
            ERR_INSUFFICIENT_LOT_QUANTITY, 409,
            "qty_kg exceeds lot available_weight_kg",
        )
    if line["requested_qty_kg"] - line["allocated_qty_kg"] < qty:
        raise ApiError(
            ERR_LINE_OVER_ALLOCATION, 409,
            "qty_kg exceeds the line's remaining quantity",
        )
    if lot["species_id"] != line["species_id"]:
        raise ApiError(
            ERR_SPECIES_MISMATCH, 422,
            "Allocation lot species does not equal order line species",
        )
    rec = new_record({
        "order_line_id": order_line_id,
        "inventory_lot_id": inventory_lot_id,
        "qty_kg": qty,
        "transit_hours": transit_hours,
        "status": "RESERVED",
    })
    store.allocations[rec["id"]] = rec
    lot["available_weight_kg"] -= qty
    lot["reserved_weight_kg"] += qty
    touch(lot)
    recompute_line(line)
    touch(order)
    return ok(rec, 201)


@bp.post("/allocations/<rid>/commit")
def commit_allocation(rid):
    _, role = auth()
    require(role, {"InventoryPlanner"})
    alloc = _get_allocation(rid)
    if alloc["status"] != "RESERVED":
        raise ApiError(ERR_ALLOCATION_INVALID_STATE, 409, "Allocation is not in RESERVED")
    lot = store.lots[alloc["inventory_lot_id"]]
    if lot["lifecycle_status"] != "ACTIVE":
        raise ApiError(ERR_LOT_INVALID_STATE, 409, "Lot lifecycle is not ACTIVE")
    line = store.order_lines[alloc["order_line_id"]]
    order = store.orders[line["sales_order_id"]]
    if order["status"] != "CONFIRMED":
        raise ApiError(ERR_ORDER_INVALID_STATE, 409, "Order is not in CONFIRMED")
    if lot["hold_status"] == "ON_HOLD":
        raise ApiError(ERR_LOT_ON_HOLD, 409, "Lot is ON_HOLD")
    lot["reserved_weight_kg"] -= alloc["qty_kg"]
    lot["committed_weight_kg"] += alloc["qty_kg"]
    touch(lot)
    alloc["status"] = "COMMITTED"
    touch(alloc)
    recompute_line(line)
    fulfill_check(order)
    return ok(alloc)


@bp.post("/allocations/<rid>/release")
def release_allocation_endpoint(rid):
    _, role = auth()
    require(role, {"InventoryPlanner"})
    alloc = _get_allocation(rid)
    # Direct release is RESERVED-only; COMMITTED releases happen via cascades.
    if alloc["status"] != "RESERVED":
        raise ApiError(ERR_ALLOCATION_INVALID_STATE, 409, "Allocation is not in RESERVED")
    lot = store.lots[alloc["inventory_lot_id"]]
    release_allocation(alloc, lot, "available")
    touch(lot)
    recompute_line(store.order_lines[alloc["order_line_id"]])
    return ok(alloc)


@bp.get("/allocations")
def list_allocations():
    auth()
    page, total, limit, offset = apply_filters(
        list(store.allocations.values()),
        ["order_line_id", "inventory_lot_id", "status"],
    )
    return ok_list(page, total, limit, offset)


@bp.get("/allocations/<rid>")
def get_allocation(rid):
    auth()
    return ok(_get_allocation(rid))
