"""Logical clock, meal programs and their child collections."""

from flask import Blueprint

import calc
from envelope import list_response, object_response
from errors import ApiError
from helpers import (auth, f_enum, f_month, f_number, f_int, f_str_array_upper,
                     f_string, get_body, pagination, parse_dt, q_month, q_enum, q_str)
from routes.common import paginate, require
from store import base_row, db, fmt_dt, public, touch

bp = Blueprint("programs", __name__)

TAXABLE_METHODS = ("DE_MINIMIS_EXCLUSION", "FULL_INCLUSION")
ROLLOVER_POLICIES = ("NONE", "CAPPED_PCT", "FULL")
FORECAST_BASES = ("COMMITMENT", "RUN_RATE")
EXPORT_FORMATS = ("CSV_EXPENSE_REPORT", "PAYROLL_IMPUTED_FEED")
EXPORT_STATUSES = ("GENERATED", "ACKNOWLEDGED", "FAILED")


# --------------------------------------------------------------------------
# logical clock
# --------------------------------------------------------------------------
@bp.post("/_clock/set_current_utc")
def set_clock():
    auth("PlatformAdmin", "ProgramAdmin")
    body = get_body()
    if "now" not in body or body["now"] is None:
        raise ApiError("ERR_INVALID_REQUEST", "Missing required field 'now'.")
    moment = parse_dt(body["now"], "now")
    db.now = moment
    return object_response({"now": fmt_dt(moment)})


# --------------------------------------------------------------------------
# meal programs
# --------------------------------------------------------------------------
@bp.post("/meal-programs")
def create_program():
    auth("PlatformAdmin")
    body = get_body()
    employer_name = f_string(body, "employer_name")
    billing_account_ref = f_string(body, "billing_account_ref")
    eligible_cuisines = f_str_array_upper(body, "eligible_cuisines")
    max_radius = f_number(body, "max_delivery_radius_km", required=False, default=8.0,
                          exclusive_min=0, maximum=50.0)
    taxable_method = f_enum(body, "taxable_benefit_method", TAXABLE_METHODS,
                            required=False, default="DE_MINIMIS_EXCLUSION")
    rollover_policy = f_enum(body, "rollover_policy", ROLLOVER_POLICIES,
                             required=False, default="CAPPED_PCT")
    rollover_cap_pct = f_number(body, "rollover_cap_pct", required=False, default=0.25,
                                minimum=0, maximum=1)
    forecast_basis = f_enum(body, "forecast_basis", FORECAST_BASES,
                            required=False, default="COMMITMENT")

    row = base_row()
    row.update({
        "employer_name": employer_name,
        "billing_account_ref": billing_account_ref,
        "max_delivery_radius_km": max_radius,
        "eligible_cuisines": eligible_cuisines,
        "taxable_benefit_method": taxable_method,
        "rollover_policy": rollover_policy,
        "rollover_cap_pct": rollover_cap_pct,
        "forecast_basis": forecast_basis,
        "program_spent_cents": 0,
        "program_reserved_cents": 0,
        "mtd_employer_captured_cents": 0,
    })
    db.meal_programs[row["id"]] = row
    return object_response(public(row), 201)


@bp.get("/meal-programs/<program_id>")
def read_program(program_id):
    auth("PlatformAdmin", "ProgramAdmin", "BenefitsController")
    program = require(db.meal_programs, program_id, "ERR_MEAL_PROGRAM_NOT_FOUND")
    calc.recompute_program_rollups(program["id"])
    return object_response(public(program))


@bp.patch("/meal-programs/<program_id>")
def patch_program(program_id):
    auth("PlatformAdmin")
    body = get_body()
    updates = {}
    if "taxable_benefit_method" in body:
        updates["taxable_benefit_method"] = f_enum(body, "taxable_benefit_method",
                                                   TAXABLE_METHODS)
    if "forecast_basis" in body:
        updates["forecast_basis"] = f_enum(body, "forecast_basis", FORECAST_BASES)
    if "rollover_policy" in body:
        updates["rollover_policy"] = f_enum(body, "rollover_policy", ROLLOVER_POLICIES)
    if "rollover_cap_pct" in body:
        updates["rollover_cap_pct"] = f_number(body, "rollover_cap_pct", minimum=0, maximum=1)
    if "max_delivery_radius_km" in body:
        updates["max_delivery_radius_km"] = f_number(body, "max_delivery_radius_km",
                                                     exclusive_min=0, maximum=50.0)
    if "eligible_cuisines" in body:
        updates["eligible_cuisines"] = f_str_array_upper(body, "eligible_cuisines")

    program = require(db.meal_programs, program_id, "ERR_MEAL_PROGRAM_NOT_FOUND")
    program.update(updates)
    touch(program)
    calc.recompute_program_rollups(program["id"])
    return object_response(public(program))


