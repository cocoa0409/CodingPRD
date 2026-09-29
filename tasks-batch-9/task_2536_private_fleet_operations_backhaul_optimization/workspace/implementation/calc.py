"""The fourteen calculations of the PRD, transcribed from §3 and cross-checked
against SCAFFOLD.yaml `calculations`.
"""

from datetime import timedelta
from decimal import Decimal

from core import (
    D, ceil_div, coll, db, dec, fail, fmt_instant, new_row, bump, rhu4,
    rhu_cents,
)

# --- calculations.trip_plan_totals -----------------------------------------
FIXED_DELIVERY_SETUP_MINUTES = 15
FIXED_PICKUP_MINUTES = 45
FIXED_DROP_OFF_MINUTES = 20
FIXED_FUEL_MINUTES = 25
MANDATORY_BREAK_MINUTES = 30
BREAK_TRIGGER_DRIVE_MINUTES = 480

# --- calculations.hos_feasibility ------------------------------------------
MAX_DAILY_DRIVE_MINUTES = 660
MAX_DAILY_DUTY_MINUTES = 840
MAX_WEEKLY_ON_DUTY_MINUTES = 4200

# --- calculations.driver_trip_pay ------------------------------------------
DETENTION_GRACE_MINUTES = 30

# --- calculations.backhaul_contribution_margin ----------------------------
LINEHAUL_VARIABLE_CENTS_PER_MILE = 185
HANDLING_CENTS_PER_CASE = 9
REEFER_SURCHARGE_CENTS_PER_MILE = 22
COMMISSION_TIER_THRESHOLD_PCT = Decimal("0.20")
COMMISSION_RATE_HIGH = Decimal("0.06")
COMMISSION_RATE_LOW = Decimal("0.03")
MIN_MARGIN_PCT = Decimal("0.08")

# --- calculations.domicile_cost_benchmark ---------------------------------
FUEL_CENTS_PER_MILE = 62
MAINTENANCE_CENTS_PER_MILE = 19

# --- calculations.domicile_balance_index ----------------------------------
REBALANCE_SOURCE_MIN_INDEX = Decimal("1.5000")
REBALANCE_TARGET_MAX_INDEX = Decimal("1.0000")

# --- calculations.driver_safety_score -------------------------------------
BASE_POINTS = {
    "HARD_BRAKE": 2,
    "SPEEDING": 3,
    "FOLLOWING_DISTANCE": 2,
    "SEATBELT": 4,
}
SAFETY_SCORE_FLOOR = 0
COACHING_HOLD_SCORE_THRESHOLD = 70

# --- calculations.route_award_selection -----------------------------------
MIN_BID_SAFETY_SCORE = 80

# --- calculations.pm_due_projection ---------------------------------------
PM_WINDOW_MINUTES = 480

# --- calculations.asset_maintenance_conflict ------------------------------
SHOP_BUFFER_MINUTES = 120

# --- calculations.driver_rest_gap -----------------------------------------
MIN_REST_MINUTES = 600

COMMITTED_PLAN_STATUSES = ("PLANNED", "DISPATCHED", "IN_PROGRESS")
OPEN_WORK_ORDER_STATUSES = ("SCHEDULED", "DEFERRED", "IN_SHOP")


# ===========================================================================
# trip_plan_totals + trailer_peak_case_load
# ===========================================================================
def stop_service_minutes(stop):
    """§3.4: per-stop service minutes, rounded UP at this stop."""
    st = stop["stop_type"]
    if st == "DELIVERY":
        store = db.stores.get(stop.get("store_id"))
        rate = store["cases_per_hour_unload_rate"] if store else 1
        unload = ceil_div(int(stop.get("cases") or 0) * 60, rate)
        return unload + FIXED_DELIVERY_SETUP_MINUTES
    if st in ("VENDOR_PICKUP", "THIRD_PARTY_PICKUP"):
        return FIXED_PICKUP_MINUTES
    if st == "DROP_OFF":
        return FIXED_DROP_OFF_MINUTES
    return FIXED_FUEL_MINUTES


def trip_stops(trip_id):
    return sorted(
        (s for s in db.stops.values() if s["trip_id"] == trip_id),
        key=lambda s: s["sequence"],
    )


