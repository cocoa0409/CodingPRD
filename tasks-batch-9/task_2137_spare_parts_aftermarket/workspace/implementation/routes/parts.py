"""Part catalogue, lifecycle transitions, classification, forecasts and the ledger."""
from decimal import Decimal

from flask import Blueprint

import auth
import calc
import domain
import envelope
import serializers
import store
from errors import ApiError
from routes.registry import fk

bp = Blueprint("parts", __name__)

LIFECYCLE_STATES = {"ACTIVE", "PHASE_OUT", "LTB_OPEN", "LTB_CLOSED", "OBSOLETE", "SUPERSEDED"}
CRITICALITY_CLASSES = {"VITAL", "ESSENTIAL", "DESIRABLE"}
FORECAST_METHODS = {"WORK_ORDER_HISTORY", "INSTALLED_BASE_RATE", "BLENDED"}
ENTRY_TYPES = {"RECEIPT", "ISSUE", "RETURN_RECEIPT", "SCRAP"}


# ---------------------------------------------------------------- CRUD -----
@bp.post("/aftermarket/parts")
def create_part():
    auth.require("AftermarketPlanner")
    data = auth.body()
    part_number = auth.req_str(data, "part_number")
    description = auth.req_str(data, "description")
    unit_cost_cents = auth.req_int(data, "unit_cost_cents", minimum=1)
    lead_time_days = auth.req_int(data, "lead_time_days", minimum=0)
    weight_kg = auth.req_number(data, "weight_kg", exclusive_min=0)
    hazmat = auth.req_bool(data, "hazmat", default=False)
    max_stock_units = auth.opt_int(data, "max_stock_units", default=0, minimum=0)
    domain.unique_or_400(store.parts, "part_number", part_number)

    rec = store.new_record("Part", {
        "part_number": part_number,
        "description": description,
        "lifecycle_state": "ACTIVE",
        "superseded_by_part_id": None,
        "unit_cost_cents": unit_cost_cents,
        "lead_time_days": lead_time_days,
        "weight_kg": weight_kg,
        "hazmat": hazmat,
        "max_stock_units": max_stock_units,
        "criticality_score": 0,
        "criticality_class": "DESIRABLE",
        "stocking_policy": "MAKE_TO_ORDER",
        "safety_stock_units": 0,
        "reorder_point_units": 0,
        "on_hand_units": 0,
        "allocated_units": 0,
        "quarantine_units": 0,
        "in_transit_units": 0,
        "current_list_unit_price_cents": 0,
        "current_effective_uplift_pct": 0,
    })
    domain.reprice_part(rec)
    store.parts[rec["id"]] = rec
    return envelope.created(serializers.part(rec))


@bp.get("/aftermarket/parts/<part_id>")
def read_part(part_id):
    auth.require("AftermarketPlanner", "InventoryController", "PricingAnalyst",
                 "DealerUser", "PlatformAdmin")
    return envelope.ok(serializers.part(domain.get_part(part_id)))


@bp.get("/aftermarket/parts")
def list_parts():
    auth.require("AftermarketPlanner", "InventoryController", "PricingAnalyst",
                 "DealerUser", "PlatformAdmin")
    limit, offset = auth.pagination()
    lifecycle_state = auth.query_enum("lifecycle_state", LIFECYCLE_STATES)
    criticality_class = auth.query_enum("criticality_class", CRITICALITY_CLASSES)
    successor = auth.query_str("superseded_by_part_id")

    rows = list(store.parts.values())
    if lifecycle_state is not None:
        rows = [r for r in rows if r["lifecycle_state"] == lifecycle_state]
    if criticality_class is not None:
        rows = [r for r in rows if r["criticality_class"] == criticality_class]
    if successor is not None:
        rows = [r for r in rows if r["superseded_by_part_id"] == successor]
    rows = store.sort_created(rows)
    page, total = auth.paginate(rows, limit, offset)
    return envelope.listing([serializers.part(r) for r in page], limit, offset, total)