# --------------------------------------------------------------------------
# employee groups
# --------------------------------------------------------------------------
@bp.post("/meal-programs/<program_id>/employee-groups")
def create_group(program_id):
    auth("ProgramAdmin")
    body = get_body()
    # PRD §2.11 — the parent must exist before any child-level validation runs
    program = require(db.meal_programs, program_id, "ERR_MEAL_PROGRAM_NOT_FOUND")

    name = f_string(body, "name")
    headcount = f_int(body, "headcount_planned", minimum=1)

    for group in db.employee_groups.values():
        if group["program_id"] == program["id"] and group["name"].lower() == name.lower():
            raise ApiError("ERR_DUPLICATE_NAME",
                           "An employee group named '%s' already exists in this program." % name)

    row = base_row()
    row.update({
        "program_id": program["id"],
        "name": name,
        "headcount_planned": headcount,
        "active_rule_count": 0,
        "_activation_count": 0,
    })
    db.employee_groups[row["id"]] = row
    return object_response(public(row), 201)


@bp.get("/meal-programs/<program_id>/employee-groups")
def list_groups(program_id):
    auth("PlatformAdmin", "ProgramAdmin", "BenefitsController")
    limit, offset = pagination()
    program = require(db.meal_programs, program_id, "ERR_MEAL_PROGRAM_NOT_FOUND")
    rows = [g for g in db.employee_groups.values() if g["program_id"] == program["id"]]
    items, total = paginate(rows, limit, offset)
    return list_response(items, limit, offset, total)


# --------------------------------------------------------------------------
# delivery locations
# --------------------------------------------------------------------------
@bp.post("/meal-programs/<program_id>/delivery-locations")
def create_location(program_id):
    auth("ProgramAdmin")
    body = get_body()
    # PRD §2.11 — the parent must exist before any child-level validation runs
    program = require(db.meal_programs, program_id, "ERR_MEAL_PROGRAM_NOT_FOUND")

    label = f_string(body, "label")
    grid_x = f_number(body, "grid_x_km")
    grid_y = f_number(body, "grid_y_km")
    buffer_minutes = f_int(body, "dock_buffer_minutes", required=False, default=15,
                           minimum=0, maximum=120)

    for loc in db.delivery_locations.values():
        if loc["program_id"] == program["id"] and loc["label"].lower() == label.lower():
            raise ApiError("ERR_DUPLICATE_NAME",
                           "A delivery location labelled '%s' already exists." % label)

    row = base_row()
    row.update({
        "program_id": program["id"],
        "label": label,
        "grid_x_km": grid_x,
        "grid_y_km": grid_y,
        "dock_buffer_minutes": buffer_minutes,
    })
    db.delivery_locations[row["id"]] = row
    return object_response(public(row), 201)


@bp.get("/meal-programs/<program_id>/delivery-locations")
def list_locations(program_id):
    auth("PlatformAdmin", "ProgramAdmin", "BenefitsController", "Employee")
    limit, offset = pagination()
    program = require(db.meal_programs, program_id, "ERR_MEAL_PROGRAM_NOT_FOUND")
    rows = [l for l in db.delivery_locations.values() if l["program_id"] == program["id"]]
    items, total = paginate(rows, limit, offset)
    return list_response(items, limit, offset, total)


# --------------------------------------------------------------------------
# eligible restaurants
# --------------------------------------------------------------------------
@bp.get("/meal-programs/<program_id>/eligible-restaurants")
def eligible_restaurants(program_id):
    auth("ProgramAdmin", "BenefitsController", "Employee")
    limit, offset = pagination()
    location_id = q_str("delivery_location_id")
    if location_id is None:
        raise ApiError("ERR_INVALID_REQUEST", "Missing required query parameter 'delivery_location_id'.")

    program = require(db.meal_programs, program_id, "ERR_MEAL_PROGRAM_NOT_FOUND")
    location = require(db.delivery_locations, location_id, "ERR_DELIVERY_LOCATION_NOT_FOUND")
    if location["program_id"] != program["id"]:
        raise ApiError("ERR_PROGRAM_SCOPE_MISMATCH",
                       "The delivery location belongs to another meal program.")

    cuisines = set(program["eligible_cuisines"])
    matches = []
    for restaurant in db.restaurants.values():
        if restaurant["status"] != "ELIGIBLE":
            continue
        if restaurant["cuisine"] not in cuisines:
            continue
        distance = calc.distance_km(restaurant, location)
        if distance > calc.effective_limit_km(program, restaurant):
            continue
        matches.append((distance, restaurant["name"], restaurant))

    matches.sort(key=lambda item: (item[0], item[1]))
    total = len(matches)
    page = matches[offset:offset + limit]
    items = [public(entry[2]) for entry in page]
    return list_response(items, limit, offset, total)