def peak_case_load(stops):
    """§3.4: the trailer leaves loaded with every delivery case."""
    running = sum(int(s.get("cases") or 0) for s in stops if s["stop_type"] == "DELIVERY")
    peak = running
    for s in stops:
        st = s["stop_type"]
        c = int(s.get("cases") or 0)
        if st == "DELIVERY":
            running -= c
        elif st in ("VENDOR_PICKUP", "THIRD_PARTY_PICKUP"):
            running += c
        elif st == "DROP_OFF":
            running -= c
        if running > peak:
            peak = running
    return peak


def recompute_trip_aggregates(trip):
    """§3.4: re-derive every aggregate by walking the stops in sequence order."""
    stops = trip_stops(trip["id"])
    trip["stop_count"] = len(stops)
    trip["planned_end_at"] = stops[-1]["scheduled_departure_at"] if stops else None
    trip["total_miles"] = sum(int(s["miles_from_prev"]) for s in stops)
    trip["loaded_miles"] = sum(
        int(s["miles_from_prev"]) for s in stops if s["segment_loaded"]
    )
    trip["empty_miles"] = trip["total_miles"] - trip["loaded_miles"]
    trip["planned_drive_minutes"] = sum(int(s["drive_minutes_from_prev"]) for s in stops)
    trip["planned_service_minutes"] = sum(int(s["service_minutes"]) for s in stops)
    trip["planned_break_minutes"] = (
        MANDATORY_BREAK_MINUTES
        if trip["planned_drive_minutes"] > BREAK_TRIGGER_DRIVE_MINUTES
        else 0
    )
    trip["planned_duty_minutes"] = (
        trip["planned_drive_minutes"]
        + trip["planned_service_minutes"]
        + trip["planned_break_minutes"]
    )
    trip["planned_delivery_cases"] = sum(
        int(s.get("cases") or 0) for s in stops if s["stop_type"] == "DELIVERY"
    )
    trip["peak_case_load"] = peak_case_load(stops)
    return trip


# ===========================================================================
# hos_feasibility
# ===========================================================================
def check_hos(driver, trip):
    """§3.5: drive, then duty, then weekly -- all strict comparisons."""
    projected_drive = int(driver["drive_minutes_used_today"]) + int(
        trip["planned_drive_minutes"]
    )
    projected_duty = int(driver["duty_minutes_used_today"]) + int(
        trip["planned_duty_minutes"]
    )
    projected_weekly = int(driver["weekly_on_duty_minutes"]) + int(
        trip["planned_duty_minutes"]
    )
    if projected_drive > MAX_DAILY_DRIVE_MINUTES:
        fail("ERR_HOS_DRIVE_LIMIT")
    if projected_duty > MAX_DAILY_DUTY_MINUTES:
        fail("ERR_HOS_DUTY_LIMIT")
    if projected_weekly > MAX_WEEKLY_ON_DUTY_MINUTES:
        fail("ERR_HOS_WEEKLY_LIMIT")


# ===========================================================================
# driver_trip_pay (two variants)
# ===========================================================================
PAID_STOP_TYPES = ("DELIVERY", "VENDOR_PICKUP", "THIRD_PARTY_PICKUP")


def compute_driver_pay(trip, variant, plan):
    """§3.8: mileage, activity, hourly, bonus, subtotal, guarantee."""
    stops = trip_stops(trip["id"])
    if variant == "FINAL_SETTLEMENT":
        counted = ("COMPLETED",)
    else:
        counted = ("PLANNED", "ARRIVED", "COMPLETED")

    mileage_cents = rhu_cents(
        dec(trip["total_miles"]) * dec(plan["mileage_cents_per_mile"])
    )

    paid_stops = sum(
        1 for s in stops if s["status"] in counted and s["stop_type"] in PAID_STOP_TYPES
    )
    drop_hooks = sum(
        1 for s in stops if s["status"] in counted and s["stop_type"] == "DROP_OFF"
    )
    activity_cents = rhu_cents(
        dec(paid_stops) * dec(plan["stop_cents_per_stop"])
        + dec(drop_hooks) * dec(plan["drop_hook_cents"])
    )

    if variant == "FINAL_SETTLEMENT":
        duty_basis = int(trip["actual_duty_minutes"] or 0)
    else:
        duty_basis = int(trip["planned_duty_minutes"] or 0)
    detention = duty_basis - int(trip["planned_duty_minutes"] or 0) - DETENTION_GRACE_MINUTES
    if detention < 0:
        detention = 0
    hourly_cents = rhu_cents(dec(detention) * dec(plan["hourly_cents_per_minute"]))

    offer = db.offers.get(trip.get("backhaul_offer_id")) if trip.get("backhaul_offer_id") else None
    if offer is not None and offer["status"] == "ACCEPTED":
        bonus_cents = rhu_cents(
            (dec(mileage_cents) + dec(activity_cents)) * dec(plan["backhaul_bonus_pct"])
        )
    else:
        bonus_cents = 0

    subtotal_cents = mileage_cents + activity_cents + hourly_cents + bonus_cents
    floor_cents = int(plan["minimum_daily_cents"])
    guarantee_makeup_cents = floor_cents - subtotal_cents if floor_cents > subtotal_cents else 0
    gross_cents = subtotal_cents + guarantee_makeup_cents
    return {
        "mileage_cents": mileage_cents,
        "activity_cents": activity_cents,
        "hourly_cents": hourly_cents,
        "bonus_cents": bonus_cents,
        "subtotal_cents": subtotal_cents,
        "guarantee_makeup_cents": guarantee_makeup_cents,
        "gross_cents": gross_cents,
    }