@bp.patch("/aftermarket/parts/<part_id>")
def amend_part(part_id):
    auth.require("AftermarketPlanner")
    part = domain.get_part(part_id)
    data = auth.body()

    if "description" in data and data["description"] is not None:
        part["description"] = auth.req_str(data, "description")
    if "unit_cost_cents" in data and data["unit_cost_cents"] is not None:
        part["unit_cost_cents"] = auth.req_int(data, "unit_cost_cents", minimum=1)
    if "lead_time_days" in data and data["lead_time_days"] is not None:
        part["lead_time_days"] = auth.req_int(data, "lead_time_days", minimum=0)
    if "weight_kg" in data and data["weight_kg"] is not None:
        part["weight_kg"] = auth.req_number(data, "weight_kg", exclusive_min=0)
    if "hazmat" in data and data["hazmat"] is not None:
        part["hazmat"] = auth.req_bool(data, "hazmat")
    if "max_stock_units" in data and data["max_stock_units"] is not None:
        part["max_stock_units"] = auth.req_int(data, "max_stock_units", minimum=0)

    domain.reprice_part(part)
    store.touch(part)
    return envelope.ok(serializers.part(part))


# ------------------------------------------------------------ classify -----
@bp.post("/aftermarket/parts/<part_id>/classify")
def classify_part(part_id):
    auth.require("AftermarketPlanner")
    part = domain.get_part(part_id)

    forecast = domain.current_forecast(part["id"], 12)
    if forecast is None:
        # Priority 14 outranks priority 24: when the band has no ACTIVE rule at all
        # the missing-rule code wins; otherwise the empty-input code applies.
        if domain.active_price_rule(part["criticality_class"]) is None:
            raise ApiError("ERR_PRICE_RULE_NOT_FOUND")
        raise ApiError("ERR_FORECAST_INPUT_EMPTY")

    forecast_units = forecast["forecast_units"]
    demand_score = min(calc.DEMAND_SCORE_CAP,
                       Decimal(forecast_units) * calc.DEMAND_UNITS_MULTIPLIER)

    lines, pairs = domain.consumed_lines_in_window(part["id"], forecast["lookback_days"])
    total_lines = len(pairs)
    if total_lines == 0:
        downtime_score = Decimal("0.00")
    else:
        down_lines = sum(1 for _, wo in pairs if wo["downtime_priority"] == "MACHINE_DOWN")
        downtime_score = calc.round_half_up(
            calc.DOWNTIME_SCORE_MAX * Decimal(down_lines) / Decimal(total_lines), 2)

    lead_time_days = part["lead_time_days"]
    if lead_time_days >= calc.LEAD_TIME_LONG_DAYS:
        lead_time_score = Decimal(20)
    elif lead_time_days >= calc.LEAD_TIME_MED_DAYS:
        lead_time_score = Decimal(12)
    else:
        lead_time_score = Decimal(5)

    ib_units = forecast["installed_base_units"]
    if ib_units >= calc.COVERAGE_HIGH_UNITS:
        coverage_score = Decimal(10)
    elif ib_units >= calc.COVERAGE_MED_UNITS:
        coverage_score = Decimal(6)
    else:
        coverage_score = Decimal(2)

    score = calc.round_half_up(
        demand_score + downtime_score + lead_time_score + coverage_score, 2)

    if score >= calc.VITAL_THRESHOLD:
        new_class = "VITAL"
    elif score >= calc.ESSENTIAL_THRESHOLD:
        new_class = "ESSENTIAL"
    else:
        new_class = "DESIRABLE"

    rule = domain.active_price_rule(new_class)
    if rule is None:
        raise ApiError("ERR_PRICE_RULE_NOT_FOUND")

    if forecast_units == 0:
        policy = "NO_STOCK"
    elif new_class == "VITAL":
        policy = "STOCK_TO_MAX"
    elif new_class == "ESSENTIAL":
        policy = "MIN_MAX"
    else:
        policy = "MAKE_TO_ORDER"

    daily_demand = Decimal(forecast_units) / Decimal(365)
    service_factor = calc.SERVICE_FACTOR[new_class]
    safety_stock = calc.ceil_int(daily_demand * Decimal(lead_time_days) * service_factor)
    reorder_point = safety_stock + calc.ceil_int(daily_demand * Decimal(lead_time_days))

    part["criticality_score"] = score
    part["criticality_class"] = new_class
    part["stocking_policy"] = policy
    part["safety_stock_units"] = safety_stock
    part["reorder_point_units"] = reorder_point

    figures = calc.price_uplift(part["unit_cost_cents"], part["lifecycle_state"], rule, 1)
    part["current_effective_uplift_pct"] = figures["effective_uplift_pct"]
    part["current_list_unit_price_cents"] = figures["list_unit_price_cents"]

    store.touch(part)
    return envelope.ok(serializers.part(part))


