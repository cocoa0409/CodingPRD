"""Stores, domiciles and pay plans -- PRD §3.1 and the cost benchmark of §3.8."""

from datetime import timedelta

from flask import Blueprint

import calc
from core import (
    ALL_ROLES, D, apply_filters, auth, bump, dec, fail, must_exist, new_row, out,
    page, respond, rhu4, rhu_cents, unique_code, db,
)
import validate as v

bp = Blueprint("network", __name__)

READ_ROLES = ALL_ROLES
STORE_STATUSES = ("ACTIVE", "SUSPENDED")


# ===========================================================================
# Stores
# ===========================================================================
@bp.post("/stores")
def create_store():
    auth(["FleetPlanner"])
    data = v.body()
    store_code = v.rstr(data, "store_code", 1, 16)
    region_code = v.rstr(data, "region_code")
    dock_count = v.rint(data, "dock_count", 1)
    unload_rate = v.rint(data, "cases_per_hour_unload_rate", 1)
    dock_open_minute = v.rint(data, "dock_open_minute", 0, 1439)
    dock_close_minute = v.rint(data, "dock_close_minute", 0, 1439)
    if dock_open_minute >= dock_close_minute:
        fail("ERR_INVALID_REQUEST", "'dock_open_minute' must be strictly less than 'dock_close_minute'.")
    unique_code(db.stores, "store_code", store_code)
    row = new_row({
        "store_code": store_code,
        "region_code": region_code,
        "dock_count": dock_count,
        "cases_per_hour_unload_rate": unload_rate,
        "dock_open_minute": dock_open_minute,
        "dock_close_minute": dock_close_minute,
        "status": "ACTIVE",
        "open_scheduled_cases": 0,
        "delivered_cases_total": 0,
    })
    db.stores[row["id"]] = row
    return respond(out(row), 201)


@bp.get("/stores/<store_id>")
def get_store(store_id):
    auth(READ_ROLES)
    return respond(out(must_exist("stores", store_id)))


@bp.get("/stores")
def list_stores():
    auth(READ_ROLES)
    limit, offset = v.page_window()
    rows = apply_filters(
        list(db.stores.values()),
        [("region_code", v.qstr("region_code")), ("status", v.qenum("status", STORE_STATUSES))],
    )
    return page(rows, limit, offset)


@bp.post("/stores/<store_id>/status")
def set_store_status(store_id):
    auth(["TransportManager"])
    store = must_exist("stores", store_id)
    data = v.body()
    status = v.renum(data, "status", STORE_STATUSES)
    store["status"] = status
    bump(store)
    return respond(out(store))


# ===========================================================================
# Domiciles
# ===========================================================================
@bp.post("/domiciles")
def create_domicile():
    auth(["FleetPlanner"])
    data = v.body()
    domicile_code = v.rstr(data, "domicile_code", 1, 16)
    region_code = v.rstr(data, "region_code")
    tractor_capacity = v.rint(data, "tractor_capacity", 1)
    headcount_target = v.rint(data, "driver_headcount_target", 1)
    fixed_ownership = v.rint(data, "fixed_ownership_cents_per_day", 0)
    overhead = v.rint(data, "overhead_cents_per_day", 0)
    dedicated_mile = v.rint(data, "dedicated_rate_cents_per_mile", 0)
    dedicated_case = v.rint(data, "dedicated_rate_cents_per_case", 0)
    unique_code(db.domiciles, "domicile_code", domicile_code)
    row = new_row({
        "domicile_code": domicile_code,
        "region_code": region_code,
        "tractor_capacity": tractor_capacity,
        "driver_headcount_target": headcount_target,
        "fixed_ownership_cents_per_day": fixed_ownership,
        "overhead_cents_per_day": overhead,
        "dedicated_rate_cents_per_mile": dedicated_mile,
        "dedicated_rate_cents_per_case": dedicated_case,
        "assigned_driver_count": 0,
        "balance_index": 0.0,
        "accrued_pay_cents": 0,
    })
    db.domiciles[row["id"]] = row
    return respond(out(row), 201)


@bp.get("/domiciles/<domicile_id>")
def get_domicile(domicile_id):
    auth(READ_ROLES)
    return respond(out(must_exist("domiciles", domicile_id)))


@bp.get("/domiciles")
def list_domiciles():
    auth(READ_ROLES)
    limit, offset = v.page_window()
    rows = apply_filters(
        list(db.domiciles.values()), [("region_code", v.qstr("region_code"))]
    )
    return page(rows, limit, offset)


BENCHMARK_VARIANTS = ("FULLY_ALLOCATED", "INCREMENTAL_VARIABLE")


