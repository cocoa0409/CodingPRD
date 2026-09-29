"""Synchronous supply: dock delivery calls and shift plans."""

import calc
import lookup
import response
import serializers as ser
import services
import validation as v
from db import db, new_record, touch
from errors import ApiError, invalid
from flask import Blueprint, g
from middleware import (ENGINEERING_LEAD, LINE_OPERATOR, PLANT_ADMIN, PRODUCTION_PLANNER,
                        SUPPLIER_PORTAL, endpoint)

supply_bp = Blueprint("supply", __name__)

CALL_STATUSES = ("SCHEDULED", "ARRIVED_ON_TIME", "ARRIVED_LATE", "MISSED", "CANCELLED")
CANCEL_REASONS = ("PLANNER", "SUPPLIER_PROBATION", "PART_SERVICE_ONLY")
SHIFT_CODES = ("A", "B", "C")
PLAN_STATUSES = ("ACTIVE", "SUPERSEDED")
BASE_WINDOWS = {"A": (6, 14, 0), "B": (14, 22, 0), "C": (22, 6, 1)}


# =========================================================================== #
# DeliveryCall
# =========================================================================== #
@supply_bp.post("/delivery-calls")
@endpoint([PRODUCTION_PLANNER, PLANT_ADMIN])
def create_delivery_call():
    body = v.body()
    supplier_id = v.req_str(body, "supplier_id")
    part_id = v.req_str(body, "part_id")
    station_id = v.req_str(body, "station_id")
    window_start = v.req_dt(body, "window_start")
    window_end = v.req_dt(body, "window_end")
    sequenced_qty = v.req_int(body, "sequenced_qty", minimum=1)
    if window_start >= window_end:
        raise invalid("window_start must be strictly before window_end")

    supplier = lookup.must(lookup.SUPPLIER, supplier_id)
    lookup.must(lookup.PART, part_id)
    lookup.must(lookup.STATION, station_id)

    padded_start = window_start - calc.minutes(calc.DOCK_BUFFER_MINUTES)
    padded_end = window_end + calc.minutes(calc.DOCK_BUFFER_MINUTES)
    for other in db.delivery_calls.values():
        if other["station_id"] != station_id or other["status"] not in calc.LIVE_CALL_STATUSES:
            continue
        if padded_start < other["window_end"] and other["window_start"] < padded_end:
            raise ApiError("ERR_DOCK_WINDOW_CONFLICT")

    if supplier["status"] == "SUSPENDED":
        raise ApiError("ERR_SUPPLIER_NOT_APPROVED")

    call = new_record()
    call.update({
        "supplier_id": supplier_id,
        "part_id": part_id,
        "station_id": station_id,
        "window_start": window_start,
        "window_end": window_end,
        "sequenced_qty": sequenced_qty,
        "arrived_at": None,
        "lateness_minutes": None,
        "cancel_reason": None,
        "status": "SCHEDULED",
    })
    db.delivery_calls[call["id"]] = call
    return response.created(ser.delivery_call_out(call))


@supply_bp.get("/delivery-calls/<call_id>")
@endpoint([PLANT_ADMIN, PRODUCTION_PLANNER, LINE_OPERATOR, ENGINEERING_LEAD, SUPPLIER_PORTAL])
def read_delivery_call(call_id):
    call = lookup.must(lookup.DELIVERY_CALL, call_id)
    if g.role == SUPPLIER_PORTAL and call["supplier_id"] != g.user_id:
        raise ApiError("ERR_SUPPLIER_SCOPE_VIOLATION")
    return response.ok(ser.delivery_call_out(call))