# --------------------------------------------------- lifecycle actions -----
@bp.post("/aftermarket/parts/<part_id>/phase-out")
def phase_out_part(part_id):
    auth.require("AftermarketPlanner")
    part = domain.get_part(part_id)
    if part["lifecycle_state"] != "ACTIVE":
        raise ApiError("ERR_PART_LIFECYCLE_INVALID")
    domain.set_lifecycle_state(part, "PHASE_OUT")
    store.touch(part)
    return envelope.ok(serializers.part(part))


@bp.post("/aftermarket/parts/<part_id>/reinstate")
def reinstate_part(part_id):
    auth.require("AftermarketPlanner")
    part = domain.get_part(part_id)
    if part["lifecycle_state"] != "PHASE_OUT":
        raise ApiError("ERR_PART_LIFECYCLE_INVALID")
    for camp in store.campaigns.values():
        if camp["part_id"] == part["id"] and camp["status"] in ("SUBMITTED", "APPROVED", "ALLOCATING"):
            raise ApiError("ERR_PART_LIFECYCLE_INVALID")
    domain.set_lifecycle_state(part, "ACTIVE")
    store.touch(part)
    return envelope.ok(serializers.part(part))


@bp.post("/aftermarket/parts/<part_id>/supersede")
def supersede_part(part_id):
    auth.require("AftermarketPlanner")
    part = domain.get_part(part_id)
    data = auth.body()
    successor = fk(data, "successor_part_id", domain.get_part)
    successor_id = auth.req_id(data, "successor_part_id")
    if successor is None:
        successor = domain.get_part(successor_id)

    if part["lifecycle_state"] not in ("ACTIVE", "PHASE_OUT"):
        raise ApiError("ERR_PART_LIFECYCLE_INVALID")
    if successor["lifecycle_state"] == "OBSOLETE":
        raise ApiError("ERR_PART_LIFECYCLE_INVALID")

    # Priority 13 — the supersession chain must stay acyclic.
    cursor = successor
    seen = set()
    while cursor is not None:
        if cursor["id"] == part["id"]:
            raise ApiError("ERR_SUPERSESSION_CYCLE")
        if cursor["id"] in seen:
            break
        seen.add(cursor["id"])
        next_id = cursor.get("superseded_by_part_id")
        cursor = store.parts.get(next_id) if next_id else None

    part["superseded_by_part_id"] = successor["id"]
    part["lifecycle_state"] = "SUPERSEDED"
    part["stocking_policy"] = "NO_STOCK"

    touched_orders = set()
    for line in domain.lines_for_part(part["id"], domain.OPEN_LINE_STATES):
        if line["line_status"] == "RESERVED":
            part["allocated_units"] -= line["qty_requested"]
        line["line_status"] = "CANCELLED"
        store.touch(line)
        touched_orders.add(line["work_order_id"])
    for wo_id in touched_orders:
        wo = store.work_orders.get(wo_id)
        if wo is not None:
            domain.sync_work_order_backorders(wo)

    store.touch(part)
    return envelope.ok(serializers.part(part))


@bp.post("/aftermarket/parts/<part_id>/obsolete")
def obsolete_part(part_id):
    auth.require("AftermarketPlanner")
    part = domain.get_part(part_id)
    if part["lifecycle_state"] != "LTB_CLOSED":
        raise ApiError("ERR_PART_LIFECYCLE_INVALID")

    part["lifecycle_state"] = "OBSOLETE"
    part["stocking_policy"] = "NO_STOCK"
    part["safety_stock_units"] = 0
    part["reorder_point_units"] = 0
    for order in store.sort_created(list(store.replenishment_orders.values())):
        if order["part_id"] == part["id"] and order["approval_status"] == "PENDING":
            order["approval_status"] = "REJECTED"
            store.touch(order)
    domain.reprice_part(part)
    store.touch(part)
    return envelope.ok(serializers.part(part))


