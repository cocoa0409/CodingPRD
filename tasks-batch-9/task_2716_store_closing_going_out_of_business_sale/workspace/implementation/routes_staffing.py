"""Employee reads, the employment state machine, bonus payment and day review."""

from flask import Blueprint

import auth
import calc
import clock
import db
import helpers
import response
import serializers
import shape
from errors import ApiError

bp = Blueprint("staffing", __name__)

ACTIONS = ("GIVE_NOTICE", "TERMINATE_INVOLUNTARY", "TERMINATE_VOLUNTARY")


@bp.get("/employees/<row_id>")
def read_employee(row_id):
    user_id, role = auth.begin(
        ("StoreManager", "LiquidationConsultant", "RetailerController")
    )
    row = db.get("employees", row_id)
    auth.scope_child(user_id, role, row)
    if row is None:
        raise ApiError("ERR_EMPLOYEE_NOT_FOUND")
    return response.ok(serializers.employee(row))


@bp.post("/employees/<row_id>/employment-action")
def employment_action(row_id):
    user_id, role = auth.begin(("StoreManager", "LiquidationConsultant"))
    employee = db.get("employees", row_id)
    auth.scope_child(user_id, role, employee)
    body = shape.json_body()
    action = shape.field_enum(body, "action", ACTIONS)
    if employee is None:
        raise ApiError("ERR_EMPLOYEE_NOT_FOUND")

    status = employee["employment_status"]
    today = clock.today()
    if action == "GIVE_NOTICE":
        if status != "ACTIVE":
            raise ApiError("ERR_EMPLOYEE_STATE_INVALID")
        employee["employment_status"] = "NOTICE_GIVEN"
        employee["notice_given_date"] = today.isoformat()
        db.touch(employee)
        return response.ok(serializers.employee(employee))

    if status not in ("ACTIVE", "NOTICE_GIVEN"):
        raise ApiError("ERR_EMPLOYEE_STATE_INVALID")
    employee["employment_status"] = (
        "TERMINATED_INVOLUNTARY"
        if action == "TERMINATE_INVOLUNTARY"
        else "TERMINATED_VOLUNTARY"
    )
    employee["termination_date"] = today.isoformat()
    if employee["bonus_status"] == "PENDING":
        calc.settle_retention_bonus(employee, today)
    db.touch(employee)

    store = db.get("stores", employee["store_id"])
    if store is not None:
        engagement = helpers.engagement_of_store(store)
        if engagement is not None:
            calc.recompute_engagement(engagement)
    return response.ok(serializers.employee(employee))


@bp.post("/employees/<row_id>/pay-bonus")
def pay_bonus(row_id):
    auth.begin(("RetailerController",))
    employee = helpers.require("employees", row_id)
    store = db.get("stores", employee["store_id"])
    if store is None or store["store_status"] not in calc.CLOSED_STORE_STATUSES:
        raise ApiError("ERR_STORE_NOT_SELLING")
    if (
        employee["bonus_status"] not in ("EARNED", "PRORATED_EARNED")
        or employee["earned_bonus_cents"] <= 0
    ):
        raise ApiError("ERR_BONUS_NOT_EARNED")

    employee["bonus_status"] = "PAID"
    employee["bonus_paid_at"] = clock.iso_now()
    db.touch(employee)
    engagement = helpers.engagement_of_store(store)
    if engagement is not None:
        calc.recompute_engagement(engagement)
    return response.ok(serializers.employee(employee))


@bp.post("/sales-days/<row_id>/review")
def review_sales_day(row_id):
    user_id, _role = auth.begin(("RetailerController",))
    day = db.get("sales_days", row_id)
    auth.deny_self_decision(user_id, day, "submitted_by_user_id")
    body = shape.json_body()
    decision = shape.field_enum(body, "decision", ("POST", "REJECT"))
    shape.field_str(body, "reject_reason", required=False, default=None)
    if day is None:
        raise ApiError("ERR_SALES_DAY_NOT_FOUND")
    if day["day_status"] != "PENDING_REVIEW":
        raise ApiError("ERR_SALES_DAY_STATE_INVALID")

    store = db.get("stores", day["store_id"])
    if decision == "REJECT":
        day["day_status"] = "REJECTED"
        day["reviewed_by_user_id"] = user_id
        db.touch(day)
        return response.ok(serializers.sales_day(day))

    business_date = calc.as_date(day["business_date"])
    jurisdiction = helpers.jurisdiction_of_store(store) if store is not None else None
    if jurisdiction is not None and jurisdiction["gob_license_required"]:
        if calc.license_covers_date(store, business_date) is None:
            raise ApiError("ERR_LICENSE_NOT_ACTIVE")

    if day["original_units_sold"] > calc.units_on_floor(store["id"], "ORIGINAL"):
        raise ApiError("ERR_UNITS_EXCEED_ON_HAND")
    if day["augmentation_units_sold"] > calc.units_on_floor(store["id"], "AUGMENTATION"):
        raise ApiError("ERR_UNITS_EXCEED_ON_HAND")

    note = calc.allocate_sales_day(store, day)
    day["day_status"] = "POSTED"
    day["posted_at"] = clock.iso_now()
    day["reviewed_by_user_id"] = user_id
    day["allocation_note"] = note or None
    db.touch(day)

    calc.recompute_store(store)
    db.touch(store)
    engagement = helpers.engagement_of_store(store)
    if engagement is not None:
        calc.recompute_engagement(engagement)
    return response.ok(serializers.sales_day(day))
