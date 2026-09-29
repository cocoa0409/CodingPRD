"""Trips and trip stops -- PRD §3.4, §3.5, §3.7 and the pay reads of §3.8."""

from flask import Blueprint, g

import calc
from core import (
    ALL_ROLES, D, apply_filters, auth, bump, fail, must_exist, new_row, out,
    out_many, page, respond, respond_list, unique_code, db,
)
import validate as v

bp = Blueprint("trips", __name__)

READ_ROLES = ALL_ROLES
PLAN_STATUSES = ("DRAFT", "PLANNED", "DISPATCHED", "IN_PROGRESS", "COMPLETED", "CANCELLED")
SETTLEMENT_STATUSES = ("PENDING", "ACCRUED", "SETTLED", "DISPUTED", "ADJUSTED")
STOP_TYPES = ("DELIVERY", "VENDOR_PICKUP", "THIRD_PARTY_PICKUP", "DROP_OFF", "FUEL")
STOP_STATUSES = ("PLANNED", "ARRIVED", "COMPLETED", "SKIPPED")
LINKABLE_PLAN_STATUSES = ("DRAFT", "PLANNED", "DISPATCHED", "IN_PROGRESS")
TERMINAL_STOP_STATUSES = ("COMPLETED", "SKIPPED")


def _driver_scope(trip):
    """§2.1: a Driver may only act on its own trip."""
    if g.role == "Driver" and trip.get("driver_id") != g.user_id:
        fail("ERR_DRIVER_SCOPE_VIOLATION")


# ===========================================================================
# Trips
# ===========================================================================
@bp.post("/trips")
def create_trip():
    auth(["FleetPlanner"])
    data = v.body()
    v.fk(data, "domicile_id", "domiciles")
    trip_code = v.rstr(data, "trip_code", 1, 16)
    domicile_id = v.rref(data, "domicile_id")
    planned_start_at = v.rinstant(data, "planned_start_at")
    unique_code(db.trips, "trip_code", trip_code)
    row = new_row({
        "trip_code": trip_code,
        "domicile_id": domicile_id,
        "planned_start_at": planned_start_at,
        "driver_id": None,
        "tractor_id": None,
        "trailer_id": None,
        "backhaul_offer_id": None,
        "pinned_pay_plan_id": None,
        "pinned_pay_plan_version": None,
        "plan_status": "DRAFT",
        "settlement_status": "PENDING",
        "stop_count": 0,
        "planned_end_at": None,
        "total_miles": 0,
        "loaded_miles": 0,
        "empty_miles": 0,
        "planned_drive_minutes": 0,
        "planned_service_minutes": 0,
        "planned_break_minutes": 0,
        "planned_duty_minutes": 0,
        "planned_delivery_cases": 0,
        "peak_case_load": 0,
        "delivered_cases": 0,
        "actual_drive_minutes": None,
        "actual_duty_minutes": None,
        "planned_pay_cents": 0,
        "driver_pay_cents": 0,
        "backhaul_credit_cents": 0,
        "created_by_user_id": g.user_id,
    })
    db.trips[row["id"]] = row
    return respond(out(row), 201)


@bp.get("/trips/<trip_id>")
def get_trip(trip_id):
    auth(READ_ROLES)
    return respond(out(must_exist("trips", trip_id)))


@bp.get("/trips")
def list_trips():
    auth(READ_ROLES)
    limit, offset = v.page_window()
    rows = apply_filters(list(db.trips.values()), [
        ("domicile_id", v.qstr("domicile_id")),
        ("driver_id", v.qstr("driver_id")),
        ("tractor_id", v.qstr("tractor_id")),
        ("trailer_id", v.qstr("trailer_id")),
        ("backhaul_offer_id", v.qstr("backhaul_offer_id")),
        ("pinned_pay_plan_id", v.qstr("pinned_pay_plan_id")),
        ("plan_status", v.qenum("plan_status", PLAN_STATUSES)),
        ("settlement_status", v.qenum("settlement_status", SETTLEMENT_STATUSES)),
    ])
    return page(rows, limit, offset)


