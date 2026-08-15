"""Routes: supply items, inventory transactions, valuation, reorder suggestion,
restock orders, supply budgets."""
from decimal import Decimal, ROUND_HALF_UP
from fractions import Fraction

import db
from domain import (
    SUPPLY_CATEGORIES, SUPPLY_UNITS, TXN_TYPES, VALUATION_POLICIES,
    body_json, get_path_resource, iso_z, new_resource, now_dt, now_iso_ms,
    opt_bool, opt_int, opt_string, parse_dt, req_enum, req_field, req_int,
    req_string, ser_budget, ser_inventory_txn, ser_restock_order,
    ser_supply_item, set_props,
)
from errors import ApiError
from middleware import require_roles
from response import success_object
from flask import Blueprint, request

from routes.core import list_response, query_filter

bp = Blueprint("supplies", __name__)

SUPPLY_READ_ROLES = ["SystemAdmin", "AthleticTrainer", "AthleticDirector", "SchoolNurse", "Physician", "TeamCoach"]
SUPPLY_MGMT_ROLES = ["SystemAdmin", "AthleticTrainer", "AthleticDirector"]


def stock_status_for(stock, threshold):
    if stock == 0:
        return "OUT_OF_STOCK"
    if stock <= threshold:
        return "LOW_STOCK"
    return "IN_STOCK"


def recompute_stock(item):
    total = 0
    for t in db.inventory_txns.values():
        if t["supply_item_id"] == item["id"]:
            if t["txn_type"] in ("RESTOCK", "ADJUSTMENT"):
                total += t["quantity"]
            else:
                total -= t["quantity"]
    status = stock_status_for(total, item["reorder_threshold"])
    if item["current_stock"] != total or item["stock_status"] != status:
        set_props(item, current_stock=total, stock_status=status)


def recompute_budget(budget):
    realized = 0
    committed = 0
    for o in db.restock_orders.values():
        if o["fiscal_year"] != budget["fiscal_year"]:
            continue
        if o["status"] == "RECEIVED":
            realized += o["extended_cost_cents"]
        elif o["status"] == "APPROVED":
            committed += o["extended_cost_cents"]
    available = budget["total_budget_cents"] - realized - committed
    if (
        budget["realized_spend_cents"] != realized
        or budget["committed_spend_cents"] != committed
        or budget["available_cents"] != available
    ):
        set_props(
            budget,
            realized_spend_cents=realized,
            committed_spend_cents=committed,
            available_cents=available,
        )


def budget_for_year(year):
    for b in db.budgets.values():
        if b["fiscal_year"] == year:
            return b
    return None


# --------------------------------------------------------------------------
# Supply items
# --------------------------------------------------------------------------
@bp.post("/supply-items")
@require_roles("SystemAdmin")
def create_supply_item(ctx):
    body = body_json()
    item_name = req_string(body, "item_name")
    category = req_enum(body, "category", SUPPLY_CATEGORIES)
    unit = req_enum(body, "unit", SUPPLY_UNITS)
    par_level = req_int(body, "par_level")
    if par_level < 1:
        raise ApiError("ERR_INVALID_REQUEST", "Field 'par_level' must be >= 1.")
    reorder_threshold = req_int(body, "reorder_threshold")
    unit_cost_cents = req_int(body, "unit_cost_cents")
    if unit_cost_cents <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "Field 'unit_cost_cents' must be positive.")
    is_discontinued = opt_bool(body, "is_discontinued", False)

    if reorder_threshold < 0 or reorder_threshold >= par_level:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "Field 'reorder_threshold' must be >= 0 and strictly below par_level.",
        )

    rec = new_resource(
        {
            "item_name": item_name,
            "category": category,
            "unit": unit,
            "par_level": par_level,
            "reorder_threshold": reorder_threshold,
            "unit_cost_cents": unit_cost_cents,
            "is_discontinued": is_discontinued,
            "current_stock": 0,
            "stock_status": "OUT_OF_STOCK",
        }
    )
    db.supply_items[rec["id"]] = rec
    return success_object(ser_supply_item(rec), 201)