# ===========================================================================
# backhaul_contribution_margin
# ===========================================================================
def compute_offer_margin(offer):
    """§3.6: eleven steps; the tier is keyed on the PRE-commission ratio."""
    incremental_miles = int(offer["deadhead_miles"]) + int(offer["loaded_miles"])
    line_haul = rhu_cents(dec(incremental_miles) * dec(LINEHAUL_VARIABLE_CENTS_PER_MILE))
    handling = rhu_cents(dec(offer["cases"]) * dec(HANDLING_CENTS_PER_CASE))
    if offer["temperature_mode"] == "REFRIGERATED":
        reefer = rhu_cents(dec(offer["loaded_miles"]) * dec(REEFER_SURCHARGE_CENTS_PER_MILE))
    else:
        reefer = 0
    variable_cost = line_haul + handling + reefer
    revenue = int(offer["revenue_cents"])
    gross_margin = revenue - variable_cost
    tier_margin_pct = rhu4(gross_margin, revenue)
    rate = (
        COMMISSION_RATE_HIGH
        if dec(tier_margin_pct) >= COMMISSION_TIER_THRESHOLD_PCT
        else COMMISSION_RATE_LOW
    )
    commission = rhu_cents(dec(revenue) * rate)
    contribution_margin = gross_margin - commission
    offer["variable_cost_cents"] = variable_cost
    offer["gross_margin_cents"] = gross_margin
    offer["tier_margin_pct"] = tier_margin_pct
    offer["commission_cents"] = commission
    offer["contribution_margin_cents"] = contribution_margin
    offer["margin_pct"] = rhu4(contribution_margin, revenue)
    return offer


# ===========================================================================
# domicile_balance_index
# ===========================================================================
def recompute_domicile_counters(domicile):
    domicile["assigned_driver_count"] = sum(
        1
        for d in db.drivers.values()
        if d["domicile_id"] == domicile["id"] and d["status"] == "ACTIVE"
    )
    domicile["balance_index"] = rhu4(
        domicile["assigned_driver_count"], domicile["driver_headcount_target"]
    )
    return domicile


def borrow_allowed(source, target):
    return (
        dec(source["balance_index"]) >= REBALANCE_SOURCE_MIN_INDEX
        and dec(target["balance_index"]) < REBALANCE_TARGET_MAX_INDEX
    )


# ===========================================================================
# driver_safety_score
# ===========================================================================
def recompute_driver_safety(driver):
    """§3.9: open points, score, hold. Returns the recomputed row."""
    open_points = sum(
        int(e["penalty_points"])
        for e in db.events.values()
        if e["driver_id"] == driver["id"] and not e["coached"]
    )
    driver["open_penalty_points"] = open_points
    score = 100 - open_points
    driver["safety_score"] = score if score > SAFETY_SCORE_FLOOR else SAFETY_SCORE_FLOOR
    driver["coaching_hold"] = driver["safety_score"] < COACHING_HOLD_SCORE_THRESHOLD
    return driver


# ===========================================================================
# dock_hours_and_window_fit / dock_capacity_occupancy
# ===========================================================================
def minute_of_day(dt):
    return dt.hour * 60 + dt.minute


