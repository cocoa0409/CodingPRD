"""DispatchPlan and DispatchOrder endpoints (PRD 3.4, 3.9)."""

from flask import Blueprint, g

import calc
import enums
import services as svc
from calc import D, f
from db import base_record, store, touch
from errors import fail
from middleware import endpoint, paginate
from validators import (get_enum, get_int, get_str, json_body, present,
                        query_enum, query_str)

bp = Blueprint("plans", __name__, url_prefix="/district-energy")

READERS = ("SystemController", "DispatchOperator", "NetworkEngineer", "BillingAnalyst")


def _optional_note(body, name):
    if present(body, name):
        get_str(body, name, min_len=0)


@endpoint(bp, "/dispatch-plans", ["POST"], ["DispatchOperator"], status=201)
def create_plan():
    body = json_body()
    loop_id = get_str(body, "loop_id")
    forecast_id = get_str(body, "forecast_id")
    expected_loop_version = get_int(body, "expected_loop_version", ge=0)

    loop = svc.fk_get("loops", loop_id)
    forecast = svc.fk_get("forecasts", forecast_id)

    if loop["version"] != expected_loop_version:
        fail("ERR_STALE_LOOP_VERSION",
             "the loop is at version %d, not %d"
             % (loop["version"], expected_loop_version))

    if forecast["loop_id"] != loop["id"]:
        fail("ERR_FORECAST_LOOP_MISMATCH",
             "the forecast belongs to a different loop")

    plan = base_record()
    plan.update({
        "loop_id": loop["id"],
        "forecast_id": forecast["id"],
        "block_hours": f(calc.DISPATCH_BLOCK_HOURS),
        "authored_by_user_id": g.user_id,
        "reviewed_by_user_id": None,
        "allocated_capacity_kw": 0.0,
        "unserved_demand_kw": 0.0,
        "total_dispatch_cost": 0.0,
        "total_emissions_kg": 0.0,
        "reserve_margin_pct": 0.0,
        "fuel_diversity_hhi": 0.0,
        "plan_state": "DRAFT",
    })
    store.plans[plan["id"]] = plan

    svc.supersede_loop_plans(loop["id"], exclude_id=plan["id"])
    touch(loop)
    return plan


@endpoint(bp, "/dispatch-plans", ["GET"], READERS)
def list_plans():
    filters = {}
    loop_id = query_str("loop_id")
    forecast_id = query_str("forecast_id")
    plan_state = query_enum("plan_state", enums.PLAN_STATE)
    if loop_id is not None:
        filters["loop_id"] = loop_id
    if forecast_id is not None:
        filters["forecast_id"] = forecast_id
    if plan_state is not None:
        filters["plan_state"] = plan_state
    return paginate(svc.where("plans", **filters))


@endpoint(bp, "/dispatch-plans/<plan_id>", ["GET"], READERS)
def get_plan(plan_id):
    return svc.path_get("plans", plan_id)


@endpoint(bp, "/dispatch-plans/<plan_id>/optimize", ["POST"], ["DispatchOperator"])
def optimize_plan(plan_id):
    plan = svc.path_get("plans", plan_id)
    if plan["plan_state"] != "DRAFT":
        fail("ERR_PLAN_STATE_INVALID", "only a DRAFT plan can be optimized")

    forecast = store.forecasts[plan["forecast_id"]]
    if forecast["forecast_state"] != "PUBLISHED":
        fail("ERR_FORECAST_STATE_INVALID",
             "the plan's forecast is not PUBLISHED")

    eligible = svc.eligible_assets(plan["loop_id"])
    if not eligible:
        fail("ERR_NO_ELIGIBLE_ASSETS",
             "no production asset on the loop is eligible for dispatch")

    demand_kw = forecast["coincident_demand_kw"]
    payloads, totals = calc.merit_order_dispatch(eligible, demand_kw)
    metrics = calc.plan_reliability_metrics(
        eligible, demand_kw, payloads, lambda order: svc.fuel_key(order["asset"]))

    for order_id in [o["id"] for o in store.orders.values()
                     if o["plan_id"] == plan["id"]]:
        del store.orders[order_id]

    for payload in payloads:
        order = base_record(versioned=False)
        order.update({
            "plan_id": plan["id"],
            "asset_id": payload["asset"]["id"],
            "merit_rank": payload["merit_rank"],
            "allocated_kw": payload["allocated_kw"],
            "block_energy_mwh": payload["block_energy_mwh"],
            "discharged_kwh": payload["discharged_kwh"],
            "order_cost": payload["order_cost"],
            "order_emissions_kg": payload["order_emissions_kg"],
        })
        store.orders[order["id"]] = order

    plan.update(totals)
    plan.update(metrics)
    touch(plan)
    return plan


@endpoint(bp, "/dispatch-plans/<plan_id>/submit", ["POST"], ["DispatchOperator"])
def submit_plan(plan_id):
    body = json_body()
    _optional_note(body, "submission_note")

    plan = svc.path_get("plans", plan_id)
    if plan["plan_state"] != "DRAFT":
        fail("ERR_PLAN_STATE_INVALID", "only a DRAFT plan can be submitted")
    if not svc.plan_orders(plan["id"]):
        fail("ERR_PLAN_HAS_NO_ORDERS",
             "the plan carries no dispatch orders")
    if D(plan["unserved_demand_kw"]) != D(0):
        fail("ERR_INSUFFICIENT_GENERATION",
             "the merit-order waterfall left %s kW unserved"
             % plan["unserved_demand_kw"])

    plan["plan_state"] = "SUBMITTED"
    touch(plan)
    return plan