@bp.get("/domiciles/<domicile_id>/cost-benchmark")
def cost_benchmark(domicile_id):
    auth(["TransportManager", "PayrollAnalyst"])
    domicile = must_exist("domiciles", domicile_id)
    variant = v.qrequired_enum("variant", BENCHMARK_VARIANTS)
    window_start = v.qinstant("window_start", required=True)
    window_end = v.qinstant("window_end", required=True)
    v.window_order(window_start, window_end, "window_start", "window_end")
    ws, we = D(window_start), D(window_end)

    included = [
        t for t in db.trips.values()
        if t["domicile_id"] == domicile["id"]
        and t["plan_status"] == "COMPLETED"
        and t["settlement_status"] in ("ACCRUED", "SETTLED")
        and ws <= D(t["planned_start_at"]) < we
    ]
    included.sort(key=lambda t: (t["created_at"], t["_seq"]))
    included_ids = {t["id"] for t in included}

    total_miles = sum(int(t["total_miles"]) for t in included)
    total_cases = 0
    for t in included:
        for s in calc.trip_stops(t["id"]):
            if s["status"] == "COMPLETED" and s["stop_type"] == "DELIVERY":
                total_cases += int(s.get("cases") or 0)

    driver_pay_cents = sum(
        int(st["gross_cents"]) for st in db.statements.values()
        if st["trip_id"] in included_ids and st["status"] in ("ACCRUED", "SETTLED")
    )
    fuel_cents = rhu_cents(dec(total_miles) * dec(calc.FUEL_CENTS_PER_MILE))
    maintenance_cents = rhu_cents(dec(total_miles) * dec(calc.MAINTENANCE_CENTS_PER_MILE))
    backhaul_credit_cents = 0
    for t in included:
        offer = db.offers.get(t.get("backhaul_offer_id")) if t.get("backhaul_offer_id") else None
        if offer is not None and offer["status"] == "ACCEPTED":
            backhaul_credit_cents += int(offer["contribution_margin_cents"])

    variable_cost_cents = (
        driver_pay_cents + fuel_cents + maintenance_cents - backhaul_credit_cents
    )
    window_days = int((we - ws).total_seconds() // 86400)
    if window_days < 1:
        window_days = 1
    fixed_cost_cents = window_days * (
        int(domicile["fixed_ownership_cents_per_day"]) + int(domicile["overhead_cents_per_day"])
    )
    if variant == "FULLY_ALLOCATED":
        total_cost_cents = variable_cost_cents + fixed_cost_cents
    else:
        total_cost_cents = variable_cost_cents

    if total_cases == 0 or total_miles == 0:
        fail("ERR_BENCHMARK_NO_VOLUME")

    cost_per_case_cents = rhu_cents(dec(total_cost_cents) / dec(total_cases))
    cost_per_mile_cents = rhu_cents(dec(total_cost_cents) / dec(total_miles))
    dedicated_case = int(domicile["dedicated_rate_cents_per_case"])
    return respond({
        "variant": variant,
        "window_start": window_start,
        "window_end": window_end,
        "window_days": window_days,
        "trip_count": len(included),
        "total_miles": total_miles,
        "total_cases": total_cases,
        "driver_pay_cents": driver_pay_cents,
        "fuel_cents": fuel_cents,
        "maintenance_cents": maintenance_cents,
        "backhaul_credit_cents": backhaul_credit_cents,
        "variable_cost_cents": variable_cost_cents,
        "fixed_cost_cents": fixed_cost_cents,
        "total_cost_cents": total_cost_cents,
        "cost_per_case_cents": cost_per_case_cents,
        "cost_per_mile_cents": cost_per_mile_cents,
        "dedicated_equivalent_cents_per_case": dedicated_case,
        "advantage_cents_per_case": dedicated_case - cost_per_case_cents,
    })


# ===========================================================================
# Driver pay plans
# ===========================================================================
@bp.post("/driver-pay-plans")
def create_pay_plan():
    auth(["PayrollAnalyst"])
    data = v.body()
    plan_code = v.rstr(data, "plan_code", 1, 16)
    mileage = v.rint(data, "mileage_cents_per_mile", 0)
    stop_cents = v.rint(data, "stop_cents_per_stop", 0)
    drop_hook = v.rint(data, "drop_hook_cents", 0)
    hourly = v.rint(data, "hourly_cents_per_minute", 0)
    minimum_daily = v.rint(data, "minimum_daily_cents", 0)
    bonus_pct = v.rnum(data, "backhaul_bonus_pct", 0, 0.50)
    unique_code(db.pay_plans, "plan_code", plan_code)
    row = new_row({
        "plan_code": plan_code,
        "mileage_cents_per_mile": mileage,
        "stop_cents_per_stop": stop_cents,
        "drop_hook_cents": drop_hook,
        "hourly_cents_per_minute": hourly,
        "minimum_daily_cents": minimum_daily,
        "backhaul_bonus_pct": bonus_pct,
    })
    db.pay_plans[row["id"]] = row
    return respond(out(row), 201)


@bp.get("/driver-pay-plans/<pay_plan_id>")
def get_pay_plan(pay_plan_id):
    auth(READ_ROLES)
    return respond(out(must_exist("pay_plans", pay_plan_id)))


@bp.get("/driver-pay-plans")
def list_pay_plans():
    auth(READ_ROLES)
    limit, offset = v.page_window()
    return page(list(db.pay_plans.values()), limit, offset)


@bp.patch("/driver-pay-plans/<pay_plan_id>")
def amend_pay_plan(pay_plan_id):
    auth(["PayrollAnalyst"])
    plan = must_exist("pay_plans", pay_plan_id)
    data = v.body()
    mileage = v.oint(data, "mileage_cents_per_mile", None, 0)
    stop_cents = v.oint(data, "stop_cents_per_stop", None, 0)
    drop_hook = v.oint(data, "drop_hook_cents", None, 0)
    hourly = v.oint(data, "hourly_cents_per_minute", None, 0)
    minimum_daily = v.oint(data, "minimum_daily_cents", None, 0)
    bonus_pct = v.onum(data, "backhaul_bonus_pct", None, 0, 0.50)
    supplied = [
        ("mileage_cents_per_mile", mileage),
        ("stop_cents_per_stop", stop_cents),
        ("drop_hook_cents", drop_hook),
        ("hourly_cents_per_minute", hourly),
        ("minimum_daily_cents", minimum_daily),
        ("backhaul_bonus_pct", bonus_pct),
    ]
    for field, value in supplied:
        if value is not None:
            plan[field] = value
    bump(plan)
    return respond(out(plan))
