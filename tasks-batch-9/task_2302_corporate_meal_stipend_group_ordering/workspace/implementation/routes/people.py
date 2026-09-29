"""Employees, their imputed-income records, and the restaurant catalogue."""

from flask import Blueprint

import calc
from envelope import list_response, object_response
from errors import ApiError
from helpers import (auth, f_bool, f_enum, f_int, f_number, f_string, get_body,
                     pagination, q_enum, q_month, q_str)
from routes.common import paginate, require
from store import base_row, db, public, touch

bp = Blueprint("people", __name__)

EMPLOYEE_STATUSES = ("ACTIVE", "INACTIVE")
RESTAURANT_STATUSES = ("ELIGIBLE", "SUSPENDED")
IMPUTED_STATUSES = ("ACCRUING", "LOCKED", "EXPORTED")


# --------------------------------------------------------------------------
# employees
# --------------------------------------------------------------------------
@bp.post("/employees")
def create_employee():
    auth("ProgramAdmin")
    body = get_body()
    program_id = f_string(body, "program_id")
    group_id = f_string(body, "group_id")
    full_name = f_string(body, "full_name")
    email = f_string(body, "email")
    card_on_file = f_bool(body, "personal_card_on_file", required=False, default=False)

    program = require(db.meal_programs, program_id, "ERR_MEAL_PROGRAM_NOT_FOUND")
    group = require(db.employee_groups, group_id, "ERR_EMPLOYEE_GROUP_NOT_FOUND")

    if group["program_id"] != program["id"]:
        raise ApiError("ERR_PROGRAM_SCOPE_MISMATCH",
                       "The employee group belongs to another meal program.")

    for existing in db.employees.values():
        if existing["program_id"] == program["id"] and existing["email"].lower() == email.lower():
            raise ApiError("ERR_DUPLICATE_NAME",
                           "An employee with email '%s' already exists in this program." % email)

    row = base_row()
    row.update({
        "program_id": program["id"],
        "group_id": group["id"],
        "full_name": full_name,
        "email": email,
        "personal_card_on_file": card_on_file,
        "tax_treatment_flag": "NONE",
        "ytd_imputed_cents": 0,
        "status": "ACTIVE",
    })
    db.employees[row["id"]] = row
    return object_response(public(row), 201)


@bp.get("/employees/<employee_id>")
def read_employee(employee_id):
    user_id, role = auth("ProgramAdmin", "BenefitsController", "Employee")
    employee = db.employees.get(employee_id)
    if employee is not None and role == "Employee" and employee["id"] != user_id:
        raise ApiError("ERR_FORBIDDEN_RESOURCE", "An employee may only read their own record.")
    if employee is None:
        raise ApiError("ERR_EMPLOYEE_NOT_FOUND")
    return object_response(public(employee))


@bp.get("/employees")
def list_employees():
    auth("PlatformAdmin", "ProgramAdmin", "BenefitsController")
    limit, offset = pagination()
    program_id = q_str("program_id")
    group_id = q_str("group_id")
    status = q_enum("status", EMPLOYEE_STATUSES)
    rows = list(db.employees.values())
    if program_id is not None:
        rows = [e for e in rows if e["program_id"] == program_id]
    if group_id is not None:
        rows = [e for e in rows if e["group_id"] == group_id]
    if status is not None:
        rows = [e for e in rows if e["status"] == status]
    items, total = paginate(rows, limit, offset)
    return list_response(items, limit, offset, total)


@bp.post("/employees/<employee_id>/deactivate")
def deactivate_employee(employee_id):
    auth("ProgramAdmin")
    employee = require(db.employees, employee_id, "ERR_EMPLOYEE_NOT_FOUND")

    if employee["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE",
                       "An employee in status %s cannot be deactivated." % employee["status"])

    for order in db.orders.values():
        if (order["employee_id"] == employee["id"]
                and order["fulfillment_status"] in ("PLACED", "CONFIRMED")):
            raise ApiError("ERR_EMPLOYEE_HAS_OPEN_ORDERS",
                           "The employee still holds a placed or confirmed order.")

    employee["status"] = "INACTIVE"
    touch(employee)

    for period in db.benefit_periods.values():
        if period["employee_id"] == employee["id"] and period["status"] == "OPEN":
            period["status"] = "GRACE"
            touch(period)

    calc.recompute_program_rollups(employee["program_id"])
    return object_response(public(employee))


@bp.get("/employees/<employee_id>/imputed-income-records")
def list_imputed(employee_id):
    auth("ProgramAdmin", "BenefitsController", "Employee")
    limit, offset = pagination()
    tax_month = q_month("tax_month")
    employee = require(db.employees, employee_id, "ERR_EMPLOYEE_NOT_FOUND")
    rows = [r for r in db.imputed_records.values() if r["employee_id"] == employee["id"]]
    if tax_month is not None:
        rows = [r for r in rows if r["tax_month"] == tax_month]
    items, total = paginate(rows, limit, offset)
    return list_response(items, limit, offset, total)


# --------------------------------------------------------------------------
# restaurants
# --------------------------------------------------------------------------
@bp.post("/restaurants")
def create_restaurant():
    auth("PlatformAdmin")
    body = get_body()
    name = f_string(body, "name")
    cuisine = f_string(body, "cuisine")
    if cuisine != cuisine.upper():
        raise ApiError("ERR_INVALID_REQUEST", "Field 'cuisine' must be uppercase.")
    grid_x = f_number(body, "grid_x_km")
    grid_y = f_number(body, "grid_y_km")
    radius = f_number(body, "delivery_radius_km", exclusive_min=0)
    max_concurrent = f_int(body, "max_concurrent_group_deliveries", required=False,
                           default=1, minimum=1)

    row = base_row()
    row.update({
        "name": name,
        "cuisine": cuisine,
        "grid_x_km": grid_x,
        "grid_y_km": grid_y,
        "delivery_radius_km": radius,
        "max_concurrent_group_deliveries": max_concurrent,
        "status": "ELIGIBLE",
    })
    db.restaurants[row["id"]] = row
    return object_response(public(row), 201)


@bp.get("/restaurants/<restaurant_id>")
def read_restaurant(restaurant_id):
    auth("PlatformAdmin", "ProgramAdmin", "BenefitsController", "Employee", "Restaurant")
    restaurant = require(db.restaurants, restaurant_id, "ERR_RESTAURANT_NOT_FOUND")
    return object_response(public(restaurant))


@bp.patch("/restaurants/<restaurant_id>")
def patch_restaurant(restaurant_id):
    auth("PlatformAdmin")
    body = get_body()
    status = f_enum(body, "status", RESTAURANT_STATUSES)
    restaurant = require(db.restaurants, restaurant_id, "ERR_RESTAURANT_NOT_FOUND")
    if restaurant["status"] == status:
        raise ApiError("ERR_INVALID_STATE",
                       "The restaurant is already %s." % status)
    restaurant["status"] = status
    touch(restaurant)
    return object_response(public(restaurant))