# -------------------------------------------------------------- ledger -----
@bp.get("/aftermarket/parts/<part_id>/ledger-entries")
def list_ledger(part_id):
    auth.require("AftermarketPlanner", "InventoryController", "PlatformAdmin")
    part = domain.get_part(part_id)
    limit, offset = auth.pagination()
    entry_type = auth.query_enum("entry_type", ENTRY_TYPES)

    rows = [e for e in store.ledger_entries.values() if e["part_id"] == part["id"]]
    if entry_type is not None:
        rows = [e for e in rows if e["entry_type"] == entry_type]
    rows = sorted(rows, key=lambda e: (e["occurred_at"], e["created_at"], e["_seq"]))
    page, total = auth.paginate(rows, limit, offset)
    return envelope.listing([serializers.ledger_entry(r) for r in page], limit, offset, total)


# ------------------------------------------------------------ forecasts ----
@bp.post("/aftermarket/parts/<part_id>/forecasts")
def create_forecast(part_id):
    auth.require("AftermarketPlanner")
    part = domain.get_part(part_id)
    data = auth.body()
    horizon_months = auth.req_int(data, "horizon_months")
    if horizon_months not in (12, 24, 60):
        raise ApiError("ERR_INVALID_REQUEST", "horizon_months must be one of 12, 24, 60.")
    method = auth.req_enum(data, "method", FORECAST_METHODS)
    lookback_days = auth.opt_int(data, "lookback_days",
                                 default=calc.DEFAULT_LOOKBACK_DAYS, minimum=1)

    lines, pairs = domain.consumed_lines_in_window(part["id"], lookback_days)
    if method == "WORK_ORDER_HISTORY" and not pairs:
        raise ApiError("ERR_FORECAST_INPUT_EMPTY")

    wo_history_units = sum(l["qty_consumed"] for l, _ in pairs)
    annualized = calc.round_half_up(
        Decimal(wo_history_units) * Decimal(365) / Decimal(lookback_days), 2)

    covered = domain.covered_units(part["id"])
    installed_base_units = len(covered)
    qty_per_unit = covered[0][1]["qty_per_unit"] if covered else 0
    ib_rate = calc.round_half_up(
        Decimal(installed_base_units) * Decimal(qty_per_unit) * calc.ANNUAL_REPLACEMENT_RATE, 2)

    if method == "WORK_ORDER_HISTORY":
        raw = annualized
    elif method == "INSTALLED_BASE_RATE":
        raw = ib_rate
    else:
        raw = calc.round_half_up(
            calc.BLEND_WEIGHT_WO * annualized + (Decimal(1) - calc.BLEND_WEIGHT_WO) * ib_rate, 2)
    forecast_units = calc.ceil_int(raw)

    for prior in store.forecasts.values():
        if (prior["part_id"] == part["id"]
                and prior["horizon_months"] == horizon_months
                and prior["forecast_status"] == "CURRENT"):
            prior["forecast_status"] = "SUPERSEDED"
            store.touch(prior)

    rec = store.new_record("DemandForecast", {
        "part_id": part["id"],
        "horizon_months": horizon_months,
        "lookback_days": lookback_days,
        "method": method,
        "wo_history_units": wo_history_units,
        "annualized_wo_units": annualized,
        "installed_base_units": installed_base_units,
        "ib_rate_units": ib_rate,
        "forecast_units": forecast_units,
        "forecast_status": "CURRENT",
        "computed_at": store.now(),
    })
    store.forecasts[rec["id"]] = rec
    return envelope.created(serializers.forecast(rec))


@bp.get("/aftermarket/parts/<part_id>/forecasts")
def list_forecasts(part_id):
    auth.require("AftermarketPlanner", "InventoryController", "PricingAnalyst", "PlatformAdmin")
    part = domain.get_part(part_id)
    limit, offset = auth.pagination()
    horizon_months = auth.query_int("horizon_months")
    forecast_status = auth.query_enum("forecast_status", {"CURRENT", "SUPERSEDED"})

    rows = [f for f in store.forecasts.values() if f["part_id"] == part["id"]]
    if horizon_months is not None:
        rows = [f for f in rows if f["horizon_months"] == horizon_months]
    if forecast_status is not None:
        rows = [f for f in rows if f["forecast_status"] == forecast_status]
    rows = sorted(rows, key=lambda f: (f["computed_at"], f["created_at"], f["_seq"]),
                  reverse=True)
    page, total = auth.paginate(rows, limit, offset)
    return envelope.listing([serializers.forecast(r) for r in page], limit, offset, total)