def check_dock_hours(stop, store):
    arr = D(stop["scheduled_arrival_at"])
    dep = D(stop["scheduled_departure_at"])
    if arr.date() != dep.date():
        fail("ERR_DOCK_HOURS_VIOLATION")
    if minute_of_day(arr) < int(store["dock_open_minute"]):
        fail("ERR_DOCK_HOURS_VIOLATION")
    if minute_of_day(dep) > int(store["dock_close_minute"]):
        fail("ERR_DOCK_HOURS_VIOLATION")


def check_window_fit(stop, order):
    arr = D(stop["scheduled_arrival_at"])
    dep = D(stop["scheduled_departure_at"])
    if arr < D(order["requested_window_start"]) or dep > D(order["requested_window_end"]):
        fail("ERR_DELIVERY_WINDOW_VIOLATION")


def check_dock_capacity(stop, store):
    """§3.5: half-open, strict overlap, aggregate against dock_count."""
    arr = D(stop["scheduled_arrival_at"])
    dep = D(stop["scheduled_departure_at"])
    occupants = 0
    for other in db.stops.values():
        if other["id"] == stop["id"]:
            continue
        if other["stop_type"] != "DELIVERY" or other.get("store_id") != store["id"]:
            continue
        if other["status"] not in ("PLANNED", "ARRIVED"):
            continue
        parent = db.trips.get(other["trip_id"])
        if parent is None or parent["plan_status"] not in COMMITTED_PLAN_STATUSES:
            continue
        o_arr = D(other["scheduled_arrival_at"])
        o_dep = D(other["scheduled_departure_at"])
        if o_arr < dep and o_dep > arr:
            occupants += 1
    if occupants + 1 > int(store["dock_count"]):
        fail("ERR_DOCK_CAPACITY_EXCEEDED")


# ===========================================================================
# asset_maintenance_conflict / driver_rest_gap
# ===========================================================================
def trip_buffered_interval(trip):
    start = D(trip["planned_start_at"])
    end = D(trip.get("planned_end_at"))
    if start is None or end is None:
        return None
    return (
        start - timedelta(minutes=SHOP_BUFFER_MINUTES),
        end + timedelta(minutes=SHOP_BUFFER_MINUTES),
    )


def _closed_overlap(a_start, a_end, b_start, b_end):
    """Both edges inclusive: a touch is a collision."""
    return a_start <= b_end and a_end >= b_start


def check_asset_maintenance_conflict(trip, asset_field, asset_id):
    interval = trip_buffered_interval(trip)
    if interval is None:
        return
    t_start, t_end = interval
    for wo in db.work_orders.values():
        if wo.get(asset_field) != asset_id:
            continue
        if wo["status"] not in OPEN_WORK_ORDER_STATUSES:
            continue
        if _closed_overlap(
            t_start, t_end, D(wo["window_start_at"]), D(wo["window_end_at"])
        ):
            fail("ERR_ASSET_MAINTENANCE_CONFLICT")


def check_work_order_conflict(asset_field, asset_id, w_start, w_end, exclude_id=None):
    """§3.2: the reverse direction -- a shop window against committed trips."""
    for trip in db.trips.values():
        if trip.get(asset_field) != asset_id:
            continue
        if trip["plan_status"] not in COMMITTED_PLAN_STATUSES:
            continue
        interval = trip_buffered_interval(trip)
        if interval is None:
            continue
        t_start, t_end = interval
        if _closed_overlap(w_start, w_end, t_start, t_end):
            fail("ERR_ASSET_MAINTENANCE_CONFLICT")


def check_driver_rest_gap(driver_id, trip):
    """§3.5: minimum ten hours between consecutive duty periods."""
    start = D(trip["planned_start_at"])
    end = D(trip.get("planned_end_at"))
    if start is None or end is None:
        return
    for other in db.trips.values():
        if other["id"] == trip["id"] or other.get("driver_id") != driver_id:
            continue
        if other["plan_status"] not in COMMITTED_PLAN_STATUSES:
            continue
        o_start = D(other["planned_start_at"])
        o_end = D(other.get("planned_end_at"))
        if o_start is None or o_end is None:
            continue
        if start >= o_end:
            gap = (start - o_end).total_seconds() / 60.0
        elif o_start >= end:
            gap = (o_start - end).total_seconds() / 60.0
        else:
            gap = 0
        if gap < MIN_REST_MINUTES:
            fail("ERR_DRIVER_REST_GAP")