@supply_bp.get("/delivery-calls")
@endpoint([PLANT_ADMIN, PRODUCTION_PLANNER, LINE_OPERATOR, ENGINEERING_LEAD, SUPPLIER_PORTAL])
def list_delivery_calls():
    limit, offset = v.pagination()
    supplier_id = v.q_str("supplier_id")
    part_id = v.q_str("part_id")
    station_id = v.q_str("station_id")
    status = v.q_enum("status", CALL_STATUSES)
    cancel_reason = v.q_enum("cancel_reason", CANCEL_REASONS)

    lookup.must_fk(lookup.SUPPLIER, supplier_id)
    lookup.must_fk(lookup.PART, part_id)
    lookup.must_fk(lookup.STATION, station_id)

    if g.role == SUPPLIER_PORTAL:
        if supplier_id is not None and supplier_id != g.user_id:
            raise ApiError("ERR_SUPPLIER_SCOPE_VIOLATION")
        supplier_id = g.user_id

    items = list(db.delivery_calls.values())
    if supplier_id is not None:
        items = [c for c in items if c["supplier_id"] == supplier_id]
    if part_id is not None:
        items = [c for c in items if c["part_id"] == part_id]
    if station_id is not None:
        items = [c for c in items if c["station_id"] == station_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    if cancel_reason is not None:
        items = [c for c in items if c["cancel_reason"] == cancel_reason]

    items.sort(key=lambda c: (c["window_start"], c["created_at"], c["_seq"]))
    window, total = v.page(items, limit, offset)
    return response.ok_list([ser.delivery_call_out(c) for c in window], limit, offset, total)


@supply_bp.post("/delivery-calls/<call_id>/record-arrival")
@endpoint([SUPPLIER_PORTAL])
def record_arrival(call_id):
    body = v.body()
    arrived_at = v.req_dt(body, "arrived_at")
    call = lookup.must(lookup.DELIVERY_CALL, call_id)
    if call["supplier_id"] != g.user_id:
        raise ApiError("ERR_SUPPLIER_SCOPE_VIOLATION")
    if call["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE")

    supplier = db.suppliers.get(call["supplier_id"])
    call["arrived_at"] = arrived_at
    if arrived_at < call["window_end"]:
        call["status"] = "ARRIVED_ON_TIME"
        call["lateness_minutes"] = 0
        if supplier is not None:
            supplier["delivered_on_time_count"] += 1
    else:
        call["status"] = "ARRIVED_LATE"
        call["lateness_minutes"] = calc.lateness_minutes(arrived_at, call["window_end"])
        if supplier is not None:
            supplier["delivered_late_count"] += 1
    touch(call)
    if supplier is not None:
        services.rescore_supplier(supplier)
    return response.ok(ser.delivery_call_out(call))


@supply_bp.post("/delivery-calls/<call_id>/cancel")
@endpoint([PRODUCTION_PLANNER, PLANT_ADMIN])
def cancel_delivery_call(call_id):
    call = lookup.must(lookup.DELIVERY_CALL, call_id)
    if call["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE")
    services.cancel_call(call, "PLANNER")
    return response.ok(ser.delivery_call_out(call))


# =========================================================================== #
# ShiftPlan
# =========================================================================== #
def _plan_window(shift_date, shift_code):
    start_hour, end_hour, day_offset = BASE_WINDOWS[shift_code]
    return (v.date_at(shift_date, start_hour),
            v.date_at(shift_date, end_hour, day_offset))


@supply_bp.post("/shift-plans")
@endpoint([PRODUCTION_PLANNER, PLANT_ADMIN])
def create_shift_plan():
    body = v.body()
    line_id = v.req_str(body, "line_id")
    shift_date = v.req_date(body, "shift_date")
    shift_code = v.req_enum(body, "shift_code", SHIFT_CODES)
    headcount = v.req_int(body, "planned_headcount", minimum=1)
    shift_start = v.req_dt(body, "shift_start")
    shift_end = v.req_dt(body, "shift_end")
    expected_version = v.req_int(body, "expected_line_version")
    overtime = v.opt_int(body, "overtime_minutes", default=0, minimum=0,
                         maximum=calc.OVERTIME_CAP_MINUTES)
    if shift_start >= shift_end:
        raise invalid("shift_start must be strictly before shift_end")
    base_start, base_end = _plan_window(shift_date, shift_code)
    if shift_start != base_start or shift_end != base_end:
        raise invalid("shift_start / shift_end must match the base window of shift_code")

    line = lookup.must(lookup.LINE, line_id)
    if expected_version != line["version"]:
        raise ApiError("ERR_STALE_LINE_VERSION")

    prior = None
    for plan in db.shift_plans.values():
        if (plan["line_id"] == line_id and plan["status"] == "ACTIVE"
                and plan["shift_date"] == shift_date and plan["shift_code"] == shift_code):
            if prior is None or (plan["created_at"], plan["id"]) > (prior["created_at"], prior["id"]):
                prior = plan

    new_end = shift_end + calc.minutes(overtime)
    for plan in db.shift_plans.values():
        if plan["line_id"] != line_id or plan["status"] != "ACTIVE":
            continue
        if prior is not None and plan["id"] == prior["id"]:
            continue
        other_end = plan["shift_end"] + calc.minutes(plan["overtime_minutes"])
        if shift_start < other_end and plan["shift_start"] < new_end:
            raise ApiError("ERR_SHIFT_WINDOW_OVERLAP")

    plan = new_record()
    plan.update({
        "line_id": line_id,
        "shift_date": shift_date,
        "shift_code": shift_code,
        "planned_headcount": headcount,
        "overtime_minutes": overtime,
        "shift_start": shift_start,
        "shift_end": shift_end,
        "unit_labor_minutes": calc.d(0),
        "changeover_minutes": calc.d(0),
        "committed_labor_minutes": 0,
        "_booked_changeover_minutes": 0,
        "status": "ACTIVE",
    })
    db.shift_plans[plan["id"]] = plan

    if prior is not None:
        prior["status"] = "SUPERSEDED"
        touch(prior)
        for slot in db.build_slots.values():
            if slot["shift_plan_id"] == prior["id"]:
                slot["shift_plan_id"] = plan["id"]
                touch(slot)
        services.recompute_plan(plan)

    touch(line)  # shift-plan creation advances the line's version
    return response.created(ser.shift_plan_out(plan))


@supply_bp.get("/shift-plans/<plan_id>")
@endpoint([PLANT_ADMIN, PRODUCTION_PLANNER, LINE_OPERATOR, ENGINEERING_LEAD])
def read_shift_plan(plan_id):
    plan = lookup.must(lookup.SHIFT_PLAN, plan_id)
    return response.ok(ser.shift_plan_out(plan))


@supply_bp.get("/lines/<line_id>/shift-plans")
@endpoint([PLANT_ADMIN, PRODUCTION_PLANNER, LINE_OPERATOR, ENGINEERING_LEAD])
def list_line_shift_plans(line_id):
    limit, offset = v.pagination()
    shift_date = v.q_str("shift_date")
    shift_code = v.q_enum("shift_code", SHIFT_CODES)
    status = v.q_enum("status", PLAN_STATUSES)
    lookup.must(lookup.LINE, line_id)

    items = [p for p in db.shift_plans.values() if p["line_id"] == line_id]
    if shift_date is not None:
        items = [p for p in items if p["shift_date"] == shift_date]
    if shift_code is not None:
        items = [p for p in items if p["shift_code"] == shift_code]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    items.sort(key=lambda p: (p["shift_start"], p["created_at"], p["_seq"]))
    window, total = v.page(items, limit, offset)
    return response.ok_list([ser.shift_plan_out(p) for p in window], limit, offset, total)