@bp.get("/supply-items")
@require_roles(*SUPPLY_READ_ROLES)
def list_supply_items(ctx):
    filters = []
    for field in ("category", "stock_status"):
        f = query_filter(field)
        if f:
            filters.append(f)
    return list_response(list(db.supply_items.values()), ser_supply_item, filters)


@bp.get("/supply-items/<itemId>")
@require_roles(*SUPPLY_READ_ROLES)
def get_supply_item(ctx, itemId):
    rec = get_path_resource(
        db.supply_items, itemId, "ERR_SUPPLY_ITEM_NOT_FOUND", "Supply item id does not exist.")
    return success_object(ser_supply_item(rec))


@bp.patch("/supply-items/<itemId>")
@require_roles("SystemAdmin")
def patch_supply_item(ctx, itemId):
    rec = get_path_resource(
        db.supply_items, itemId, "ERR_SUPPLY_ITEM_NOT_FOUND", "Supply item id does not exist.")
    body = body_json()
    new_par = rec["par_level"]
    new_threshold = rec["reorder_threshold"]
    new_cost = rec["unit_cost_cents"]
    new_disc = rec["is_discontinued"]
    if "par_level" in body:
        new_par = req_int(body, "par_level")
        if new_par < 1:
            raise ApiError("ERR_INVALID_REQUEST", "Field 'par_level' must be >= 1.")
    if "reorder_threshold" in body:
        new_threshold = req_int(body, "reorder_threshold")
    if "unit_cost_cents" in body:
        new_cost = req_int(body, "unit_cost_cents")
        if new_cost <= 0:
            raise ApiError("ERR_INVALID_REQUEST", "Field 'unit_cost_cents' must be positive.")
    if "is_discontinued" in body:
        new_disc = req_field(body, "is_discontinued")
        if not isinstance(new_disc, bool):
            raise ApiError("ERR_INVALID_REQUEST", "Field 'is_discontinued' must be a boolean.")
    if new_threshold < 0 or new_threshold >= new_par:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "Field 'reorder_threshold' must be >= 0 and strictly below par_level.",
        )
    set_props(
        rec,
        par_level=new_par,
        reorder_threshold=new_threshold,
        unit_cost_cents=new_cost,
        is_discontinued=new_disc,
        stock_status=stock_status_for(rec["current_stock"], new_threshold),
    )
    return success_object(ser_supply_item(rec))


