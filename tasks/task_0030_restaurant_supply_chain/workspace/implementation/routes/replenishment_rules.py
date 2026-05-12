"""Replenishment rules — including manual replenish action."""

import math
from datetime import timedelta

from flask import Blueprint, g, request

import clock
import db
import errors
import helpers
import response
import serializers
from middleware import auth_required
from services import audit


bp = Blueprint("replenishment_rules", __name__, url_prefix="/supply-chain/replenishment-rules")


MIN_REPLENISHMENT_UNITS = 1


def _ensure_owner(rule):
    if g.user_role == "StoreManager" and rule["store_id"] != g.user_id:
        errors.raise_error(errors.ERR_FORBIDDEN, "StoreManager may only act on their own rules.")


def _on_hand_for(store_id, recipe_id):
    return sum(b["quantity_on_hand"] for b in db.inventory_batches.values()
               if b["store_id"] == store_id and b["recipe_id"] == recipe_id and b["status"] == "ON_HAND")


def _store_has_active_rule_for(store_id, recipe_id):
    for r in db.replenishment_rules.values():
        if r["store_id"] == store_id and r["recipe_id"] == recipe_id and r["status"] == "ACTIVE":
            return True
    return False


@bp.route("", methods=["POST"])
@auth_required("StoreManager")
def create_rule():
    body = helpers.get_json_body()
    for f in ["recipe_id", "safety_stock_units", "replenish_to_units", "cycle_hours"]:
        if f not in body:
            errors.raise_error(errors.ERR_QUANTITY_OUT_OF_RANGE, f"Missing field: {f}")

    recipe_id = body["recipe_id"]
    if recipe_id not in db.recipes:
        errors.raise_error(errors.ERR_REFERENCE_NOT_FOUND, "Recipe not found.")
    safety = body["safety_stock_units"]
    target = body["replenish_to_units"]
    cycle = body["cycle_hours"]
    if not isinstance(safety, int) or safety < 0:
        errors.raise_error(errors.ERR_QUANTITY_OUT_OF_RANGE, "safety_stock_units must be >= 0.")
    if not isinstance(target, int) or target <= safety:
        errors.raise_error(errors.ERR_QUANTITY_OUT_OF_RANGE,
                           "replenish_to_units must be > safety_stock_units.")
    if not isinstance(cycle, int) or cycle <= 0:
        errors.raise_error(errors.ERR_QUANTITY_OUT_OF_RANGE, "cycle_hours must be > 0.")

    rid = db.new_id()
    common = helpers.common_create()
    rule = {
        "id": rid,
        "store_id": g.user_id,
        "recipe_id": recipe_id,
        "safety_stock_units": safety,
        "replenish_to_units": target,
        "cycle_hours": cycle,
        "velocity_multiplier": 1.0,
        "last_evaluated_at": None,
        "status": "ACTIVE",
        **common,
    }
    db.replenishment_rules[rid] = rule
    audit.append(target_type="ReplenishmentRule", target_id=rid, action="CREATE_RULE",
                 payload={"recipe_id": recipe_id, "store_id": g.user_id})
    return response.created(serializers.replenishment_rule_dict(rule))


@bp.route("", methods=["GET"])
@auth_required("StoreManager", "CentralKitchenPlanner")
def list_rules():
    limit, offset = helpers.parse_pagination()
    items = list(db.replenishment_rules.values())
    store_id = request.args.get("store_id")
    status_filter = request.args.get("status")
    if g.user_role == "StoreManager":
        items = [r for r in items if r["store_id"] == g.user_id]
    if store_id:
        items = [r for r in items if r["store_id"] == store_id]
    if status_filter:
        items = [r for r in items if r["status"] == status_filter]
    items.sort(key=lambda r: r["created_at"])
    page, total = helpers.paginate(items, limit, offset)
    return response.list_ok([serializers.replenishment_rule_dict(r) for r in page],
                            limit=limit, offset=offset, total_count=total)


@bp.route("/<rid>/suspend", methods=["POST"])
@auth_required("StoreManager")
def suspend(rid):
    rule = db.replenishment_rules.get(rid)
    if rule is None:
        errors.raise_error(errors.ERR_NOT_FOUND, f"ReplenishmentRule {rid} not found.")
    _ensure_owner(rule)
    body = helpers.get_json_body()
    if rule["status"] != "ACTIVE":
        errors.raise_error(errors.ERR_INVALID_STATE, "Only ACTIVE rules may be suspended.")
    helpers.check_occ(rule, body.get("version"))
    rule["status"] = "SUSPENDED"
    helpers.bump(rule)
    audit.append(target_type="ReplenishmentRule", target_id=rid, action="SUSPEND_RULE", payload={})
    return response.ok(serializers.replenishment_rule_dict(rule))