# ===========================================================================
# Trip stops: append, list, delete
# ===========================================================================
@bp.post("/trips/<trip_id>/stops")
def append_stop(trip_id):
    auth(["FleetPlanner"])
    trip = must_exist("trips", trip_id)
    data = v.body()
    # level 5: body references
    store = v.fk(data, "store_id", "stores")
    order = v.fk(data, "replenishment_order_id", "orders")
    # level 6: the referenced order must not already sit on another trip
    if order is not None:
        for other in db.stops.values():
            if other.get("replenishment_order_id") == order["id"] and other["trip_id"] != trip["id"]:
                fail("ERR_PARENT_MISMATCH")
    # level 7: shape
    sequence = v.rint(data, "sequence", 1)
    stop_type = v.renum(data, "stop_type", STOP_TYPES)
    store_id = v.oref(data, "store_id")
    order_id = v.oref(data, "replenishment_order_id")
    arrival = v.rinstant(data, "scheduled_arrival_at")
    departure = v.rinstant(data, "scheduled_departure_at")
    v.window_order(arrival, departure, "scheduled_arrival_at", "scheduled_departure_at")
    drive_minutes = v.rint(data, "drive_minutes_from_prev", 0)
    miles = v.rint(data, "miles_from_prev", 0)
    segment_loaded = v.rbool(data, "segment_loaded")
    cases = v.oint(data, "cases", 0, 0)
    # level 8: the trip's own state
    if trip["plan_status"] != "DRAFT":
        fail("ERR_TRIP_NOT_DRAFT")
    # level 13: structural completeness of the stop
    if stop_type == "DELIVERY":
        if store_id is None or order_id is None:
            fail("ERR_REFERENTIAL_INCOMPLETE", "A DELIVERY stop requires store_id and replenishment_order_id.")
    else:
        if store_id is not None or order_id is not None:
            fail("ERR_REFERENTIAL_INCOMPLETE", "Only a DELIVERY stop may carry store_id or replenishment_order_id.")
    # level 14: sequence ordering
    existing = calc.trip_stops(trip["id"])
    highest = existing[-1]["sequence"] if existing else 0
    if sequence != highest + 1:
        fail("ERR_STOP_SEQUENCE_DISORDER")
    if existing and D(arrival) < D(existing[-1]["scheduled_departure_at"]):
        fail("ERR_STOP_SEQUENCE_DISORDER")

    row = new_row({
        "trip_id": trip["id"],
        "sequence": sequence,
        "stop_type": stop_type,
        "store_id": store_id,
        "replenishment_order_id": order_id,
        "scheduled_arrival_at": arrival,
        "scheduled_departure_at": departure,
        "drive_minutes_from_prev": drive_minutes,
        "miles_from_prev": miles,
        "segment_loaded": segment_loaded,
        "cases": cases,
        "service_minutes": 0,
        "status": "PLANNED",
        "actual_arrival_at": None,
        "actual_departure_at": None,
    })
    row["service_minutes"] = calc.stop_service_minutes(row)
    db.stops[row["id"]] = row
    calc.recompute_trip_aggregates(trip)
    bump(trip)
    return respond(out(row), 201)


@bp.get("/trips/<trip_id>/stops")
def list_trip_stops(trip_id):
    auth(READ_ROLES)
    trip = must_exist("trips", trip_id)
    limit, offset = v.page_window()
    ordered = calc.trip_stops(trip["id"])
    total = len(ordered)
    window = ordered[offset: offset + limit]
    return respond_list(out_many(window), limit, offset, total)


@bp.delete("/trips/<trip_id>/stops/<trip_stop_id>")
def delete_stop(trip_id, trip_stop_id):
    auth(["FleetPlanner"])
    trip = must_exist("trips", trip_id)
    stop = must_exist("stops", trip_stop_id)
    if stop["trip_id"] != trip["id"]:
        fail("ERR_PARENT_MISMATCH")
    del db.stops[stop["id"]]
    for index, remaining in enumerate(calc.trip_stops(trip["id"]), start=1):
        if remaining["sequence"] != index:
            remaining["sequence"] = index
            bump(remaining)
    calc.recompute_trip_aggregates(trip)
    bump(trip)
    return respond(out(trip))