# ===========================================================================
# pm_due_projection
# ===========================================================================
def project_pm(tractor):
    """§3.7: at most one auto-generated PM order per tractor at a time."""
    if tractor["pm_hold"]:
        return None
    if int(tractor["miles_since_pm"]) < int(tractor["pm_interval_miles"]):
        return None
    service_type = (
        "PM_B"
        if int(tractor["miles_since_pm"]) >= 2 * int(tractor["pm_interval_miles"])
        else "PM_A"
    )
    now = db.clock
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    wo = new_row(
        {
            "asset_kind": "TRACTOR",
            "tractor_id": tractor["id"],
            "trailer_id": None,
            "service_type": service_type,
            "window_start_at": fmt_instant(midnight),
            "window_end_at": fmt_instant(midnight + timedelta(minutes=PM_WINDOW_MINUTES)),
            "status": "SCHEDULED",
            "deferral_count": 0,
            "auto_generated": True,
        }
    )
    db.work_orders[wo["id"]] = wo
    tractor["pm_hold"] = True
    return wo


# ===========================================================================
# Pay-plan pin (§3.8) and statement accrual
# ===========================================================================
PLAN_RATE_FIELDS = (
    "mileage_cents_per_mile",
    "stop_cents_per_stop",
    "drop_hook_cents",
    "hourly_cents_per_minute",
    "minimum_daily_cents",
    "backhaul_bonus_pct",
)


def plan_snapshot(plan):
    snap = {f: plan[f] for f in PLAN_RATE_FIELDS}
    snap["id"] = plan["id"]
    snap["version"] = plan["version"]
    return snap


def pin_pay_plan(trip, driver):
    """§3.5: the pin is taken at plan time and never refreshed."""
    plan = db.pay_plans.get(driver["pay_plan_id"])
    if plan is None:
        fail("ERR_PAY_PLAN_NOT_FOUND")
    trip["pinned_pay_plan_id"] = plan["id"]
    trip["pinned_pay_plan_version"] = plan["version"]
    trip["_pinned_plan_snapshot"] = plan_snapshot(plan)
    return plan


def pay_context(trip):
    """The plan a pay computation must read.

    Once a trip has been committed that is the plan named by pinned_pay_plan_id
    at the version recorded in pinned_pay_plan_version, and never the driver's
    current plan; while a trip is still DRAFT the plan is the driver's own.
    """
    pinned_id = trip.get("pinned_pay_plan_id")
    if pinned_id is not None:
        if pinned_id not in db.pay_plans:
            return None
        snap = trip.get("_pinned_plan_snapshot")
        if snap is None:
            plan = db.pay_plans[pinned_id]
            snap = plan_snapshot(plan)
        return snap
    driver = db.drivers.get(trip.get("driver_id")) if trip.get("driver_id") else None
    if driver is None:
        return None
    plan = db.pay_plans.get(driver["pay_plan_id"])
    if plan is None:
        return None
    return plan_snapshot(plan)


def accrue_statement(trip, snap, breakdown):
    """§3.8: the statement born from close-out or re-accrual."""
    row = new_row({
        "driver_id": trip.get("driver_id"),
        "trip_id": trip["id"],
        "pay_plan_id": snap["id"],
        "pay_plan_version": snap["version"],
        "variant": "FINAL_SETTLEMENT",
        "mileage_cents": breakdown["mileage_cents"],
        "activity_cents": breakdown["activity_cents"],
        "hourly_cents": breakdown["hourly_cents"],
        "bonus_cents": breakdown["bonus_cents"],
        "guarantee_makeup_cents": breakdown["guarantee_makeup_cents"],
        "gross_cents": breakdown["gross_cents"],
        "status": "ACCRUED",
        "settlement_reference": None,
    })
    db.statements[row["id"]] = row
    # The created statement raises both money ledgers.
    driver = db.drivers.get(row["driver_id"]) if row["driver_id"] else None
    if driver is not None:
        driver["ytd_gross_cents"] = int(driver["ytd_gross_cents"]) + int(row["gross_cents"])
        bump(driver)
        domicile = db.domiciles.get(driver["domicile_id"])
        if domicile is not None:
            domicile["accrued_pay_cents"] = int(domicile["accrued_pay_cents"]) + int(
                row["gross_cents"]
            )
            bump(domicile)
    return row
