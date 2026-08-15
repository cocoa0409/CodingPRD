"""SeasonalWindow + SeasonalAllotment + CustomerAccount endpoints."""
from decimal import Decimal

from flask import Blueprint, request

import domain as D
from db import store, mint, touch, now
from errors import err
from middleware import authorize, ROLES
from response import ok, ok_list
from validate import (body, need_str, need_num, need_int, need_enum, need_date,
                      paginate)

bp = Blueprint("sales", __name__)


# ---- SeasonalWindow ----

@bp.post("/plant/seasonal-windows")
def create_window():
    authorize(["PlantManager"])
    b = body()
    window_name = need_str(b, "window_name")
    starts_on = need_date(b, "starts_on")
    ends_on = need_date(b, "ends_on")
    demand_multiplier = need_num(b, "demand_multiplier")
    forecast_total_cases = need_int(b, "forecast_total_cases")
    if ends_on < starts_on:
        err("ERR_INVALID_REQUEST", 400, "ends_on must be on or after starts_on")
    if demand_multiplier < Decimal("1.0"):
        err("ERR_INVALID_REQUEST", 400, "demand_multiplier must be at least 1.0")
    if forecast_total_cases < 0:
        err("ERR_INVALID_REQUEST", 400, "forecast_total_cases must be at least zero")
    # Closed inclusive date-interval overlap vs SCHEDULED/ACTIVE windows
    for w in store.windows.values():
        if w["window_status"] not in ("SCHEDULED", "ACTIVE"):
            continue
        if starts_on <= w["ends_on"] and ends_on >= w["starts_on"]:
            err("ERR_WINDOW_DATE_OVERLAP", 409,
                "Window dates overlap an existing SCHEDULED/ACTIVE window")
    window = mint()
    window.update({
        "window_name": window_name, "starts_on": starts_on, "ends_on": ends_on,
        "demand_multiplier": demand_multiplier,
        "forecast_total_cases": forecast_total_cases,
        "is_strict": demand_multiplier >= D.SPIKE_MULTIPLIER_THRESHOLD,
        "window_status": "SCHEDULED",
    })
    store.windows[window["id"]] = window
    return ok(D.window_json(window), 201)


@bp.get("/plant/seasonal-windows")
def list_windows():
    authorize(ROLES)
    status = request.args.get("window_status")
    items = [w for w in store.windows.values()
             if status is None or w["window_status"] == status]
    page, limit, offset, total = paginate(items, D.window_json)
    return ok_list(page, limit, offset, total)


@bp.get("/plant/seasonal-windows/<wid>")
def get_window(wid):
    authorize(ROLES)
    return ok(D.window_json(D.get_window(wid)))


def _create_allotment(window, customer, allotted_cases):
    a = mint()
    a.update({"seasonal_window_id": window["id"], "customer_id": customer["id"],
              "allotted_cases": allotted_cases, "allotment_status": "ACTIVE"})
    store.allotments[a["id"]] = a
    return a


@bp.post("/plant/seasonal-windows/<wid>/activate")
def activate_window(wid):
    authorize(["PlantManager"])
    window = D.get_window(wid)
    if window["window_status"] != "SCHEDULED":
        err("ERR_WINDOW_INVALID_STATE", 409, "Window must be SCHEDULED to activate")
    today = now().date()
    if not (window["starts_on"] <= today <= window["ends_on"]):
        err("ERR_WINDOW_INVALID_STATE", 409,
            "Logical clock date is outside the window's [starts_on, ends_on]")
    # Waterfall (pinned order): foodservice first, then retail tiers A>B>C.
    mult = window["demand_multiplier"]
    good = sorted((c for c in store.customers.values()
                   if c["credit_standing"] == "GOOD"), key=lambda c: c["_seq"])
    foodservice = [c for c in good if c["channel"] == "FOODSERVICE_DIST"]
    retail = [c for c in good if c["channel"] in ("RETAIL_GROCERY", "TORTILLERIA")]
    retail.sort(key=lambda c: (D.TIER_ORDER[c["priority_tier"]], c["_seq"]))
    fs_total = 0
    for c in foodservice:
        allotted = D.ceil_int(Decimal(c["base_weekly_cases"]) * mult)
        _create_allotment(window, c, allotted)
        fs_total += allotted
    pool = window["forecast_total_cases"] - fs_total
    if pool < 0:
        pool = 0
    for c in retail:
        request_cases = D.ceil_int(Decimal(c["base_weekly_cases"]) * mult
                                   * D.TIER_FACTOR[c["priority_tier"]])
        allotted = min(request_cases, pool)
        _create_allotment(window, c, allotted)
        pool -= allotted
    window["window_status"] = "ACTIVE"
    touch(window)
    # Strict-mode enforcement sweep: short pre-existing ALLOCATED stops dated
    # inside the window that exceed the customer's new allotment (created_at ASC).
    if window["is_strict"]:
        stops = [s for s in store.stops.values()
                 if s["stop_status"] == "ALLOCATED"
                 and D.window_covers_date(
                     window, store.routes[s["route_id"]]["route_date"])]
        stops.sort(key=lambda s: s["_seq"])
        for s in stops:
            allot = D.find_allotment(window["id"], s["customer_id"])
            remaining = (allot["allotted_cases"]
                         - D.allotment_consumed_cases(allot)) if allot else 0
            if s["allocated_cases"] > remaining:
                D.short_stop(s)
    return ok(D.window_json(window))