# ===========================================================================
# The plan gate (§3.5)
# ===========================================================================
@bp.post("/trips/<trip_id>/plan")
def plan_trip(trip_id):
    auth(["FleetPlanner"])
    trip = must_exist("trips", trip_id)
    v.body()
    # level 8
    if trip["plan_status"] != "DRAFT":
        fail("ERR_TRIP_NOT_DRAFT")
    calc.recompute_trip_aggregates(trip)
    stops = calc.trip_stops(trip["id"])
    delivery_stops = [s for s in stops if s["stop_type"] == "DELIVERY"]
    # level 10: cross-entity state
    for s in delivery_stops:
        store = db.stores.get(s.get("store_id"))
        if store is None or store["status"] != "ACTIVE":
            fail("ERR_STORE_SUSPENDED")
    for s in delivery_stops:
        order = db.orders.get(s.get("replenishment_order_id"))
        if order is None or order["status"] != "UNSCHEDULED":
            fail("ERR_ORDER_NOT_SCHEDULABLE")
    # level 12: hours of service
    driver = db.drivers.get(trip.get("driver_id")) if trip.get("driver_id") else None
    if driver is not None:
        calc.check_hos(driver, trip)
    # level 13: structural completeness
    if not (trip.get("driver_id") and trip.get("tractor_id") and trip.get("trailer_id")):
        fail("ERR_TRIP_NOT_STAFFED")
    if not delivery_stops:
        fail("ERR_TRIP_HAS_NO_STOPS")
    for index, s in enumerate(stops, start=1):
        if s["sequence"] != index:
            fail("ERR_REFERENTIAL_INCOMPLETE", "Stop sequences must run contiguously from 1.")
    # level 14: interval geometry, in the fixed within-level order
    for s in delivery_stops:
        calc.check_dock_hours(s, db.stores[s["store_id"]])
    for s in delivery_stops:
        calc.check_window_fit(s, db.orders[s["replenishment_order_id"]])
    for s in delivery_stops:
        calc.check_dock_capacity(s, db.stores[s["store_id"]])
    # level 15: capacity
    trailer = db.trailers.get(trip["trailer_id"])
    if trailer is not None and int(trip["peak_case_load"]) > int(trailer["capacity_cases"]):
        fail("ERR_TRAILER_CAPACITY_EXCEEDED")

    # --- side effects ------------------------------------------------------
    plan = calc.pin_pay_plan(trip, driver)
    snap = calc.plan_snapshot(plan)
    breakdown = calc.compute_driver_pay(trip, "PLANNED_ACCRUAL", snap)
    trip["planned_pay_cents"] = breakdown["gross_cents"]
    for s in delivery_stops:
        order = db.orders[s["replenishment_order_id"]]
        order["status"] = "SCHEDULED"
        bump(order)
        store = db.stores[order["store_id"]]
        store["open_scheduled_cases"] = int(store["open_scheduled_cases"]) + int(order["cases"])
        bump(store)
    trip["plan_status"] = "PLANNED"
    bump(trip)
    return respond(out(trip))


