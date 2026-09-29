"""Group orders: collection, locking, reopening, consolidated submission."""

from datetime import timedelta

from flask import Blueprint

import calc
from envelope import list_response, object_response
from errors import ApiError
from helpers import (auth, f_datetime, f_int, f_string, get_body, pagination,
                     q_enum, q_str)
from routes.common import paginate, require
from routes.orders import cancel_order_row, price_order
from store import base_row, db, fmt_dt, public, touch

bp = Blueprint("groups", __name__)

GROUP_STATUSES = ("COLLECTING", "LOCKED", "SUBMITTED", "CANCELLED")


def _organizer_gate(group_order, user_id):
    if group_order is not None and group_order["organizer_employee_id"] != user_id:
        raise ApiError("ERR_FORBIDDEN_RESOURCE",
                       "Only the organizer may act on this group order.")


@bp.post("/group-orders")
def create_group_order():
    user_id, _role = auth("Employee")
    body = get_body()

    raw_organizer = body.get("organizer_employee_id")
    if isinstance(raw_organizer, str) and raw_organizer != user_id:
        raise ApiError("ERR_FORBIDDEN_RESOURCE",
                       "An employee may only organise their own group orders.")

    program_id = f_string(body, "program_id")
    organizer_id = f_string(body, "organizer_employee_id")
    restaurant_id = f_string(body, "restaurant_id")
    location_id = f_string(body, "delivery_location_id")
    cutoff_at = f_datetime(body, "cutoff_at")
    window_start = f_datetime(body, "window_start")
    window_end = f_datetime(body, "window_end")
    per_person_limit = f_int(body, "per_person_limit_cents", minimum=1)

    if cutoff_at >= window_start:
        raise ApiError("ERR_INVALID_REQUEST",
                       "Field 'cutoff_at' must be strictly before 'window_start'.")
    if window_end <= window_start:
        raise ApiError("ERR_INVALID_REQUEST",
                       "Field 'window_end' must be strictly after 'window_start'.")

    if organizer_id != user_id:
        raise ApiError("ERR_FORBIDDEN_RESOURCE",
                       "An employee may only organise their own group orders.")

    # rank 7 — body FK existence in declaration order
    program = require(db.meal_programs, program_id, "ERR_MEAL_PROGRAM_NOT_FOUND")
    organizer = require(db.employees, organizer_id, "ERR_EMPLOYEE_NOT_FOUND")
    restaurant = require(db.restaurants, restaurant_id, "ERR_RESTAURANT_NOT_FOUND")
    location = require(db.delivery_locations, location_id, "ERR_DELIVERY_LOCATION_NOT_FOUND")

    # rank 10
    if organizer["status"] != "ACTIVE":
        raise ApiError("ERR_EMPLOYEE_INACTIVE", "The organiser is not ACTIVE.")
    # rank 23
    if organizer["program_id"] != program["id"] or location["program_id"] != program["id"]:
        raise ApiError("ERR_PROGRAM_SCOPE_MISMATCH",
                       "The referenced rows belong to different meal programs.")
    # rank 30
    if not calc.in_range(program, restaurant, location):
        raise ApiError("ERR_RESTAURANT_OUT_OF_RANGE",
                       "The restaurant is outside the effective delivery radius.")
    # rank 31
    if restaurant["cuisine"] not in program["eligible_cuisines"]:
        raise ApiError("ERR_CUISINE_NOT_ELIGIBLE",
                       "The restaurant's cuisine is not in the program's allow-list.")

    row = base_row()
    row.update({
        "program_id": program["id"],
        "organizer_employee_id": organizer["id"],
        "restaurant_id": restaurant["id"],
        "delivery_location_id": location["id"],
        "cutoff_at": fmt_dt(cutoff_at),
        "window_start": fmt_dt(window_start),
        "window_end": fmt_dt(window_end),
        "per_person_limit_cents": per_person_limit,
        "member_order_count": 0,
        "reopen_count": 0,
        "allocated_delivery_fee_cents": 0,
        "status": "COLLECTING",
        "_cutoff_at": cutoff_at,
        "_window_start": window_start,
        "_window_end": window_end,
    })
    db.group_orders[row["id"]] = row
    return object_response(public(row), 201)


