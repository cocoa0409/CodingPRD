"""Benefit periods: opening, reading and closing (PRD §3.3, §3.9)."""

from flask import Blueprint

import calc
from envelope import list_response, object_response
from errors import ApiError
from helpers import (auth, f_enum, f_month, f_string, get_body, pagination,
                     q_enum, q_month, q_str)
from routes.common import group_active_rule, paginate, require
from store import base_row, db, public, touch

bp = Blueprint("periods", __name__)

PERIOD_STATUSES = ("OPEN", "GRACE", "CLOSED")
CLOSE_MODES = ("GRACE", "FINAL")


@bp.post("/benefit-periods")
def open_period():
    auth("ProgramAdmin")
    body = get_body()
    employee_id = f_string(body, "employee_id")
    period_month = f_month(body, "period_month")
    predecessor_id = f_string(body, "predecessor_period_id", required=False)

    # rank 7 — body FK existence, in declaration order
    employee = require(db.employees, employee_id, "ERR_EMPLOYEE_NOT_FOUND")
    predecessor = None
    if predecessor_id is not None:
        predecessor = require(db.benefit_periods, predecessor_id,
                              "ERR_BENEFIT_PERIOD_NOT_FOUND")

    # rank 25 — the group must have exactly one ACTIVE rule to pin
    rule = group_active_rule(employee["group_id"])
    if rule is None:
        raise ApiError("ERR_NO_ACTIVE_BUDGET_RULE",
                       "The employee's group has no ACTIVE budget rule to pin.")

    # rank 26 / 27 — predecessor eligibility
    if predecessor is not None:
        if (predecessor["employee_id"] != employee["id"]
                or predecessor["status"] != "CLOSED"
                or not (predecessor["period_month"] < period_month)):
            raise ApiError("ERR_PREDECESSOR_NOT_CLOSED",
                           "The predecessor must be a CLOSED period of the same employee "
                           "with an earlier period_month.")
        for other in db.benefit_periods.values():
            if other.get("predecessor_period_id") == predecessor["id"]:
                raise ApiError("ERR_PREDECESSOR_ALREADY_CONSUMED",
                               "The predecessor's rollover has already been carried forward.")

    # rank 28 — one period per employee per month
    for other in db.benefit_periods.values():
        if other["employee_id"] == employee["id"] and other["period_month"] == period_month:
            raise ApiError("ERR_DUPLICATE_PERIOD_MONTH",
                           "The employee already holds a period for %s." % period_month)

    rollover_in = predecessor["rollover_out_cents"] if predecessor is not None else 0
    allocated = rule["monthly_allocation_cents"] + rollover_in

    row = base_row()
    row.update({
        "employee_id": employee["id"],
        "budget_rule_id": rule["id"],
        "predecessor_period_id": predecessor["id"] if predecessor is not None else None,
        "period_month": period_month,
        "allocated_cents": allocated,
        "rollover_in_cents": rollover_in,
        "reserved_cents": 0,
        "spent_cents": 0,
        "available_cents": allocated,
        "forfeited_cents": 0,
        "rollover_out_cents": 0,
        "status": "OPEN",
    })
    db.benefit_periods[row["id"]] = row
    calc.recompute_program_rollups(employee["program_id"])
    return object_response(public(row), 201)


@bp.get("/benefit-periods/<period_id>")
def read_period(period_id):
    auth("ProgramAdmin", "BenefitsController", "Employee")
    period = require(db.benefit_periods, period_id, "ERR_BENEFIT_PERIOD_NOT_FOUND")
    return object_response(public(period))


@bp.get("/benefit-periods")
def list_periods():
    auth("ProgramAdmin", "BenefitsController", "Employee")
    limit, offset = pagination()
    employee_id = q_str("employee_id")
    budget_rule_id = q_str("budget_rule_id")
    predecessor_id = q_str("predecessor_period_id")
    status = q_enum("status", PERIOD_STATUSES)
    period_month = q_month("period_month")

    rows = list(db.benefit_periods.values())
    if employee_id is not None:
        rows = [p for p in rows if p["employee_id"] == employee_id]
    if budget_rule_id is not None:
        rows = [p for p in rows if p.get("budget_rule_id") == budget_rule_id]
    if predecessor_id is not None:
        rows = [p for p in rows if p.get("predecessor_period_id") == predecessor_id]
    if status is not None:
        rows = [p for p in rows if p["status"] == status]
    if period_month is not None:
        rows = [p for p in rows if p["period_month"] == period_month]
    items, total = paginate(rows, limit, offset)
    return list_response(items, limit, offset, total)


@bp.post("/benefit-periods/<period_id>/close")
def close_period(period_id):
    auth("ProgramAdmin")
    body = get_body()
    mode = f_enum(body, "mode", CLOSE_MODES)

    period = require(db.benefit_periods, period_id, "ERR_BENEFIT_PERIOD_NOT_FOUND")

    if mode == "GRACE":
        if period["status"] != "OPEN":
            raise ApiError("ERR_INVALID_STATE",
                           "A period in status %s cannot move to GRACE." % period["status"])
        period["status"] = "GRACE"
        touch(period)
        employee = db.employees.get(period["employee_id"])
        if employee:
            calc.recompute_program_rollups(employee["program_id"])
        return object_response(public(period))

    # mode FINAL
    if period["status"] not in ("OPEN", "GRACE"):
        raise ApiError("ERR_INVALID_STATE",
                       "A period in status %s cannot be closed." % period["status"])

    for order in db.orders.values():
        if (order["benefit_period_id"] == period["id"]
                and order["fulfillment_status"] in ("PLACED", "CONFIRMED")):
            raise ApiError("ERR_PERIOD_HAS_OPEN_ORDERS",
                           "The period still has PLACED or CONFIRMED orders.")

    employee = db.employees.get(period["employee_id"])
    program = db.meal_programs.get(employee["program_id"]) if employee else None
    if program is None:
        raise ApiError("ERR_MEAL_PROGRAM_NOT_FOUND")

    calc.period_close_rollover(period, program)
    period["status"] = "CLOSED"
    touch(period)

    for record in db.imputed_records.values():
        if (record["employee_id"] == period["employee_id"]
                and record["tax_month"] == period["period_month"]
                and record["status"] == "ACCRUING"):
            record["status"] = "LOCKED"
            touch(record)

    calc.recompute_program_rollups(program["id"])
    return object_response(public(period))
