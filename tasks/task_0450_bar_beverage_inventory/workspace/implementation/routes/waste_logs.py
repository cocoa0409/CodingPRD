"""Waste log endpoints (PRD §3.8)."""
from flask import Blueprint, request

import serialize
from db import db, stamp_create
from middleware import require_roles
from money import D, round_cents
from response import object_response, array_response
from routes.lookup import get_product
from services.product import adjust_on_hand
from validate import (get_json_body, require, as_enum, as_number, parse_pagination, paginate)

bp = Blueprint("waste_logs", __name__)

WASTE_REASONS = {"SPILL", "BREAKAGE", "EXPIRY", "OVERPOUR", "COMP"}


@bp.route("/waste-logs", methods=["POST"])
@require_roles("BarManager", "InventoryManager")
def create_waste_log():
    body = get_json_body()
    product_id = require(body, "product_id")
    reason = as_enum(require(body, "reason"), "reason", WASTE_REASONS)
    wasted_units = as_number(require(body, "wasted_units"), "wasted_units", gt=0)
    # body FK existence (404)
    product = get_product(product_id)
    # waste_cost_cents = round_half_up(wasted_units * unit_cost_cents)
    waste_cost = round_cents(D(wasted_units) * D(product["unit_cost_cents"]))
    record = {
        "product_id": product_id,
        "reason": reason,
        "wasted_units": wasted_units,
        "waste_cost_cents": waste_cost,
    }
    stamp_create(record)
    db.waste_logs[record["id"]] = record
    # deplete stock, floored at 0, recompute needs_reorder
    adjust_on_hand(product, -D(wasted_units), floor_zero=True)
    return object_response(serialize.waste_log(record), 201)


@bp.route("/waste-logs", methods=["GET"])
@require_roles("BarManager", "InventoryManager")
def list_waste_logs():
    limit, offset = parse_pagination()
    product_id = request.args.get("product_id")
    reason = request.args.get("reason")
    items = list(db.waste_logs.values())
    if product_id is not None:
        items = [w for w in items if w["product_id"] == product_id]
    if reason is not None:
        items = [w for w in items if w["reason"] == reason]
    page, total = paginate(items, limit, offset)
    return array_response([serialize.waste_log(w) for w in page], limit, offset, total)