# --------------------------------------------------------------------------
# Inventory transactions
# --------------------------------------------------------------------------
@bp.post("/inventory-transactions")
@require_roles("AthleticTrainer", "SystemAdmin")
def create_inventory_txn(ctx):
    body = body_json()
    supply_item_id = req_string(body, "supply_item_id")
    txn_type = req_enum(body, "txn_type", TXN_TYPES)
    occurred_at = parse_dt(req_field(body, "occurred_at"), "occurred_at")
    event_id = opt_string(body, "event_id")
    reason = opt_string(body, "reason")

    if "quantity" not in body or body["quantity"] is None:
        raise ApiError("ERR_INVALID_REQUEST", "Missing required field 'quantity'.")
    quantity = body["quantity"]
    if not isinstance(quantity, int) or isinstance(quantity, bool):
        raise ApiError("ERR_INVALID_REQUEST", "Field 'quantity' must be an integer.")
    if quantity <= 0:
        raise ApiError("ERR_QUANTITY_NONPOSITIVE", "quantity must be strictly positive.")

    unit_cost_cents = body.get("unit_cost_cents")
    if txn_type == "RESTOCK":
        if unit_cost_cents is None:
            raise ApiError("ERR_INVALID_REQUEST", "unit_cost_cents is required on a RESTOCK.")
        if not isinstance(unit_cost_cents, int) or isinstance(unit_cost_cents, bool) or unit_cost_cents <= 0:
            raise ApiError("ERR_INVALID_REQUEST", "unit_cost_cents must be a positive integer.")
    if txn_type in ("ADJUSTMENT", "WASTE") and reason is None:
        raise ApiError("ERR_INVALID_REQUEST", "reason is mandatory for ADJUSTMENT and WASTE entries.")

    item = db.supply_items.get(supply_item_id)
    if item is None:
        raise ApiError("ERR_SUPPLY_ITEM_NOT_FOUND", "Supply item id does not exist.")
    if event_id is not None and event_id not in db.events:
        raise ApiError("ERR_EVENT_NOT_FOUND", "Event id does not exist.")
    if occurred_at > now_dt():
        raise ApiError("ERR_INVALID_DATE_RANGE", "occurred_at may not lie in the future.")

    if txn_type in ("USAGE", "WASTE") and item["current_stock"] - quantity < 0:
        raise ApiError("ERR_INSUFFICIENT_STOCK", "The entry would drive current_stock below zero.")

    rec = new_resource(
        {
            "supply_item_id": supply_item_id,
            "txn_type": txn_type,
            "quantity": quantity,
            "unit_cost_cents": unit_cost_cents if txn_type == "RESTOCK" else None,
            "occurred_at": iso_z(occurred_at),
            "event_id": event_id,
            "restock_order_id": None,
            "reason": reason,
            "recorded_by_staff_id": ctx["uid"],
        },
        common=False,
    )
    db.inventory_txns[rec["id"]] = rec
    recompute_stock(item)
    return success_object(ser_inventory_txn(rec), 201)


@bp.get("/inventory-transactions")
@require_roles(*SUPPLY_MGMT_ROLES)
def list_inventory_txns(ctx):
    filters = []
    for field in ("supply_item_id", "recorded_by_staff_id", "restock_order_id", "event_id", "txn_type"):
        f = query_filter(field)
        if f:
            filters.append(f)
    return list_response(list(db.inventory_txns.values()), ser_inventory_txn, filters)


@bp.get("/inventory-transactions/<txnId>")
@require_roles(*SUPPLY_MGMT_ROLES)
def get_inventory_txn(ctx, txnId):
    rec = get_path_resource(
        db.inventory_txns, txnId, "ERR_NOT_FOUND", "Inventory transaction id does not exist.")
    return success_object(ser_inventory_txn(rec))


# --------------------------------------------------------------------------
# Valuation + reorder suggestion
# --------------------------------------------------------------------------
def _ledger_chronological(item_id):
    rows = [t for t in db.inventory_txns.values() if t["supply_item_id"] == item_id]
    rows.sort(key=lambda t: (parse_dt(t["occurred_at"], "occurred_at"), t["created_at"], t["_seq"]))
    return rows


def valuation_fifo(rows):
    layers = []  # [qty, unit_cost_cents]
    last_cost = 0
    for t in rows:
        if t["txn_type"] == "RESTOCK":
            last_cost = t["unit_cost_cents"]
            layers.append([t["quantity"], t["unit_cost_cents"]])
        elif t["txn_type"] == "ADJUSTMENT":
            layers.append([t["quantity"], last_cost])
        else:
            remaining = t["quantity"]
            while remaining > 0 and layers:
                take = min(layers[0][0], remaining)
                layers[0][0] -= take
                remaining -= take
                if layers[0][0] == 0:
                    layers.pop(0)
    qty = sum(layer[0] for layer in layers)
    value = sum(layer[0] * layer[1] for layer in layers)
    return qty, value