@endpoint(bp, "/dispatch-plans/<plan_id>/review", ["POST"], ["SystemController"])
def review_plan(plan_id):
    body = json_body()
    decision = get_enum(body, "decision", enums.REVIEW_DECISION)
    _optional_note(body, "review_note")

    plan = svc.path_get("plans", plan_id)
    if plan["plan_state"] != "SUBMITTED":
        fail("ERR_PLAN_STATE_INVALID", "only a SUBMITTED plan can be reviewed")
    if g.user_id == plan["authored_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "the reviewer must differ from the plan author")

    if decision == "APPROVE":
        if D(plan["reserve_margin_pct"]) < calc.MIN_RESERVE_MARGIN_PCT:
            fail("ERR_RESERVE_MARGIN_INSUFFICIENT",
                 "the N-1 reserve margin %s%% is below the %s%% floor"
                 % (plan["reserve_margin_pct"], calc.MIN_RESERVE_MARGIN_PCT))
        if D(plan["fuel_diversity_hhi"]) > calc.MAX_FUEL_DIVERSITY_HHI:
            fail("ERR_FUEL_DIVERSITY_BREACH",
                 "the fuel concentration index %s exceeds the %s ceiling"
                 % (plan["fuel_diversity_hhi"], calc.MAX_FUEL_DIVERSITY_HHI))
        plan["reviewed_by_user_id"] = g.user_id
        plan["plan_state"] = "APPROVED"
        touch(plan)
        loop = store.loops.get(plan["loop_id"])
        if (loop is not None and loop["posture"] == "CONSTRAINED"
                and loop["open_isolation_count"] == 0):
            loop["posture"] = "NORMAL"
            touch(loop)
        return plan

    plan["reviewed_by_user_id"] = g.user_id
    plan["plan_state"] = "DRAFT"
    touch(plan)
    return plan


@endpoint(bp, "/dispatch-plans/<plan_id>/commit", ["POST"], ["DispatchOperator"])
def commit_plan(plan_id):
    plan = svc.path_get("plans", plan_id)
    if plan["plan_state"] != "APPROVED":
        fail("ERR_PLAN_STATE_INVALID", "only an APPROVED plan can be committed")

    loop = store.loops.get(plan["loop_id"])
    if loop is None or loop["posture"] != "NORMAL":
        fail("ERR_LOOP_NOT_NORMAL",
             "the loop posture must be NORMAL to commit a plan")

    storage_orders = [o for o in svc.plan_orders(plan["id"])
                      if D(o["discharged_kwh"]) > D(0)]
    for order in storage_orders:
        asset = store.assets.get(order["asset_id"])
        if asset is None or D(asset["state_of_charge_kwh"]) < D(order["discharged_kwh"]):
            fail("ERR_STORAGE_ENERGY_INSUFFICIENT",
                 "the storage asset holds less energy than the plan schedules")

    for order in storage_orders:
        asset = store.assets[order["asset_id"]]
        asset["state_of_charge_kwh"] = f(
            D(asset["state_of_charge_kwh"]) - D(order["discharged_kwh"]))
        touch(asset)

    plan["plan_state"] = "COMMITTED"
    touch(plan)
    return plan


@endpoint(bp, "/dispatch-plans/<plan_id>/decommit", ["POST"], ["SystemController"])
def decommit_plan(plan_id):
    body = json_body()
    _optional_note(body, "reason")

    plan = svc.path_get("plans", plan_id)
    if plan["plan_state"] != "COMMITTED":
        fail("ERR_PLAN_STATE_INVALID", "only a COMMITTED plan can be decommitted")

    for order in svc.plan_orders(plan["id"]):
        if D(order["discharged_kwh"]) <= D(0):
            continue
        asset = store.assets.get(order["asset_id"])
        if asset is None:
            continue
        asset["state_of_charge_kwh"] = f(
            D(asset["state_of_charge_kwh"]) + D(order["discharged_kwh"]))
        touch(asset)

    plan["plan_state"] = "DRAFT"
    plan["reviewed_by_user_id"] = None
    touch(plan)
    return plan


@endpoint(bp, "/dispatch-plans/<plan_id>/reconcile", ["POST"], ["SystemController"])
def reconcile_plan(plan_id):
    plan = svc.path_get("plans", plan_id)
    if plan["plan_state"] != "COMMITTED":
        fail("ERR_PLAN_STATE_INVALID", "only a COMMITTED plan can be reconciled")

    forecast = store.forecasts[plan["forecast_id"]]
    if forecast["variant_applied"] != "ACTUAL_WEIGHTED_FINAL":
        fail("ERR_FORECAST_STATE_INVALID",
             "the plan's forecast has not been finalised on actual weather")

    plan["plan_state"] = "RECONCILED"
    touch(plan)
    return plan


@endpoint(bp, "/dispatch-orders", ["GET"], READERS)
def list_orders():
    filters = {}
    plan_id = query_str("plan_id")
    asset_id = query_str("asset_id")
    if plan_id is not None:
        filters["plan_id"] = plan_id
    if asset_id is not None:
        filters["asset_id"] = asset_id
    return paginate(svc.where("orders", **filters))


@endpoint(bp, "/dispatch-orders/<order_id>", ["GET"], READERS)
def get_order(order_id):
    return svc.path_get("orders", order_id)