# --------------------------------------------------------------------------
# forecast
# --------------------------------------------------------------------------
@bp.get("/meal-programs/<program_id>/forecast")
def forecast(program_id):
    auth("ProgramAdmin", "BenefitsController")
    program = require(db.meal_programs, program_id, "ERR_MEAL_PROGRAM_NOT_FOUND")
    return object_response(calc.program_cost_forecast(program))


# --------------------------------------------------------------------------
# expense exports
# --------------------------------------------------------------------------
@bp.post("/meal-programs/<program_id>/expense-exports")
def create_export(program_id):
    auth("BenefitsController")
    body = get_body()
    # PRD §2.11 — the parent must exist before any child-level validation runs
    program = require(db.meal_programs, program_id, "ERR_MEAL_PROGRAM_NOT_FOUND")

    tax_month = f_month(body, "tax_month")
    export_format = f_enum(body, "format", EXPORT_FORMATS)

    bucket = [o for o in calc.program_orders(program["id"])
              if o["fulfillment_status"] == "DELIVERED"
              and o["settlement_status"] != "VOIDED"
              and o["tax_month"] == tax_month]

    receipt_count = len(bucket)
    employer_gross = sum(o["employer_covered_cents"] for o in bucket)
    employer_refund = sum(o["employer_refunded_cents"] for o in bucket)
    admin_total = sum(o["admin_fee_cents"] for o in bucket)
    imputed_total = sum(o["taxable_cents"] for o in bucket)
    status = "FAILED" if receipt_count == 0 else "GENERATED"

    row = base_row()
    row.update({
        "program_id": program["id"],
        "tax_month": tax_month,
        "format": export_format,
        "receipt_count": receipt_count,
        "employer_gross_cents": employer_gross,
        "employer_refund_cents": employer_refund,
        "net_of_refunds_cents": employer_gross - employer_refund,
        "admin_fee_total_cents": admin_total,
        "imputed_total_cents": imputed_total,
        "status": status,
    })
    db.expense_exports[row["id"]] = row

    if export_format == "PAYROLL_IMPUTED_FEED" and status == "GENERATED":
        program_employee_ids = {e["id"] for e in db.employees.values()
                                if e["program_id"] == program["id"]}
        for record in db.imputed_records.values():
            if (record["tax_month"] == tax_month
                    and record["status"] == "LOCKED"
                    and record["employee_id"] in program_employee_ids):
                record["status"] = "EXPORTED"
                touch(record)

    return object_response(public(row), 201)


@bp.get("/meal-programs/<program_id>/expense-exports")
def list_exports(program_id):
    auth("ProgramAdmin", "BenefitsController")
    limit, offset = pagination()
    tax_month = q_month("tax_month")
    status = q_enum("status", EXPORT_STATUSES)
    program = require(db.meal_programs, program_id, "ERR_MEAL_PROGRAM_NOT_FOUND")
    rows = [e for e in db.expense_exports.values() if e["program_id"] == program["id"]]
    if tax_month is not None:
        rows = [e for e in rows if e["tax_month"] == tax_month]
    if status is not None:
        rows = [e for e in rows if e["status"] == status]
    items, total = paginate(rows, limit, offset)
    return list_response(items, limit, offset, total)


@bp.post("/expense-exports/<export_id>/acknowledge")
def acknowledge_export(export_id):
    auth("BenefitsController")
    export = require(db.expense_exports, export_id, "ERR_EXPENSE_EXPORT_NOT_FOUND")
    if export["status"] != "GENERATED":
        raise ApiError("ERR_INVALID_STATE",
                       "An export in status %s cannot be acknowledged." % export["status"])
    export["status"] = "ACKNOWLEDGED"
    touch(export)
    return object_response(public(export))