# ===========================================================================
# Assignment (§3.5)
# ===========================================================================
@bp.post("/trips/<trip_id>/assignments")
def assign_trip(trip_id):
    auth(["TransportManager"])
    trip = must_exist("trips", trip_id)
    data = v.body()
    driver = v.fk(data, "driver_id", "drivers")
    tractor = v.fk(data, "tractor_id", "tractors")
    trailer = v.fk(data, "trailer_id", "trailers")
    v.rref(data, "driver_id")
    v.rref(data, "tractor_id")
    v.rref(data, "trailer_id")
    # level 8
    if trip["plan_status"] not in LINKABLE_PLAN_STATUSES:
        fail("ERR_INVALID_STATE_TRANSITION")
    # level 10: cross-entity state (an asset this trip already holds is free)
    def _available(asset, field):
        if asset["status"] == "AVAILABLE":
            return True
        return trip.get(field) == asset["id"] and asset["status"] == "ASSIGNED"

    if not _available(tractor, "tractor_id"):
        fail("ERR_ASSET_NOT_AVAILABLE")
    if not _available(trailer, "trailer_id"):
        fail("ERR_ASSET_NOT_AVAILABLE")
    if tractor["pm_hold"]:
        fail("ERR_TRACTOR_PM_HOLD")
    if driver["status"] != "ACTIVE":
        fail("ERR_DRIVER_NOT_ACTIVE")
    # level 11: driver eligibility
    if driver["coaching_hold"]:
        fail("ERR_DRIVER_COACHING_HOLD")
    if int(driver["safety_score"]) < calc.MIN_BID_SAFETY_SCORE:
        fail("ERR_DRIVER_SAFETY_INELIGIBLE")
    if tractor["domicile_id"] != trip["domicile_id"]:
        fail("ERR_DOMICILE_MISMATCH")
    if trailer["domicile_id"] != trip["domicile_id"]:
        fail("ERR_DOMICILE_MISMATCH")
    if driver["domicile_id"] != trip["domicile_id"]:
        source = db.domiciles.get(driver["domicile_id"])
        target = db.domiciles.get(trip["domicile_id"])
        if source is None or target is None or not calc.borrow_allowed(source, target):
            fail("ERR_DOMICILE_MISMATCH")
    # level 12: hours of service
    calc.check_hos(driver, trip)
    # level 14: maintenance conflict, then rest gap
    calc.check_asset_maintenance_conflict(trip, "tractor_id", tractor["id"])
    calc.check_asset_maintenance_conflict(trip, "trailer_id", trailer["id"])
    calc.check_driver_rest_gap(driver["id"], trip)
    # level 15: capacity, then temperature
    if int(trip["peak_case_load"]) > int(trailer["capacity_cases"]):
        fail("ERR_TRAILER_CAPACITY_EXCEEDED")
    for s in calc.trip_stops(trip["id"]):
        if s["stop_type"] != "DELIVERY":
            continue
        order = db.orders.get(s.get("replenishment_order_id"))
        if order is not None and order["temperature_mode"] == "REFRIGERATED":
            if trailer["trailer_type"] != "REEFER":
                fail("ERR_TEMPERATURE_MODE_MISMATCH")

    # --- side effects: release before claim -------------------------------
    old_tractor = db.tractors.get(trip.get("tractor_id")) if trip.get("tractor_id") else None
    old_trailer = db.trailers.get(trip.get("trailer_id")) if trip.get("trailer_id") else None
    if old_tractor is not None and old_tractor["id"] != tractor["id"]:
        old_tractor["status"] = "AVAILABLE"
        bump(old_tractor)
    if old_trailer is not None and old_trailer["id"] != trailer["id"]:
        old_trailer["status"] = "AVAILABLE"
        bump(old_trailer)
    if tractor["status"] != "ASSIGNED":
        tractor["status"] = "ASSIGNED"
        bump(tractor)
    if trailer["status"] != "ASSIGNED":
        trailer["status"] = "ASSIGNED"
        bump(trailer)
    trip["driver_id"] = driver["id"]
    trip["tractor_id"] = tractor["id"]
    trip["trailer_id"] = trailer["id"]
    bump(trip)
    return respond(out(trip))


# ===========================================================================
# Backhaul linkage (§3.6)
# ===========================================================================
@bp.post("/trips/<trip_id>/backhaul-assignments")
def link_backhaul(trip_id):
    auth(["TransportManager"])
    trip = must_exist("trips", trip_id)
    data = v.body()
    offer = v.fk(data, "backhaul_offer_id", "offers")
    v.rref(data, "backhaul_offer_id")
    expected = v.rint(data, "expected_trip_version")
    # level 8
    if trip["plan_status"] not in LINKABLE_PLAN_STATUSES:
        fail("ERR_INVALID_STATE_TRANSITION")
    # level 9
    if expected != trip["version"]:
        fail("ERR_STALE_TRIP_VERSION")
    # level 10
    if offer["status"] in ("REJECTED", "WITHDRAWN", "EXPIRED"):
        fail("ERR_OFFER_NOT_ACCEPTED")
    # level 15
    for other in db.trips.values():
        if other["id"] != trip["id"] and other.get("backhaul_offer_id") == offer["id"]:
            fail("ERR_BACKHAUL_ALREADY_LINKED")

    previous = db.offers.get(trip.get("backhaul_offer_id")) if trip.get("backhaul_offer_id") else None
    if previous is not None and previous["id"] != offer["id"]:
        if previous["status"] == "ACCEPTED":
            previous["status"] = "PROPOSED"
        bump(previous)
    trip["backhaul_offer_id"] = offer["id"]
    trip["backhaul_credit_cents"] = (
        int(offer["contribution_margin_cents"]) if offer["status"] == "ACCEPTED" else 0
    )
    bump(trip)
    return respond(out(trip))