@bp.route("/<rid>/activate", methods=["POST"])
@auth_required("StoreManager")
def activate(rid):
    rule = db.replenishment_rules.get(rid)
    if rule is None:
        errors.raise_error(errors.ERR_NOT_FOUND, f"ReplenishmentRule {rid} not found.")
    _ensure_owner(rule)
    body = helpers.get_json_body()
    if rule["status"] != "SUSPENDED":
        errors.raise_error(errors.ERR_INVALID_STATE, "Only SUSPENDED rules may be activated.")
    helpers.check_occ(rule, body.get("version"))
    rule["status"] = "ACTIVE"
    helpers.bump(rule)
    audit.append(target_type="ReplenishmentRule", target_id=rid, action="ACTIVATE_RULE", payload={})
    return response.ok(serializers.replenishment_rule_dict(rule))


def _generate_replenishment_order(rule, *, force_within_window=False):
    """Generate a DRAFT (auto-submitted if low-amount) StoreOrder from a rule.

    Returns the StoreOrder dict. Updates rule.last_evaluated_at."""
    store = db.stores[rule["store_id"]]
    recipe = db.recipes[rule["recipe_id"]]

    # Velocity-adjusted target (ceil) and shortfall.
    on_hand = _on_hand_for(rule["store_id"], rule["recipe_id"])
    velocity_adj = math.ceil(rule["replenish_to_units"] * rule["velocity_multiplier"])
    shortfall = max(MIN_REPLENISHMENT_UNITS, velocity_adj - on_hand)

    # Build the DRAFT order with one line.
    today = clock.now().date()
    target_date = today.isoformat()  # default to "today" if not specified

    oid = db.new_id()
    common = helpers.common_create()
    order = {
        "id": oid,
        "store_id": store["id"],
        "target_delivery_date": target_date,
        "submitted_at": None,
        "cancelled_at": None,
        "total_units": 0,
        "total_value_cents": 0,
        "consolidation_batch_id": None,
        "status": "DRAFT",
        **common,
    }
    db.store_orders[oid] = order

    line_id = db.new_id()
    line = {
        "id": line_id,
        "store_order_id": oid,
        "recipe_id": recipe["id"],
        "quantity": shortfall,
        "line_value_cents": 0,
        "created_at": clock.now(),
    }
    db.order_lines[line_id] = line

    audit.append(target_type="StoreOrder", target_id=oid, action="REPLENISHMENT_GENERATE",
                 payload={"recipe_id": recipe["id"], "shortfall_units": shortfall,
                          "rule_id": rule["id"]})

    # Auto-submit if below low_amount_bypass_cents.
    line_value_cents = shortfall * recipe["unit_price_cents"]
    if line_value_cents < store["low_amount_bypass_cents"]:
        line["line_value_cents"] = line_value_cents
        order["status"] = "SUBMITTED"
        order["submitted_at"] = clock.now()
        order["total_units"] = shortfall
        order["total_value_cents"] = line_value_cents
        helpers.bump(order)
        audit.append(target_type="StoreOrder", target_id=oid, action="SUBMIT_ORDER",
                     payload={"auto_bypass": True,
                              "total_value_cents": line_value_cents,
                              "total_units": shortfall},
                     external_systems=["POS", "ERP"])

    rule["last_evaluated_at"] = clock.now()
    helpers.bump(rule)
    return order


@bp.route("/<rid>/manual-replenish", methods=["POST"])
@auth_required("StoreManager")
def manual_replenish(rid):
    rule = db.replenishment_rules.get(rid)
    if rule is None:
        errors.raise_error(errors.ERR_NOT_FOUND, f"ReplenishmentRule {rid} not found.")
    _ensure_owner(rule)
    if rule["status"] != "ACTIVE":
        errors.raise_error(errors.ERR_INVALID_STATE, "Rule is not ACTIVE.")

    last = rule["last_evaluated_at"]
    if last is not None:
        elapsed_hours = (clock.now() - last).total_seconds() / 3600.0
        if elapsed_hours < rule["cycle_hours"]:
            errors.raise_error(errors.ERR_REPLENISHMENT_CYCLE_NOT_ELAPSED,
                               "Replenishment cycle has not elapsed.")

    # Duplicate check: any existing replenishment StoreOrder for (store, recipe)
    # since cycle bucket boundary?
    if last is not None:
        bucket_size = timedelta(hours=rule["cycle_hours"])
        bucket_start = last
        for o in db.store_orders.values():
            if o["store_id"] != rule["store_id"]:
                continue
            if o["created_at"] < bucket_start:
                continue
            for ln in db.order_lines.values():
                if ln["store_order_id"] == o["id"] and ln["recipe_id"] == rule["recipe_id"]:
                    if o["created_at"] >= bucket_start and o["created_at"] < bucket_start + bucket_size:
                        errors.raise_error(errors.ERR_REPLENISHMENT_DUPLICATE,
                                           "A replenishment order already exists for this cycle window.")

    order = _generate_replenishment_order(rule)
    return response.created(serializers.store_order_dict(order))
