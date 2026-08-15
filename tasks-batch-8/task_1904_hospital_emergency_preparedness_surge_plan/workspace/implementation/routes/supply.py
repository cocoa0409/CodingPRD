"""Supply/PPE cache items and the append-only stock transaction ledger."""

import uuid
from decimal import Decimal

from flask import Blueprint, request

from db import clock, store
from domain import (SUPPLY_CATEGORIES, TRANSACTION_TYPES, get_or_404, list_response,
                    recompute_item, ser_stock_transaction, ser_supply_item)
from envelope import success
from errors import ApiError
from security import ALL_ROLES, authorize
from util import (bool_filter_param, field_dt, field_enum, field_int, field_str,
                  fmt_dt, new_entity, require_body, touch)

bp = Blueprint("supply", __name__)


@bp.post("/supply-items")
@authorize(["LogisticsChief"])
def create_supply_item():
    body = require_body()
    item_name = field_str(body, "item_name", required=True)
    category = field_enum(body, "category", SUPPLY_CATEGORIES, required=True)
    unit = field_str(body, "unit", required=True)
    reorder_min_days = field_int(body, "reorder_min_days", required=True)

    item = new_entity()
    item.update({
        "item_name": item_name,
        "category": category,
        "unit": unit,
        "reorder_min_days": reorder_min_days,
        "quantity_on_hand": 0,
        "observed_daily_burn_rate": Decimal("0"),
        "projected_daily_burn_rate": Decimal("0"),
        "days_of_supply": None,
        "below_reorder_level": False,
    })
    store["supply_items"][item["id"]] = item
    recompute_item(item)
    return success(ser_supply_item(item), "object", 201)


@bp.get("/supply-items")
@authorize(ALL_ROLES)
def list_supply_items():
    category = request.args.get("category")
    below = bool_filter_param("below_reorder_level")

    def predicate(item):
        if category is not None and item["category"] != category:
            return False
        if below is not None:
            recompute_item(item)
            if item["below_reorder_level"] != below:
                return False
        return True

    return list_response("supply_items", ser_supply_item, predicate)


@bp.get("/supply-items/<item_id>")
@authorize(ALL_ROLES)
def get_supply_item(item_id):
    return success(ser_supply_item(get_or_404("supply_items", item_id)), "object", 200)


@bp.post("/stock-transactions")
@authorize(["LogisticsChief"])
def create_stock_transaction():
    body = require_body()
    supply_item_id = field_str(body, "supply_item_id", required=True)
    transaction_type = field_enum(body, "transaction_type", TRANSACTION_TYPES,
                                  required=True)
    quantity = field_int(body, "quantity", required=True, minimum=1)
    occurred_at = field_dt(body, "occurred_at", required=True)
    incident_id = field_str(body, "incident_id")
    note = field_str(body, "note")

    if occurred_at > clock.now():
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "occurred_at must not be after the current clock time")

    item = get_or_404("supply_items", supply_item_id)
    incident = None
    if incident_id is not None:
        incident = get_or_404("incidents", incident_id)

    # Posture gate applies only to incident-linked transactions.
    if incident is not None and incident["status"] != "ACTIVATED":
        raise ApiError("ERR_INCIDENT_NOT_ACTIVATED", 409,
                       "incident-linked stock transactions require an ACTIVATED incident")

    if transaction_type == "ISSUE" and quantity > item["quantity_on_hand"]:
        raise ApiError("ERR_INSUFFICIENT_STOCK", 422,
                       "ISSUE quantity exceeds quantity_on_hand")

    if transaction_type == "RECEIVE":
        item["quantity_on_hand"] += quantity
    elif transaction_type == "ISSUE":
        item["quantity_on_hand"] -= quantity
    elif transaction_type == "RETURN":
        item["quantity_on_hand"] += quantity
    else:  # ADJUST resets to the absolute value
        item["quantity_on_hand"] = quantity

    entry = {
        "id": str(uuid.uuid4()),
        "created_at": clock.now(),
        "supply_item_id": supply_item_id,
        "transaction_type": transaction_type,
        "quantity": quantity,
        "occurred_at": occurred_at,
        "incident_id": incident_id,
        "note": note,
    }
    store["stock_transactions"][entry["id"]] = entry

    touch(item)
    recompute_item(item)
    return success(ser_stock_transaction(entry), "object", 201)


@bp.get("/stock-transactions")
@authorize(ALL_ROLES)
def list_stock_transactions():
    supply_item_id = request.args.get("supply_item_id")
    incident_id = request.args.get("incident_id")
    transaction_type = request.args.get("transaction_type")

    def predicate(t):
        if supply_item_id is not None and t["supply_item_id"] != supply_item_id:
            return False
        if incident_id is not None and t["incident_id"] != incident_id:
            return False
        if transaction_type is not None and t["transaction_type"] != transaction_type:
            return False
        return True

    return list_response("stock_transactions", ser_stock_transaction, predicate)


@bp.get("/stock-transactions/<transaction_id>")
@authorize(ALL_ROLES)
def get_stock_transaction(transaction_id):
    return success(ser_stock_transaction(get_or_404("stock_transactions", transaction_id)),
                   "object", 200)