# ===========================================================================
# Dispatch, close-out and cancellation (§3.7)
# ===========================================================================
@bp.post("/trips/<trip_id>/dispatch")
def dispatch_trip(trip_id):
    auth(["TransportManager"])
    trip = must_exist("trips", trip_id)
    v.body()
    if trip["plan_status"] != "PLANNED":
        fail("ERR_INVALID_STATE_TRANSITION")
    if not (trip.get("driver_id") and trip.get("tractor_id") and trip.get("trailer_id")):
        fail("ERR_REFERENTIAL_INCOMPLETE", "A dispatched trip needs a driver, a tractor and a trailer.")
    driver = db.drivers.get(trip["driver_id"])
    tractor = db.tractors.get(trip["tractor_id"])
    if driver is None or driver["status"] != "ACTIVE":
        fail("ERR_DRIVER_NOT_ACTIVE")
    if driver["coaching_hold"]:
        fail("ERR_DRIVER_COACHING_HOLD")
    if tractor is None or tractor["status"] != "ASSIGNED" or tractor["pm_hold"]:
        fail("ERR_TRACTOR_PM_HOLD")
    calc.check_hos(driver, trip)
    driver["hos_status"] = "ON_DUTY"
    bump(driver)
    trip["plan_status"] = "DISPATCHED"
    bump(trip)
    return respond(out(trip))


@bp.post("/trips/<trip_id>/complete")
def complete_trip(trip_id):
    auth(["Driver", "TransportManager"])
    trip = must_exist("trips", trip_id)
    data = v.body()
    actual_drive = v.rint(data, "actual_drive_minutes", 0)
    actual_duty = v.rint(data, "actual_duty_minutes", 0)
    if trip["plan_status"] != "IN_PROGRESS":
        fail("ERR_INVALID_STATE_TRANSITION")
    _driver_scope(trip)
    stops = calc.trip_stops(trip["id"])
    for s in stops:
        if s["status"] not in TERMINAL_STOP_STATUSES:
            fail("ERR_INVALID_STATE_TRANSITION", "Every stop must be COMPLETED or SKIPPED.")

    trip["actual_drive_minutes"] = actual_drive
    trip["actual_duty_minutes"] = actual_duty
    trip["delivered_cases"] = sum(
        int(s.get("cases") or 0)
        for s in stops
        if s["stop_type"] == "DELIVERY" and s["status"] == "COMPLETED"
    )
    # order-delivery cascade
    for s in stops:
        if s["stop_type"] != "DELIVERY" or s["status"] != "COMPLETED":
            continue
        order = db.orders.get(s.get("replenishment_order_id"))
        if order is None or order["status"] != "SCHEDULED":
            continue
        order["status"] = "DELIVERED"
        bump(order)
        store = db.stores.get(order["store_id"])
        if store is not None:
            store["open_scheduled_cases"] = int(store["open_scheduled_cases"]) - int(order["cases"])
            store["delivered_cases_total"] = int(store["delivered_cases_total"]) + int(order["cases"])
            bump(store)
    # driver counters
    driver = db.drivers.get(trip.get("driver_id")) if trip.get("driver_id") else None
    if driver is not None:
        driver["drive_minutes_used_today"] = int(driver["drive_minutes_used_today"]) + actual_drive
        driver["duty_minutes_used_today"] = int(driver["duty_minutes_used_today"]) + actual_duty
        driver["weekly_on_duty_minutes"] = int(driver["weekly_on_duty_minutes"]) + actual_duty
        driver["hos_status"] = "AVAILABLE"
        bump(driver)
    # odometer and preventive-maintenance projection
    tractor = db.tractors.get(trip.get("tractor_id")) if trip.get("tractor_id") else None
    if tractor is not None:
        tractor["odometer_miles"] = int(tractor["odometer_miles"]) + int(trip["total_miles"])
        tractor["miles_since_pm"] = int(tractor["odometer_miles"]) - int(
            tractor["pm_last_service_odometer"]
        )
        calc.project_pm(tractor)
        tractor["status"] = "AVAILABLE"
        bump(tractor)
    trailer = db.trailers.get(trip.get("trailer_id")) if trip.get("trailer_id") else None
    if trailer is not None:
        trailer["status"] = "AVAILABLE"
        bump(trailer)
    trip["plan_status"] = "COMPLETED"
    # payroll dimension PENDING -> ACCRUED
    snap = calc.pay_context(trip)
    if snap is not None:
        breakdown = calc.compute_driver_pay(trip, "FINAL_SETTLEMENT", snap)
        trip["driver_pay_cents"] = breakdown["gross_cents"]
        offer = db.offers.get(trip.get("backhaul_offer_id")) if trip.get("backhaul_offer_id") else None
        trip["backhaul_credit_cents"] = (
            int(offer["contribution_margin_cents"])
            if offer is not None and offer["status"] == "ACCEPTED"
            else 0
        )
        trip["settlement_status"] = "ACCRUED"
        calc.accrue_statement(trip, snap, breakdown)
    bump(trip)
    return respond(out(trip))