@bp.get("/group-orders/<group_order_id>")
def read_group_order(group_order_id):
    auth("ProgramAdmin", "BenefitsController", "Employee", "Restaurant")
    group_order = require(db.group_orders, group_order_id, "ERR_GROUP_ORDER_NOT_FOUND")
    return object_response(public(group_order))


@bp.get("/group-orders")
def list_group_orders():
    auth("ProgramAdmin", "BenefitsController", "Employee", "Restaurant")
    limit, offset = pagination()
    filters = {
        "program_id": q_str("program_id"),
        "organizer_employee_id": q_str("organizer_employee_id"),
        "restaurant_id": q_str("restaurant_id"),
        "delivery_location_id": q_str("delivery_location_id"),
    }
    status = q_enum("status", GROUP_STATUSES)
    rows = list(db.group_orders.values())
    for key, value in filters.items():
        if value is not None:
            rows = [g for g in rows if g.get(key) == value]
    if status is not None:
        rows = [g for g in rows if g["status"] == status]
    items, total = paginate(rows, limit, offset)
    return list_response(items, limit, offset, total)


@bp.post("/group-orders/<group_order_id>/lock")
def lock_group_order(group_order_id):
    user_id, _role = auth("Employee")
    group_order = db.group_orders.get(group_order_id)
    _organizer_gate(group_order, user_id)
    if group_order is None:
        raise ApiError("ERR_GROUP_ORDER_NOT_FOUND")

    if group_order["status"] != "COLLECTING":
        raise ApiError("ERR_INVALID_STATE",
                       "A group order in status %s cannot be locked." % group_order["status"])
    if group_order["member_order_count"] < 1:
        raise ApiError("ERR_GROUP_ORDER_EMPTY", "The group order has no member orders.")

    group_order["status"] = "LOCKED"
    touch(group_order)
    return object_response(public(group_order))


@bp.post("/group-orders/<group_order_id>/reopen")
def reopen_group_order(group_order_id):
    user_id, _role = auth("Employee")
    group_order = db.group_orders.get(group_order_id)
    _organizer_gate(group_order, user_id)
    if group_order is None:
        raise ApiError("ERR_GROUP_ORDER_NOT_FOUND")

    if group_order["status"] != "LOCKED":
        raise ApiError("ERR_INVALID_STATE",
                       "A group order in status %s cannot be reopened." % group_order["status"])
    # rank 19
    if db.now >= group_order["_cutoff_at"]:
        raise ApiError("ERR_GROUP_CUTOFF_PASSED", "The group order cutoff has passed.")
    # rank 34
    if group_order["reopen_count"] >= calc.GROUP_REOPEN_LIMIT:
        raise ApiError("ERR_REOPEN_LIMIT_EXCEEDED",
                       "The group order has reached the reopen ceiling.")

    group_order["status"] = "COLLECTING"
    group_order["reopen_count"] += 1
    touch(group_order)
    return object_response(public(group_order))


def _dock_interval(group_order, buffer_minutes):
    start = group_order["_window_start"]
    end = group_order["_window_end"] + timedelta(minutes=buffer_minutes)
    return start, end