def _round_half_up_decimal(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def valuation_wac_running(rows):
    running_qty = 0
    running_value = 0  # integer cents
    unit_cost = 0
    for t in rows:
        if t["txn_type"] in ("RESTOCK", "ADJUSTMENT"):
            cost = t["unit_cost_cents"] if t["txn_type"] == "RESTOCK" else unit_cost
            running_value += t["quantity"] * cost
            running_qty += t["quantity"]
        else:
            running_value -= t["quantity"] * unit_cost
            running_qty -= t["quantity"]
        if running_qty > 0:
            unit_cost = _round_half_up_decimal(Decimal(running_value) / Decimal(running_qty))
        else:
            running_value = 0
            unit_cost = 0
    return max(running_qty, 0), running_value


def valuation_wac_exact(rows):
    running_qty = 0
    running_value = Fraction(0, 1)
    unit_cost = Fraction(0, 1)
    for t in rows:
        if t["txn_type"] in ("RESTOCK", "ADJUSTMENT"):
            cost = Fraction(t["unit_cost_cents"], 1) if t["txn_type"] == "RESTOCK" else unit_cost
            running_value += t["quantity"] * cost
            running_qty += t["quantity"]
        else:
            running_value -= t["quantity"] * unit_cost
            running_qty -= t["quantity"]
        if running_qty > 0:
            unit_cost = running_value / running_qty
        else:
            running_value = Fraction(0, 1)
            unit_cost = Fraction(0, 1)
    value = int(running_value.numerator // running_value.denominator)
    remainder = running_value - value
    if remainder >= Fraction(1, 2):
        value += 1
    return max(running_qty, 0), value


@bp.get("/supply-items/<itemId>/valuation")
@require_roles(*SUPPLY_MGMT_ROLES)
def get_valuation(ctx, itemId):
    rec = get_path_resource(
        db.supply_items, itemId, "ERR_SUPPLY_ITEM_NOT_FOUND", "Supply item id does not exist.")
    policy = request.args.get("policy", "WAC_RUNNING")
    if policy not in VALUATION_POLICIES:
        raise ApiError("ERR_INVALID_REQUEST", "policy must be one of FIFO, WAC_RUNNING, WAC_EXACT.")
    rows = _ledger_chronological(itemId)
    if policy == "FIFO":
        qty, value = valuation_fifo(rows)
    elif policy == "WAC_RUNNING":
        qty, value = valuation_wac_running(rows)
    else:
        qty, value = valuation_wac_exact(rows)
    return success_object(
        {
            "supply_item_id": itemId,
            "policy": policy,
            "quantity_on_hand": qty,
            "valuation_cents": value,
        }
    )


@bp.get("/supply-items/<itemId>/reorder-suggestion")
@require_roles(*SUPPLY_MGMT_ROLES)
def get_reorder_suggestion(ctx, itemId):
    rec = get_path_resource(
        db.supply_items, itemId, "ERR_SUPPLY_ITEM_NOT_FOUND", "Supply item id does not exist.")
    current_stock = rec["current_stock"]
    inbound_qty = sum(
        o["quantity"]
        for o in db.restock_orders.values()
        if o["supply_item_id"] == itemId and o["status"] == "APPROVED"
    )
    deficit_qty = max(0, rec["par_level"] - current_stock - inbound_qty)
    budget = budget_for_year(now_dt().year)
    if budget is None:
        available_cents = 0
    else:
        available_cents = (
            budget["total_budget_cents"]
            - budget["realized_spend_cents"]
            - budget["committed_spend_cents"]
        )
    max_affordable_qty = available_cents // rec["unit_cost_cents"]
    suggested_qty = max(0, min(deficit_qty, max_affordable_qty))
    return success_object(
        {
            "supply_item_id": itemId,
            "current_stock": current_stock,
            "inbound_qty": inbound_qty,
            "deficit_qty": deficit_qty,
            "available_budget_cents": available_cents,
            "max_affordable_qty": max_affordable_qty,
            "suggested_qty": suggested_qty,
        }
    )


# --------------------------------------------------------------------------
# Restock orders
# --------------------------------------------------------------------------
@bp.post("/restock-orders")
@require_roles("AthleticTrainer", "AthleticDirector")
def create_restock_order(ctx):
    body = body_json()
    supply_item_id = req_string(body, "supply_item_id")
    fiscal_year = req_int(body, "fiscal_year")

    if "quantity" not in body or body["quantity"] is None:
        raise ApiError("ERR_INVALID_REQUEST", "Missing required field 'quantity'.")
    quantity = body["quantity"]
    if not isinstance(quantity, int) or isinstance(quantity, bool):
        raise ApiError("ERR_INVALID_REQUEST", "Field 'quantity' must be an integer.")
    if quantity <= 0:
        raise ApiError("ERR_QUANTITY_NONPOSITIVE", "quantity must be strictly positive.")
    unit_cost_cents = req_int(body, "unit_cost_cents")
    if unit_cost_cents <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "Field 'unit_cost_cents' must be positive.")

    item = db.supply_items.get(supply_item_id)
    if item is None:
        raise ApiError("ERR_SUPPLY_ITEM_NOT_FOUND", "Supply item id does not exist.")
    if item["is_discontinued"]:
        raise ApiError("ERR_ITEM_DISCONTINUED", "Discontinued items reject new restock orders.")

    rec = new_resource(
        {
            "supply_item_id": supply_item_id,
            "quantity": quantity,
            "unit_cost_cents": unit_cost_cents,
            "fiscal_year": fiscal_year,
            "extended_cost_cents": quantity * unit_cost_cents,
            "requested_by_staff_id": ctx["uid"],
            "approved_by_staff_id": None,
            "status": "DRAFT",
        }
    )
    db.restock_orders[rec["id"]] = rec
    return success_object(ser_restock_order(rec), 201)


@bp.get("/restock-orders")
@require_roles(*SUPPLY_MGMT_ROLES)
def list_restock_orders(ctx):
    filters = []
    for field in ("supply_item_id", "requested_by_staff_id", "approved_by_staff_id", "status"):
        f = query_filter(field)
        if f:
            filters.append(f)
    raw_fy = request.args.get("fiscal_year")
    if raw_fy is not None:
        try:
            fy = int(raw_fy)
        except ValueError:
            fy = None
        filters.append(lambda r: r["fiscal_year"] == fy)
    return list_response(list(db.restock_orders.values()), ser_restock_order, filters)


@bp.get("/restock-orders/<orderId>")
@require_roles(*SUPPLY_MGMT_ROLES)
def get_restock_order(ctx, orderId):
    rec = get_path_resource(
        db.restock_orders, orderId, "ERR_RESTOCK_ORDER_NOT_FOUND", "Restock order id does not exist.")
    return success_object(ser_restock_order(rec))


@bp.post("/restock-orders/<orderId>/submit")
@require_roles("AthleticTrainer", "AthleticDirector")
def submit_restock_order(ctx, orderId):
    rec = get_path_resource(
        db.restock_orders, orderId, "ERR_RESTOCK_ORDER_NOT_FOUND", "Restock order id does not exist.")
    if rec["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "Only a DRAFT order can be submitted.")
    set_props(rec, status="SUBMITTED")
    return success_object(ser_restock_order(rec))


@bp.post("/restock-orders/<orderId>/approve")
@require_roles("AthleticDirector")
def approve_restock_order(ctx, orderId):
    rec = get_path_resource(
        db.restock_orders, orderId, "ERR_RESTOCK_ORDER_NOT_FOUND", "Restock order id does not exist.")
    if rec["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", "Only a SUBMITTED order can be approved.")
    if ctx["uid"] == rec["requested_by_staff_id"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "The approver may not be the order's requester.",
        )
    budget = budget_for_year(rec["fiscal_year"])
    if budget is None:
        raise ApiError("ERR_BUDGET_NOT_FOUND", "No SupplyBudget exists for the order's fiscal_year.")
    if budget["available_cents"] < rec["extended_cost_cents"]:
        raise ApiError("ERR_BUDGET_EXCEEDED", "The order exceeds the budget's available funds.")
    set_props(rec, status="APPROVED", approved_by_staff_id=ctx["uid"])
    recompute_budget(budget)
    return success_object(ser_restock_order(rec))


@bp.post("/restock-orders/<orderId>/reject")
@require_roles("AthleticDirector")
def reject_restock_order(ctx, orderId):
    rec = get_path_resource(
        db.restock_orders, orderId, "ERR_RESTOCK_ORDER_NOT_FOUND", "Restock order id does not exist.")
    if rec["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", "Only a SUBMITTED order can be rejected.")
    set_props(rec, status="REJECTED")
    return success_object(ser_restock_order(rec))


@bp.post("/restock-orders/<orderId>/receive")
@require_roles("AthleticTrainer")
def receive_restock_order(ctx, orderId):
    rec = get_path_resource(
        db.restock_orders, orderId, "ERR_RESTOCK_ORDER_NOT_FOUND", "Restock order id does not exist.")
    if rec["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", "Only an APPROVED order can be received.")
    set_props(rec, status="RECEIVED")
    txn = new_resource(
        {
            "supply_item_id": rec["supply_item_id"],
            "txn_type": "RESTOCK",
            "quantity": rec["quantity"],
            "unit_cost_cents": rec["unit_cost_cents"],
            "occurred_at": now_iso_ms(),
            "event_id": None,
            "restock_order_id": rec["id"],
            "reason": None,
            "recorded_by_staff_id": ctx["uid"],
        },
        common=False,
    )
    db.inventory_txns[txn["id"]] = txn
    item = db.supply_items.get(rec["supply_item_id"])
    if item is not None:
        recompute_stock(item)
    budget = budget_for_year(rec["fiscal_year"])
    if budget is not None:
        recompute_budget(budget)
    return success_object(ser_restock_order(rec))


@bp.post("/restock-orders/<orderId>/cancel")
@require_roles("AthleticTrainer")
def cancel_restock_order(ctx, orderId):
    rec = get_path_resource(
        db.restock_orders, orderId, "ERR_RESTOCK_ORDER_NOT_FOUND", "Restock order id does not exist.")
    if rec["status"] not in ("DRAFT", "SUBMITTED", "APPROVED"):
        raise ApiError("ERR_INVALID_STATE", "This order can no longer be cancelled.")
    was_approved = rec["status"] == "APPROVED"
    set_props(rec, status="CANCELLED")
    if was_approved:
        budget = budget_for_year(rec["fiscal_year"])
        if budget is not None:
            recompute_budget(budget)
    return success_object(ser_restock_order(rec))


# --------------------------------------------------------------------------
# Supply budgets
# --------------------------------------------------------------------------
@bp.post("/supply-budgets")
@require_roles("SystemAdmin")
def create_budget(ctx):
    body = body_json()
    fiscal_year = req_int(body, "fiscal_year")
    total_budget_cents = req_int(body, "total_budget_cents")
    if total_budget_cents <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "Field 'total_budget_cents' must be positive.")
    if budget_for_year(fiscal_year) is not None:
        raise ApiError("ERR_DUPLICATE_BUDGET_YEAR", "A SupplyBudget for this fiscal_year already exists.")
    rec = new_resource(
        {
            "fiscal_year": fiscal_year,
            "total_budget_cents": total_budget_cents,
            "realized_spend_cents": 0,
            "committed_spend_cents": 0,
            "available_cents": total_budget_cents,
        }
    )
    db.budgets[rec["id"]] = rec
    return success_object(ser_budget(rec), 201)


@bp.get("/supply-budgets")
@require_roles(*SUPPLY_MGMT_ROLES)
def list_budgets(ctx):
    filters = []
    raw_fy = request.args.get("fiscal_year")
    if raw_fy is not None:
        try:
            fy = int(raw_fy)
        except ValueError:
            fy = None
        filters.append(lambda r: r["fiscal_year"] == fy)
    return list_response(list(db.budgets.values()), ser_budget, filters)


@bp.get("/supply-budgets/<budgetId>")
@require_roles(*SUPPLY_MGMT_ROLES)
def get_budget(ctx, budgetId):
    rec = get_path_resource(
        db.budgets, budgetId, "ERR_BUDGET_NOT_FOUND", "Supply budget id does not exist.")
    return success_object(ser_budget(rec))