@bp.post("/trips/<trip_id>/cancel")
def cancel_trip(trip_id):
    auth(["FleetPlanner", "TransportManager"])
    trip = must_exist("trips", trip_id)
    data = v.body()
    reason = v.ostr(data, "reason_code")
    origin = trip["plan_status"]
    if origin not in ("DRAFT", "PLANNED", "DISPATCHED"):
        fail("ERR_INVALID_STATE_TRANSITION")

    skipped = []
    for s in calc.trip_stops(trip["id"]):
        if s["status"] in ("PLANNED", "ARRIVED"):
            s["status"] = "SKIPPED"
            bump(s)
            skipped.append(s)
    if origin != "DRAFT":
        for s in skipped:
            order = db.orders.get(s.get("replenishment_order_id"))
            if order is None or order["status"] != "SCHEDULED":
                continue
            order["status"] = "UNSCHEDULED"
            bump(order)
            store = db.stores.get(order["store_id"])
            if store is not None:
                store["open_scheduled_cases"] = int(store["open_scheduled_cases"]) - int(order["cases"])
                bump(store)
    tractor = db.tractors.get(trip.get("tractor_id")) if trip.get("tractor_id") else None
    if tractor is not None:
        tractor["status"] = "AVAILABLE"
        bump(tractor)
    trailer = db.trailers.get(trip.get("trailer_id")) if trip.get("trailer_id") else None
    if trailer is not None:
        trailer["status"] = "AVAILABLE"
        bump(trailer)
    if origin != "DRAFT":
        driver = db.drivers.get(trip.get("driver_id")) if trip.get("driver_id") else None
        if driver is not None:
            driver["hos_status"] = "AVAILABLE"
            bump(driver)
    trip["driver_id"] = None
    trip["tractor_id"] = None
    trip["trailer_id"] = None
    if origin != "DRAFT":
        offer = db.offers.get(trip.get("backhaul_offer_id")) if trip.get("backhaul_offer_id") else None
        if offer is not None:
            if offer["status"] == "ACCEPTED":
                offer["status"] = "PROPOSED"
                offer["margin_exception_approved"] = False
                bump(offer)
            trip["backhaul_offer_id"] = None
            trip["backhaul_credit_cents"] = 0
        trip["pinned_pay_plan_id"] = None
        trip["pinned_pay_plan_version"] = None
        trip["_pinned_plan_snapshot"] = None
        trip["planned_pay_cents"] = 0
    trip["plan_status"] = "CANCELLED"
    trip["_reason_code"] = reason
    bump(trip)
    return respond(out(trip))


# ===========================================================================
# Pay reads and the payroll dimension (§3.8)
# ===========================================================================
PAY_VARIANTS = ("PLANNED_ACCRUAL", "FINAL_SETTLEMENT")


@bp.get("/trips/<trip_id>/pay-preview")
def pay_preview(trip_id):
    auth(["PayrollAnalyst", "TransportManager"])
    trip = must_exist("trips", trip_id)
    variant = v.qrequired_enum("variant", PAY_VARIANTS)
    snap = calc.pay_context(trip)
    if snap is None:
        fail("ERR_REFERENTIAL_INCOMPLETE", "No pay plan is resolvable for this trip.")
    breakdown = calc.compute_driver_pay(trip, variant, snap)
    payload = {
        "variant": variant,
        "pay_plan_id": snap["id"],
        "pay_plan_version": snap["version"],
    }
    payload.update(breakdown)
    return respond(payload)


@bp.post("/trips/<trip_id>/re-accrue")
def re_accrue(trip_id):
    auth(["PayrollAnalyst"])
    trip = must_exist("trips", trip_id)
    data = v.body()
    actual_drive = v.rint(data, "actual_drive_minutes", 0)
    actual_duty = v.rint(data, "actual_duty_minutes", 0)
    if trip["settlement_status"] not in ("DISPUTED", "ADJUSTED"):
        fail("ERR_INVALID_STATE_TRANSITION")
    if trip["plan_status"] != "COMPLETED":
        fail("ERR_INVALID_STATE_TRANSITION")
    for st in db.statements.values():
        if st["trip_id"] == trip["id"] and st["status"] in ("ACCRUED", "SETTLED"):
            fail("ERR_INVALID_STATE_TRANSITION", "A statement is still live on this trip.")
    pinned_id = trip.get("pinned_pay_plan_id")
    if pinned_id is None or pinned_id not in db.pay_plans:
        fail("ERR_REFERENTIAL_INCOMPLETE", "The pinned pay plan no longer resolves.")
    snap = calc.pay_context(trip)
    trip["actual_drive_minutes"] = actual_drive
    trip["actual_duty_minutes"] = actual_duty
    breakdown = calc.compute_driver_pay(trip, "FINAL_SETTLEMENT", snap)
    trip["driver_pay_cents"] = breakdown["gross_cents"]
    calc.accrue_statement(trip, snap, breakdown)
    trip["settlement_status"] = "ACCRUED"
    bump(trip)
    return respond(out(trip))