@bp.post("/group-orders/<group_order_id>/submit")
def submit_group_order(group_order_id):
    user_id, _role = auth("Employee")
    group_order = db.group_orders.get(group_order_id)
    _organizer_gate(group_order, user_id)
    if group_order is None:
        raise ApiError("ERR_GROUP_ORDER_NOT_FOUND")

    if group_order["status"] != "LOCKED":
        raise ApiError("ERR_INVALID_STATE",
                       "A group order in status %s cannot be submitted." % group_order["status"])

    members = calc.allocation_members(group_order["id"])
    if group_order["member_order_count"] < 1 or not members:
        raise ApiError("ERR_GROUP_ORDER_EMPTY", "The group order has no member orders.")

    restaurant = require(db.restaurants, group_order["restaurant_id"], "ERR_RESTAURANT_NOT_FOUND")
    location = require(db.delivery_locations, group_order["delivery_location_id"],
                       "ERR_DELIVERY_LOCATION_NOT_FOUND")

    # rank 11
    if restaurant["status"] != "ELIGIBLE":
        raise ApiError("ERR_RESTAURANT_NOT_ELIGIBLE", "The restaurant is not ELIGIBLE.")

    buffer_minutes = location.get("dock_buffer_minutes", 0)
    my_start, my_end = _dock_interval(group_order, buffer_minutes)

    # rank 20 — dock occupancy is a CLOSED interval with a trailing buffer
    for other in db.group_orders.values():
        if other["id"] == group_order["id"] or other["status"] != "SUBMITTED":
            continue
        if other["delivery_location_id"] != group_order["delivery_location_id"]:
            continue
        other_location = db.delivery_locations.get(other["delivery_location_id"]) or {}
        other_start, other_end = _dock_interval(
            other, other_location.get("dock_buffer_minutes", 0))
        if my_start <= other_end and other_start <= my_end:
            raise ApiError("ERR_DOCK_WINDOW_CONFLICT",
                           "Another submitted group order already occupies the dock.")

    # rank 21 — restaurant capacity uses HALF-OPEN windows
    overlapping = 0
    for other in db.group_orders.values():
        if other["id"] == group_order["id"] or other["status"] != "SUBMITTED":
            continue
        if other["restaurant_id"] != group_order["restaurant_id"]:
            continue
        if (group_order["_window_start"] < other["_window_end"]
                and other["_window_start"] < group_order["_window_end"]):
            overlapping += 1
    if overlapping >= restaurant["max_concurrent_group_deliveries"]:
        raise ApiError("ERR_RESTAURANT_CAPACITY_EXCEEDED",
                       "The restaurant has no remaining concurrent group delivery capacity.")

    # allocate the consolidated delivery fee, then re-price every member order
    shares = calc.allocate_group_delivery_fee(members)
    working_available = {}
    pending = []
    for member in members:
        employee = db.employees.get(member["employee_id"])
        period = db.benefit_periods.get(member["benefit_period_id"])
        rule = db.budget_rules.get(period.get("budget_rule_id")) if period else None
        program = db.meal_programs.get(employee["program_id"]) if employee else None
        if employee is None or period is None or rule is None or program is None:
            raise ApiError("ERR_INVALID_STATE", "A member order is missing its pricing context.")

        if period["id"] not in working_available:
            working_available[period["id"]] = period["available_cents"]
        # release this order's previous reservation before re-pricing it
        effective_available = working_available[period["id"]] + member["employer_covered_cents"]

        priced = price_order(member, rule, employee, program, effective_available,
                             shares[member["id"]])
        working_available[period["id"]] = effective_available - priced["employer_covered_cents"]
        pending.append((member, period, priced, priced["employer_covered_cents"]
                        - member["employer_covered_cents"]))

    touched_periods = {}
    for member, period, priced, delta in pending:
        member.update(priced)
        touch(member)
        entry = touched_periods.setdefault(period["id"], [period, 0])
        entry[1] += delta
    for period, delta in touched_periods.values():
        period["reserved_cents"] += delta
        period["available_cents"] -= delta
        touch(period)

    group_order["status"] = "SUBMITTED"
    group_order["allocated_delivery_fee_cents"] = calc.GROUP_DELIVERY_FEE_CENTS
    touch(group_order)

    program = db.meal_programs.get(group_order["program_id"])
    if program:
        calc.recompute_program_rollups(program["id"])
    return object_response(public(group_order))


@bp.post("/group-orders/<group_order_id>/cancel")
def cancel_group_order(group_order_id):
    user_id, _role = auth("Employee")
    group_order = db.group_orders.get(group_order_id)
    _organizer_gate(group_order, user_id)
    if group_order is None:
        raise ApiError("ERR_GROUP_ORDER_NOT_FOUND")

    if group_order["status"] not in ("COLLECTING", "LOCKED"):
        raise ApiError("ERR_INVALID_STATE",
                       "A group order in status %s cannot be cancelled." % group_order["status"])

    group_order["status"] = "CANCELLED"
    touch(group_order)

    members = [o for o in db.orders.values() if o.get("group_order_id") == group_order["id"]]
    for member in sorted(members, key=lambda o: (o["created_at"], o["_seq"])):
        if member["fulfillment_status"] in ("DRAFT", "PLACED"):
            cancel_order_row(member, adjust_group=False)

    return object_response(public(group_order))
