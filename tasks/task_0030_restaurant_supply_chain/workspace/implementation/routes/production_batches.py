"""Production batches: consolidate, schedule, start, complete, fail, forecast."""

import math
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

import clock
import db
import errors
import helpers
import response
import serializers
from middleware import auth_required
from services import audit


bp = Blueprint("production_batches", __name__, url_prefix="/supply-chain/production-batches")


EQUIPMENT_MINUTES_PER_CLASS_PER_DAY = 480
BATCH_SETUP_FEE_CENTS = 100
FORECAST_HORIZON_DAYS = 1


def _round_half_up_int(x):
    return int(Decimal(str(x)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _parse_date(s):
    if not isinstance(s, str):
        errors.raise_error(errors.ERR_QUANTITY_OUT_OF_RANGE, "target_delivery_date must be ISO date string.")
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        errors.raise_error(errors.ERR_QUANTITY_OUT_OF_RANGE, "target_delivery_date must be YYYY-MM-DD.")


def _end_of_day_utc(date_str):
    """Return aware UTC datetime at 23:59:00 on the given ISO date."""
    d = _parse_date(date_str)
    return datetime(d.year, d.month, d.day, 23, 59, 0, tzinfo=timezone.utc)


@bp.route("/consolidate", methods=["POST"])
@auth_required("CentralKitchenPlanner")
def consolidate():
    body = helpers.get_json_body()
    if "target_delivery_date" not in body:
        errors.raise_error(errors.ERR_QUANTITY_OUT_OF_RANGE, "Missing target_delivery_date.")
    tdd = body["target_delivery_date"]
    _parse_date(tdd)

    # Find SUBMITTED orders whose store is ACTIVE and target date matches.
    candidate_orders = []
    for o in db.store_orders.values():
        if o["status"] != "SUBMITTED":
            continue
        if o["target_delivery_date"] != tdd:
            continue
        store = db.stores.get(o["store_id"])
        if store is None or store["status"] != "ACTIVE":
            continue
        candidate_orders.append(o)

    # Group order lines by recipe_id.
    lines_by_recipe = {}
    orders_by_recipe = {}
    for o in candidate_orders:
        for ln in db.order_lines.values():
            if ln["store_order_id"] == o["id"]:
                lines_by_recipe.setdefault(ln["recipe_id"], []).append(ln)
                orders_by_recipe.setdefault(ln["recipe_id"], set()).add(o["id"])

    created_batches = []
    for recipe_id, lines in lines_by_recipe.items():
        recipe = db.recipes[recipe_id]
        planned_units = sum(l["quantity"] for l in lines)

        bid = db.new_id()
        common = helpers.common_create()
        batch = {
            "id": bid,
            "recipe_id": recipe_id,
            "planned_units": planned_units,
            "forecast_units": None,
            "equipment_minutes": planned_units * recipe["production_minutes_per_unit"],
            "scheduled_start_at": None,
            "scheduled_end_at": None,
            "produced_at": None,
            "expires_at": None,
            "target_delivery_date": tdd,
            "status": "PLANNED",
            **common,
        }
        db.production_batches[bid] = batch
        created_batches.append(batch)

        # Transition each contributing StoreOrder SUBMITTED -> CONSOLIDATED.
        for oid in orders_by_recipe[recipe_id]:
            order = db.store_orders[oid]
            if order["status"] == "SUBMITTED":
                order["status"] = "CONSOLIDATED"
                order["consolidation_batch_id"] = bid
                helpers.bump(order)
                audit.append(target_type="StoreOrder", target_id=oid, action="CONSOLIDATE_ORDER",
                             payload={"production_batch_id": bid})

        audit.append(target_type="ProductionBatch", target_id=bid, action="CREATE_BATCH",
                     payload={"recipe_id": recipe_id, "planned_units": planned_units,
                              "target_delivery_date": tdd})

    # Sort returned batches by created_at ascending (default sort).
    created_batches.sort(key=lambda b: b["created_at"])
    return response.created([serializers.production_batch_dict(b) for b in created_batches])


@bp.route("", methods=["GET"])
@auth_required("CentralKitchenPlanner", "FinanceController")
def list_batches():
    limit, offset = helpers.parse_pagination()
    items = list(db.production_batches.values())
    status_filter = request.args.get("status")
    tdd = request.args.get("target_delivery_date")
    if status_filter:
        items = [b for b in items if b["status"] == status_filter]
    if tdd:
        items = [b for b in items if b["target_delivery_date"] == tdd]
    items.sort(key=lambda b: b["created_at"])
    page, total = helpers.paginate(items, limit, offset)
    return response.list_ok([serializers.production_batch_dict(b) for b in page],
                            limit=limit, offset=offset, total_count=total)


@bp.route("/<bid>", methods=["GET"])
@auth_required("CentralKitchenPlanner", "FinanceController")
def read_batch(bid):
    batch = db.production_batches.get(bid)
    if batch is None:
        errors.raise_error(errors.ERR_NOT_FOUND, f"ProductionBatch {bid} not found.")
    return response.ok(serializers.production_batch_dict(batch))


@bp.route("/<bid>/forecast", methods=["GET"])
@auth_required("CentralKitchenPlanner")
def batch_forecast(bid):
    batch = db.production_batches.get(bid)
    if batch is None:
        errors.raise_error(errors.ERR_NOT_FOUND, f"ProductionBatch {bid} not found.")

    recipe = db.recipes[batch["recipe_id"]]
    forecast_units_total = 0
    per_store = []
    for store in db.stores.values():
        if store["status"] != "ACTIVE":
            continue
        rule = None
        for r in db.replenishment_rules.values():
            if r["store_id"] == store["id"] and r["recipe_id"] == recipe["id"] and r["status"] == "ACTIVE":
                rule = r
                break
        if rule is None:
            continue
        unit_price = recipe["unit_price_cents"]
        if unit_price <= 0:
            continue
        # avg_daily_sales_cents / unit_price * horizon * velocity_multiplier, rounded once.
        per_store_value = (
            store["avg_daily_sales_cents"] / unit_price
            * FORECAST_HORIZON_DAYS
            * rule["velocity_multiplier"]
        )
        rounded = _round_half_up_int(per_store_value)
        forecast_units_total += rounded
        per_store.append({"store_id": store["id"], "forecast_units": rounded})

    # Forecast ingredient demand: sum across recipes (here we have one recipe).
    forecast_ingredient_demand = []
    for ri in db.recipe_ingredients.values():
        if ri["recipe_id"] != recipe["id"]:
            continue
        # Quantities tracked in milligrams (integer) internally — but the public field is base unit.
        demand = forecast_units_total * ri["quantity_per_unit"]
        forecast_ingredient_demand.append({
            "ingredient_id": ri["ingredient_id"],
            "demand": demand,
        })
    forecast_ingredient_demand.sort(key=lambda x: x["ingredient_id"])

    payload = {
        "production_batch_id": bid,
        "recipe_id": recipe["id"],
        "forecast_units": forecast_units_total,
        "per_store_forecast": per_store,
        "forecast_ingredient_demand": forecast_ingredient_demand,
    }
    return response.ok(payload)


@bp.route("/<bid>/schedule", methods=["POST"])
@auth_required("CentralKitchenPlanner")
def schedule_batch(bid):
    batch = db.production_batches.get(bid)
    if batch is None:
        errors.raise_error(errors.ERR_NOT_FOUND, f"ProductionBatch {bid} not found.")
    body = helpers.get_json_body()
    if batch["status"] != "PLANNED":
        errors.raise_error(errors.ERR_INVALID_STATE, "Only PLANNED batches may be scheduled.")
    helpers.check_occ(batch, body.get("version"))

    recipe = db.recipes[batch["recipe_id"]]
    eq_min = batch["equipment_minutes"]
    eq_min_int = math.ceil(eq_min)

    # Determine scheduled_start_at.
    eod = _end_of_day_utc(batch["target_delivery_date"])  # 23:59:00 UTC
    shelf_secs = recipe["shelf_life_hours"] * 3600

    # If preferred_start_at is supplied and valid, we may use it; otherwise derive
    # the latest start that still satisfies shelf-life sufficiency.
    preferred = body.get("preferred_start_at")
    if preferred:
        start_at = clock.parse_iso(preferred)
    else:
        # Latest possible start such that start + eq_min + shelf_life >= eod.
        # Using the equality boundary so the constraint is satisfied.
        latest = eod - timedelta(seconds=shelf_secs) - timedelta(minutes=eq_min_int)
        # We schedule at the start of the production day to keep things simple: use
        # the earliest possible reasonable start = today start of day, but if that
        # would violate the sequencing rule we move to the latest allowed start.
        start_at = latest

    # SHELF-LIFE SUFFICIENCY CHECK
    if start_at + timedelta(minutes=eq_min_int) + timedelta(seconds=shelf_secs) < eod:
        errors.raise_error(errors.ERR_SHELF_LIFE_INSUFFICIENT,
                           "Shelf life would not last past target date end-of-day.")

    # EQUIPMENT-CLASS CAPACITY CHECK (per (target_delivery_date, equipment_class))
    key = (batch["target_delivery_date"], recipe["equipment_class"])
    reserved = db.equipment_reservations.get(key, 0)
    if reserved + eq_min_int > EQUIPMENT_MINUTES_PER_CLASS_PER_DAY:
        errors.raise_error(errors.ERR_EQUIPMENT_CAPACITY_EXCEEDED,
                           "Equipment-class capacity exceeded for the chosen day.")
    db.equipment_reservations[key] = reserved + eq_min_int

    end_at = start_at + timedelta(minutes=eq_min_int)
    batch["scheduled_start_at"] = start_at
    batch["scheduled_end_at"] = end_at
    batch["status"] = "SCHEDULED"
    helpers.bump(batch)
    audit.append(target_type="ProductionBatch", target_id=bid, action="SCHEDULE_BATCH",
                 payload={"scheduled_start_at": clock.iso_format(start_at),
                          "scheduled_end_at": clock.iso_format(end_at)},
                 external_systems=["ERP"])
    return response.ok(serializers.production_batch_dict(batch))


@bp.route("/<bid>/start", methods=["POST"])
@auth_required("CentralKitchenPlanner")
def start_batch(bid):
    batch = db.production_batches.get(bid)
    if batch is None:
        errors.raise_error(errors.ERR_NOT_FOUND, f"ProductionBatch {bid} not found.")
    if batch["status"] != "SCHEDULED":
        errors.raise_error(errors.ERR_INVALID_STATE, "Only SCHEDULED batches may be started.")
    if clock.now() < batch["scheduled_start_at"]:
        errors.raise_error(errors.ERR_INVALID_STATE, "now() < scheduled_start_at.")

    batch["status"] = "IN_PRODUCTION"
    helpers.bump(batch)
    audit.append(target_type="ProductionBatch", target_id=bid, action="START_BATCH", payload={})
    return response.ok(serializers.production_batch_dict(batch))


def _provisional_cost_allocation(batch):
    """Compute and apply provisional cost per receiving store (not stored on batch
    explicitly, but exposed via audit log)."""
    recipe = db.recipes[batch["recipe_id"]]

    # Ingredient cost
    ingredient_cost = 0
    for ri in db.recipe_ingredients.values():
        if ri["recipe_id"] != recipe["id"]:
            continue
        ing = db.ingredients[ri["ingredient_id"]]
        ingredient_cost += ri["quantity_per_unit"] * ing["unit_cost_cents"] * batch["planned_units"]
    total_cost_cents_decimal = Decimal(str(ingredient_cost)) + Decimal(BATCH_SETUP_FEE_CENTS)

    # Receiving stores: stores whose orders contributed lines to this batch.
    contributions = {}  # store_id -> units_contributed
    for line in db.order_lines.values():
        order = db.store_orders.get(line["store_order_id"])
        if order is None:
            continue
        if order["consolidation_batch_id"] != batch["id"]:
            continue
        if line["recipe_id"] != batch["recipe_id"]:
            continue
        contributions[order["store_id"]] = contributions.get(order["store_id"], 0) + line["quantity"]

    if not contributions or batch["planned_units"] == 0:
        return {"per_store": [], "total_cost_cents": int(total_cost_cents_decimal)}

    per_store_alloc = {}
    raw_total = Decimal("0")
    for sid, units in contributions.items():
        share = Decimal(units) / Decimal(batch["planned_units"])
        raw = total_cost_cents_decimal * share
        rounded = int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        per_store_alloc[sid] = rounded
        raw_total += raw

    # Distribute remainder to top-share store (tie-break: lowest store_code).
    target_total = int(total_cost_cents_decimal.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    summed = sum(per_store_alloc.values())
    diff = target_total - summed
    if diff != 0:
        # Top-share, with tie on store_code ascending.
        candidates = sorted(
            contributions.items(),
            key=lambda kv: (-kv[1], db.stores[kv[0]]["store_code"]),
        )
        recipient = candidates[0][0]
        per_store_alloc[recipient] += diff

    return {
        "per_store": [{"store_id": sid, "allocated_cost_cents": per_store_alloc[sid]}
                      for sid in sorted(per_store_alloc.keys())],
        "total_cost_cents": target_total,
    }


@bp.route("/<bid>/complete", methods=["POST"])
@auth_required("CentralKitchenPlanner")
def complete_batch(bid):
    batch = db.production_batches.get(bid)
    if batch is None:
        errors.raise_error(errors.ERR_NOT_FOUND, f"ProductionBatch {bid} not found.")
    if batch["status"] != "IN_PRODUCTION":
        errors.raise_error(errors.ERR_INVALID_STATE, "Only IN_PRODUCTION batches may be completed.")

    recipe = db.recipes[batch["recipe_id"]]
    now = clock.now()
    batch["produced_at"] = now
    batch["expires_at"] = now + timedelta(hours=recipe["shelf_life_hours"])
    batch["status"] = "COMPLETED"
    helpers.bump(batch)

    allocation = _provisional_cost_allocation(batch)
    audit.append(target_type="ProductionBatch", target_id=bid, action="COMPLETE_BATCH",
                 payload={
                     "produced_at": clock.iso_format(batch["produced_at"]),
                     "expires_at": clock.iso_format(batch["expires_at"]),
                     "provisional_cost_allocation": allocation,
                 },
                 external_systems=["ERP", "LOGISTICS"])
    return response.ok(serializers.production_batch_dict(batch))


@bp.route("/<bid>/fail", methods=["POST"])
@auth_required("CentralKitchenPlanner")
def fail_batch(bid):
    batch = db.production_batches.get(bid)
    if batch is None:
        errors.raise_error(errors.ERR_NOT_FOUND, f"ProductionBatch {bid} not found.")
    if batch["status"] != "IN_PRODUCTION":
        errors.raise_error(errors.ERR_INVALID_STATE, "Only IN_PRODUCTION batches may be failed.")

    batch["status"] = "FAILED"
    helpers.bump(batch)

    # Revert linked CONSOLIDATED orders -> SUBMITTED, clear consolidation_batch_id.
    for order in db.store_orders.values():
        if order["consolidation_batch_id"] == bid and order["status"] == "CONSOLIDATED":
            order["status"] = "SUBMITTED"
            order["consolidation_batch_id"] = None
            helpers.bump(order)
            audit.append(target_type="StoreOrder", target_id=order["id"], action="REVERT_ORDER",
                         payload={"production_batch_id": bid})

    # Free up equipment-class minutes reservation for the day.
    recipe = db.recipes[batch["recipe_id"]]
    key = (batch["target_delivery_date"], recipe["equipment_class"])
    db.equipment_reservations[key] = max(0, db.equipment_reservations.get(key, 0)
                                         - math.ceil(batch["equipment_minutes"]))

    audit.append(target_type="ProductionBatch", target_id=bid, action="FAIL_BATCH", payload={})
    return response.ok(serializers.production_batch_dict(batch))