@bp.post("/trips/<trip_id>/settlement-dispute")
def settlement_dispute(trip_id):
    auth(["PayrollAnalyst", "Driver"])
    trip = must_exist("trips", trip_id)
    data = v.body()
    note = v.ostr(data, "dispute_note")
    if trip["settlement_status"] not in ("ACCRUED", "SETTLED"):
        fail("ERR_INVALID_STATE_TRANSITION")
    _driver_scope(trip)
    trip["settlement_status"] = "DISPUTED"
    trip["_dispute_note"] = note
    bump(trip)
    return respond(out(trip))


# ===========================================================================
# The flat trip-stop surface (§3.7)
# ===========================================================================
@bp.get("/trip-stops/<trip_stop_id>")
def get_stop(trip_stop_id):
    auth(READ_ROLES)
    return respond(out(must_exist("stops", trip_stop_id)))


@bp.get("/trip-stops")
def list_stops():
    auth(READ_ROLES)
    limit, offset = v.page_window()
    rows = apply_filters(list(db.stops.values()), [
        ("trip_id", v.qstr("trip_id")),
        ("store_id", v.qstr("store_id")),
        ("replenishment_order_id", v.qstr("replenishment_order_id")),
        ("stop_type", v.qenum("stop_type", STOP_TYPES)),
        ("status", v.qenum("status", STOP_STATUSES)),
    ])
    return page(rows, limit, offset)


@bp.post("/trip-stops/<trip_stop_id>/arrive")
def arrive_stop(trip_stop_id):
    auth(["Driver", "TransportManager"])
    stop = must_exist("stops", trip_stop_id)
    data = v.body()
    actual_arrival_at = v.oinstant(data, "actual_arrival_at")
    trip = db.trips.get(stop["trip_id"])
    if trip is None or trip["plan_status"] not in ("DISPATCHED", "IN_PROGRESS"):
        fail("ERR_INVALID_STATE_TRANSITION")
    if stop["status"] != "PLANNED":
        fail("ERR_INVALID_STATE_TRANSITION")
    _driver_scope(trip)
    for other in calc.trip_stops(trip["id"]):
        if other["sequence"] < stop["sequence"] and other["status"] not in TERMINAL_STOP_STATUSES:
            fail("ERR_STOP_SEQUENCE_CONFLICT")
    stop["status"] = "ARRIVED"
    if actual_arrival_at is not None:
        stop["actual_arrival_at"] = actual_arrival_at
    bump(stop)
    if trip["plan_status"] == "DISPATCHED":
        trip["plan_status"] = "IN_PROGRESS"
        bump(trip)
    return respond(out(stop))


@bp.post("/trip-stops/<trip_stop_id>/complete")
def complete_stop(trip_stop_id):
    auth(["Driver", "TransportManager"])
    stop = must_exist("stops", trip_stop_id)
    data = v.body()
    actual_departure_at = v.oinstant(data, "actual_departure_at")
    cases_handled = v.oint(data, "cases_handled", None, 0)
    trip = db.trips.get(stop["trip_id"])
    if stop["status"] != "ARRIVED":
        fail("ERR_INVALID_STATE_TRANSITION")
    if trip is not None:
        _driver_scope(trip)
    stop["status"] = "COMPLETED"
    if actual_departure_at is not None:
        stop["actual_departure_at"] = actual_departure_at
    if cases_handled is not None:
        stop["cases"] = cases_handled
        stop["service_minutes"] = calc.stop_service_minutes(stop)
    bump(stop)
    if cases_handled is not None and trip is not None:
        calc.recompute_trip_aggregates(trip)
        bump(trip)
    return respond(out(stop))