@bp.post("/plant/seasonal-windows/<wid>/close")
def close_window(wid):
    authorize(["PlantManager"])
    window = D.get_window(wid)
    if window["window_status"] != "ACTIVE":
        err("ERR_WINDOW_INVALID_STATE", 409, "Window must be ACTIVE to close")
    window["window_status"] = "CLOSED"
    touch(window)
    for a in store.allotments.values():
        if a["seasonal_window_id"] == wid and a["allotment_status"] == "ACTIVE":
            a["allotment_status"] = "CLOSED"
            touch(a)
    return ok(D.window_json(window))


@bp.get("/plant/seasonal-windows/<wid>/allotments")
def window_allotments(wid):
    authorize(ROLES)
    D.get_window(wid)
    items = [a for a in store.allotments.values() if a["seasonal_window_id"] == wid]
    page, limit, offset, total = paginate(items, D.allotment_json)
    return ok_list(page, limit, offset, total)


@bp.get("/plant/allotments/<aid>")
def get_allotment(aid):
    authorize(ROLES)
    return ok(D.allotment_json(D.get_allotment(aid)))


# ---- CustomerAccount ----

@bp.post("/plant/customers")
def create_customer():
    authorize(["PlantManager"])
    b = body()
    account_name = need_str(b, "account_name")
    channel = need_enum(b, "channel", D.CUSTOMER_CHANNELS)
    region = need_str(b, "region")
    base_weekly_cases = need_int(b, "base_weekly_cases")
    priority_tier = need_enum(b, "priority_tier", D.PRIORITY_TIERS)
    min_shelf_life_pct = need_int(b, "min_shelf_life_pct")
    if base_weekly_cases < 0:
        err("ERR_INVALID_REQUEST", 400, "base_weekly_cases must be at least zero")
    if not (1 <= min_shelf_life_pct <= 100):
        err("ERR_INVALID_REQUEST", 400,
            "min_shelf_life_pct must lie between 1 and 100 inclusive")
    customer = mint()
    customer.update({
        "account_name": account_name, "channel": channel, "region": region,
        "base_weekly_cases": base_weekly_cases, "priority_tier": priority_tier,
        "min_shelf_life_pct": min_shelf_life_pct, "credit_standing": "GOOD",
    })
    store.customers[customer["id"]] = customer
    return ok(D.customer_json(customer), 201)


@bp.get("/plant/customers")
def list_customers():
    authorize(ROLES)
    channel = request.args.get("channel")
    credit = request.args.get("credit_standing")
    items = [c for c in store.customers.values()
             if (channel is None or c["channel"] == channel)
             and (credit is None or c["credit_standing"] == credit)]
    page, limit, offset, total = paginate(items, D.customer_json)
    return ok_list(page, limit, offset, total)


@bp.get("/plant/customers/<cid>")
def get_customer(cid):
    authorize(ROLES)
    return ok(D.customer_json(D.get_customer(cid)))


@bp.post("/plant/customers/<cid>/set-credit-standing")
def set_credit_standing(cid):
    authorize(["PlantManager"])
    b = body()
    credit_standing = need_enum(b, "credit_standing", D.CREDIT_STANDINGS)
    customer = D.get_customer(cid)
    customer["credit_standing"] = credit_standing
    touch(customer)
    return ok(D.customer_json(customer))


@bp.get("/plant/customers/<cid>/stops")
def customer_stops(cid):
    authorize(ROLES)
    D.get_customer(cid)
    items = [s for s in store.stops.values() if s["customer_id"] == cid]
    page, limit, offset, total = paginate(items, D.stop_json)
    return ok_list(page, limit, offset, total)


@bp.get("/plant/customers/<cid>/allotments")
def customer_allotments(cid):
    authorize(ROLES)
    D.get_customer(cid)
    items = [a for a in store.allotments.values() if a["customer_id"] == cid]
    page, limit, offset, total = paginate(items, D.allotment_json)
    return ok_list(page, limit, offset, total)
