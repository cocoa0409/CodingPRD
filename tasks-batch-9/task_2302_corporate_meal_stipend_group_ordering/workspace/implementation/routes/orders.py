"""Orders: drafting, placement, fulfilment, cancellation and the refund ledger."""

from flask import Blueprint

import calc
from envelope import list_response, object_response
from errors import ApiError
from helpers import (auth, f_int, f_lines, f_datetime, f_string, get_body,
                     pagination, q_enum, q_str)
from routes.common import paginate, require
from store import base_row, db, fmt_dt, public, touch

bp = Blueprint("orders", __name__)

FULFILLMENT_STATUSES = ("DRAFT", "PLACED", "CONFIRMED", "DELIVERED", "CANCELLED")
SETTLEMENT_STATUSES = ("UNSETTLED", "SPLIT_AUTHORIZED", "CAPTURED",
                       "PARTIALLY_REFUNDED", "REFUNDED", "VOIDED")
DIRECTIONS = ("EMPLOYER_CREDIT", "EMPLOYEE_CARD_REFUND")
REASONS = ("CLAIM_SETTLEMENT", "ORDER_VOID")


# --------------------------------------------------------------------------
# shared pricing (PRD §3.5 stages two, three and four, plus the fiscal gates)
# --------------------------------------------------------------------------
def price_order(order, rule, employee, program, available_cents, delivery_fee,
                subtotal=None, tax=None):
    if subtotal is None or tax is None:
        subtotal, tax = calc.stage_one(order["lines"])
    service_fee = calc.service_fee(subtotal, tax)
    split = calc.employer_employee_split(subtotal, tax, delivery_fee, service_fee,
                                         order["tip_cents"], rule, available_cents)

    # rank 37 -> 38 -> 39, in exactly that order
    if split["employee_card_cents"] > 0 and rule["overage_policy"] == "BLOCK":
        raise ApiError("ERR_OVERAGE_NOT_PERMITTED",
                       "The group's overage policy blocks any personal-card remainder.")
    if available_cents < split["cap_floor"]:
        raise ApiError("ERR_PERIOD_BUDGET_EXCEEDED",
                       "The benefit period has insufficient available budget.")
    if split["employee_card_cents"] > 0 and not employee["personal_card_on_file"]:
        raise ApiError("ERR_PERSONAL_CARD_REQUIRED",
                       "The employee has no personal card on file to collect the remainder.")

    admin_fee = calc.admin_fee(split["employer_covered_cents"],
                              program["mtd_employer_captured_cents"])
    priced = {
        "subtotal_cents": subtotal,
        "tax_cents": tax,
        "delivery_fee_cents": delivery_fee,
        "service_fee_cents": service_fee,
        "tip_covered_by_employer_cents": split["tip_covered_by_employer_cents"],
        "covered_base_cents": split["covered_base_cents"],
        "employer_covered_cents": split["employer_covered_cents"],
        "employee_card_cents": split["employee_card_cents"],
        "gross_total_cents": split["gross_total_cents"],
        "admin_fee_cents": admin_fee,
    }
    return priced


def order_context(order):
    """(employee, program, period, rule) for an order, raising if anything is missing."""
    employee = db.employees.get(order["employee_id"])
    if employee is None:
        raise ApiError("ERR_EMPLOYEE_NOT_FOUND")
    program = db.meal_programs.get(employee["program_id"])
    if program is None:
        raise ApiError("ERR_MEAL_PROGRAM_NOT_FOUND")
    period = db.benefit_periods.get(order["benefit_period_id"])
    if period is None:
        raise ApiError("ERR_BENEFIT_PERIOD_NOT_FOUND")
    rule = db.budget_rules.get(period.get("budget_rule_id"))
    if rule is None:
        raise ApiError("ERR_NO_ACTIVE_BUDGET_RULE",
                       "The benefit period has no pinned budget rule.")
    return employee, program, period, rule


# --------------------------------------------------------------------------
# drafting
# --------------------------------------------------------------------------
@bp.post("/orders")
def draft_order():
    user_id, _role = auth("Employee")
    body = get_body()

    # rank 3 — ownership scoping, before request-shape validation of the rest
    raw_employee_id = body.get("employee_id")
    if isinstance(raw_employee_id, str) and raw_employee_id != user_id:
        raise ApiError("ERR_FORBIDDEN_RESOURCE", "An employee may only draft their own orders.")

    employee_id = f_string(body, "employee_id")
    benefit_period_id = f_string(body, "benefit_period_id")
    restaurant_id = f_string(body, "restaurant_id")
    delivery_location_id = f_string(body, "delivery_location_id")
    requested_delivery_at = f_datetime(body, "requested_delivery_at")
    lines = f_lines(body, "lines")
    group_order_id = f_string(body, "group_order_id", required=False)
    tip_cents = f_int(body, "tip_cents", required=False, default=0, minimum=0)

    if employee_id != user_id:
        raise ApiError("ERR_FORBIDDEN_RESOURCE", "An employee may only draft their own orders.")

    # rank 7 — body FK existence in declaration order
    employee = require(db.employees, employee_id, "ERR_EMPLOYEE_NOT_FOUND")
    period = require(db.benefit_periods, benefit_period_id, "ERR_BENEFIT_PERIOD_NOT_FOUND")
    restaurant = require(db.restaurants, restaurant_id, "ERR_RESTAURANT_NOT_FOUND")
    location = require(db.delivery_locations, delivery_location_id,
                       "ERR_DELIVERY_LOCATION_NOT_FOUND")
    group_order = None
    if group_order_id is not None:
        group_order = require(db.group_orders, group_order_id, "ERR_GROUP_ORDER_NOT_FOUND")

    # rank 12 / 19 — group order gates
    if group_order is not None:
        if group_order["status"] != "COLLECTING":
            raise ApiError("ERR_GROUP_ORDER_NOT_COLLECTING",
                           "The group order is not collecting member orders.")
        if db.now >= group_order["_cutoff_at"]:
            raise ApiError("ERR_GROUP_CUTOFF_PASSED", "The group order cutoff has passed.")

    # rank 22 — the period must belong to the employee
    if period["employee_id"] != employee["id"]:
        raise ApiError("ERR_PERIOD_EMPLOYEE_MISMATCH",
                       "The benefit period belongs to another employee.")

    # rank 23 — program scope
    program_id = employee["program_id"]
    period_employee = db.employees.get(period["employee_id"])
    if (location["program_id"] != program_id
            or period_employee is None
            or period_employee["program_id"] != program_id):
        raise ApiError("ERR_PROGRAM_SCOPE_MISMATCH",
                       "The referenced rows belong to different meal programs.")

    # rank 24 — member order shape must match the group order
    if group_order is not None:
        if (group_order["restaurant_id"] != restaurant["id"]
                or group_order["delivery_location_id"] != location["id"]):
            raise ApiError("ERR_GROUP_ORDER_MISMATCH",
                           "A member order must use the group order's restaurant and dock.")

    row = base_row()
    row.update({
        "employee_id": employee["id"],
        "benefit_period_id": period["id"],
        "restaurant_id": restaurant["id"],
        "delivery_location_id": location["id"],
        "group_order_id": group_order["id"] if group_order is not None else None,
        "requested_delivery_at": fmt_dt(requested_delivery_at),
        "lines": lines,
        "tip_cents": tip_cents,
        "subtotal_cents": 0,
        "tax_cents": 0,
        "delivery_fee_cents": 0,
        "service_fee_cents": 0,
        "tip_covered_by_employer_cents": 0,
        "covered_base_cents": 0,
        "employer_covered_cents": 0,
        "employee_card_cents": 0,
        "admin_fee_cents": 0,
        "gross_total_cents": 0,
        "employer_refunded_cents": 0,
        "employee_refunded_cents": 0,
        "net_charged_cents": 0,
        "employer_net_cents": 0,
        "taxable_cents": 0,
        "tax_month": requested_delivery_at.strftime("%Y-%m"),
        "placed_at": None,
        "delivered_at": None,
        "fulfillment_status": "DRAFT",
        "settlement_status": "UNSETTLED",
        "_requested_delivery_at": requested_delivery_at,
    })
    db.orders[row["id"]] = row
    return object_response(public(row), 201)


# --------------------------------------------------------------------------
# reads
# --------------------------------------------------------------------------
@bp.get("/orders/<order_id>")
def read_order(order_id):
    user_id, role = auth("ProgramAdmin", "BenefitsController", "Employee", "Restaurant")
    order = db.orders.get(order_id)
    if order is not None:
        if role == "Employee" and order["employee_id"] != user_id:
            raise ApiError("ERR_FORBIDDEN_RESOURCE", "An employee may only read their own orders.")
        if role == "Restaurant" and order["restaurant_id"] != user_id:
            raise ApiError("ERR_FORBIDDEN_RESOURCE",
                           "A restaurant may only read orders addressed to itself.")
    if order is None:
        raise ApiError("ERR_ORDER_NOT_FOUND")
    return object_response(public(order))


@bp.get("/orders")
def list_orders():
    auth("ProgramAdmin", "BenefitsController", "Employee", "Restaurant")
    limit, offset = pagination()
    filters = {
        "employee_id": q_str("employee_id"),
        "benefit_period_id": q_str("benefit_period_id"),
        "restaurant_id": q_str("restaurant_id"),
        "delivery_location_id": q_str("delivery_location_id"),
        "group_order_id": q_str("group_order_id"),
    }
    fulfillment = q_enum("fulfillment_status", FULFILLMENT_STATUSES)
    settlement = q_enum("settlement_status", SETTLEMENT_STATUSES)

    rows = list(db.orders.values())
    for key, value in filters.items():
        if value is not None:
            rows = [o for o in rows if o.get(key) == value]
    if fulfillment is not None:
        rows = [o for o in rows if o["fulfillment_status"] == fulfillment]
    if settlement is not None:
        rows = [o for o in rows if o["settlement_status"] == settlement]
    items, total = paginate(rows, limit, offset)
    return list_response(items, limit, offset, total)


# --------------------------------------------------------------------------
# placement
# --------------------------------------------------------------------------
@bp.post("/orders/<order_id>/place")
def place_order(order_id):
    user_id, _role = auth("Employee")

    order = db.orders.get(order_id)
    if order is not None and order["employee_id"] != user_id:
        raise ApiError("ERR_FORBIDDEN_RESOURCE", "An employee may only place their own orders.")

    body = get_body()
    expected_version = f_int(body, "expected_benefit_period_version")

    if order is None:
        raise ApiError("ERR_ORDER_NOT_FOUND")

    # rank 8
    if order["fulfillment_status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE",
                       "An order in status %s cannot be placed." % order["fulfillment_status"])

    employee, program, period, rule = order_context(order)
    restaurant = require(db.restaurants, order["restaurant_id"], "ERR_RESTAURANT_NOT_FOUND")
    location = require(db.delivery_locations, order["delivery_location_id"],
                       "ERR_DELIVERY_LOCATION_NOT_FOUND")
    group_order = db.group_orders.get(order["group_order_id"]) if order.get("group_order_id") else None

    # rank 9
    if period["status"] != "OPEN":
        raise ApiError("ERR_PERIOD_NOT_OPEN",
                       "The benefit period is %s and accepts no new placement." % period["status"])
    # rank 10
    if employee["status"] != "ACTIVE":
        raise ApiError("ERR_EMPLOYEE_INACTIVE", "The ordering employee is not ACTIVE.")
    # rank 11
    if restaurant["status"] != "ELIGIBLE":
        raise ApiError("ERR_RESTAURANT_NOT_ELIGIBLE", "The restaurant is not ELIGIBLE.")
    # rank 12
    if group_order is not None and group_order["status"] != "COLLECTING":
        raise ApiError("ERR_GROUP_ORDER_NOT_COLLECTING",
                       "The group order is no longer collecting member orders.")
    # rank 13
    if expected_version != period["version"]:
        raise ApiError("ERR_STALE_PERIOD_VERSION",
                       "The benefit period has been modified since it was read.")

    requested = order["_requested_delivery_at"]
    # rank 17
    if requested.isoweekday() not in rule["eligible_weekdays"]:
        raise ApiError("ERR_OUTSIDE_ELIGIBLE_WEEKDAY",
                       "The requested delivery weekday is not eligible.")
    # rank 18
    minute_of_day = requested.hour * 60 + requested.minute
    if not (rule["eligible_window_start_minute"] <= minute_of_day
            < rule["eligible_window_end_minute"]):
        raise ApiError("ERR_OUTSIDE_ELIGIBLE_WINDOW",
                       "The requested delivery time is outside the eligible window.")
    # rank 19
    if group_order is not None and db.now >= group_order["_cutoff_at"]:
        raise ApiError("ERR_GROUP_CUTOFF_PASSED", "The group order cutoff has passed.")
    # rank 30
    if not calc.in_range(program, restaurant, location):
        raise ApiError("ERR_RESTAURANT_OUT_OF_RANGE",
                       "The restaurant is outside the effective delivery radius.")
    # rank 31
    if restaurant["cuisine"] not in program["eligible_cuisines"]:
        raise ApiError("ERR_CUISINE_NOT_ELIGIBLE",
                       "The restaurant's cuisine is not in the program's allow-list.")
    # rank 32
    requested_date = requested.date()
    live = 0
    for other in db.orders.values():
        if other["employee_id"] != employee["id"]:
            continue
        if other["fulfillment_status"] not in ("PLACED", "CONFIRMED", "DELIVERED"):
            continue
        if other["_requested_delivery_at"].date() == requested_date:
            live += 1
    if live >= rule["daily_meal_limit"]:
        raise ApiError("ERR_DAILY_MEAL_LIMIT_EXCEEDED",
                       "The employee has reached the daily meal limit for that date.")

    # stage one
    subtotal, tax = calc.stage_one(order["lines"])
    # rank 33
    if group_order is not None and (subtotal + tax) > group_order["per_person_limit_cents"]:
        raise ApiError("ERR_PER_PERSON_LIMIT_EXCEEDED",
                       "The member order exceeds the group's per-person limit.")

    delivery_fee = 0 if group_order is not None else calc.solo_delivery_fee(subtotal)
    priced = price_order(order, rule, employee, program, period["available_cents"],
                         delivery_fee, subtotal=subtotal, tax=tax)

    order.update(priced)
    order["placed_at"] = fmt_dt(db.now)
    order["fulfillment_status"] = "PLACED"
    order["settlement_status"] = "SPLIT_AUTHORIZED"
    touch(order)

    employer = priced["employer_covered_cents"]
    period["reserved_cents"] += employer
    period["available_cents"] -= employer
    touch(period)

    if group_order is not None:
        group_order["member_order_count"] = group_order.get("member_order_count", 0) + 1
        touch(group_order)

    calc.recompute_program_rollups(program["id"])
    return object_response(public(order))


# --------------------------------------------------------------------------
# confirm / deliver
# --------------------------------------------------------------------------
@bp.post("/orders/<order_id>/confirm")
def confirm_order(order_id):
    user_id, _role = auth("Restaurant")
    order = db.orders.get(order_id)
    if order is not None and order["restaurant_id"] != user_id:
        raise ApiError("ERR_FORBIDDEN_RESOURCE",
                       "A restaurant may only confirm orders addressed to itself.")
    if order is None:
        raise ApiError("ERR_ORDER_NOT_FOUND")

    if order["fulfillment_status"] != "PLACED":
        raise ApiError("ERR_INVALID_STATE",
                       "An order in status %s cannot be confirmed." % order["fulfillment_status"])

    restaurant = require(db.restaurants, order["restaurant_id"], "ERR_RESTAURANT_NOT_FOUND")
    if restaurant["status"] != "ELIGIBLE":
        raise ApiError("ERR_RESTAURANT_NOT_ELIGIBLE", "The restaurant is not ELIGIBLE.")

    order["fulfillment_status"] = "CONFIRMED"
    touch(order)
    return object_response(public(order))


@bp.post("/orders/<order_id>/deliver")
def deliver_order(order_id):
    user_id, _role = auth("Restaurant")
    order = db.orders.get(order_id)
    if order is not None and order["restaurant_id"] != user_id:
        raise ApiError("ERR_FORBIDDEN_RESOURCE",
                       "A restaurant may only deliver orders addressed to itself.")
    if order is None:
        raise ApiError("ERR_ORDER_NOT_FOUND")

    if order["fulfillment_status"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_STATE",
                       "An order in status %s cannot be delivered." % order["fulfillment_status"])

    employee, program, period, _rule = order_context(order)

    # rank 14 — the payroll bucket must still be open
    record = calc.find_imputed_record(employee["id"], order["tax_month"])
    if record is not None and record["status"] in ("LOCKED", "EXPORTED"):
        raise ApiError("ERR_TAX_MONTH_LOCKED",
                       "The imputed-income bucket for %s is %s."
                       % (order["tax_month"], record["status"]))

    order["delivered_at"] = fmt_dt(db.now)
    order["fulfillment_status"] = "DELIVERED"
    order["settlement_status"] = "CAPTURED"
    order["net_charged_cents"] = order["gross_total_cents"]
    order["employer_net_cents"] = order["employer_covered_cents"]
    touch(order)

    employer = order["employer_covered_cents"]
    period["reserved_cents"] -= employer
    period["spent_cents"] += employer
    touch(period)

    if record is None:
        row = base_row()
        row.update({
            "employee_id": employee["id"],
            "tax_month": order["tax_month"],
            "method": program["taxable_benefit_method"],
            "gross_employer_paid_cents": 0,
            "taxable_cents": 0,
            "status": "ACCRUING",
            "_fresh": True,
        })
        db.imputed_records[row["id"]] = row

    calc.reconcile_imputed(employee["id"], order["tax_month"])
    calc.recompute_program_rollups(program["id"])
    return object_response(public(order))


# --------------------------------------------------------------------------
# cancellation
# --------------------------------------------------------------------------
def void_authorised_split(order, group_order, adjust_group=True):
    """Release the reservation, write the void ledger and zero the captured figures."""
    period = db.benefit_periods.get(order["benefit_period_id"])
    employer = order["employer_covered_cents"]
    employee_card = order["employee_card_cents"]

    if period is not None:
        period["reserved_cents"] -= employer
        period["available_cents"] += employer
        touch(period)

    if employer > 0:
        calc.write_ledger_entry(order["id"], "EMPLOYER_CREDIT", employer, "ORDER_VOID")
    if employee_card > 0:
        calc.write_ledger_entry(order["id"], "EMPLOYEE_CARD_REFUND", employee_card, "ORDER_VOID")

    order["employer_refunded_cents"] = employer
    order["employee_refunded_cents"] = employee_card
    order["net_charged_cents"] = 0
    order["employer_net_cents"] = 0
    order["admin_fee_cents"] = 0

    if adjust_group and group_order is not None:
        group_order["member_order_count"] = max(0, group_order.get("member_order_count", 0) - 1)
        touch(group_order)


def cancel_order_row(order, adjust_group=True):
    """Shared cancellation body; the caller has already checked actor and state."""
    group_order = db.group_orders.get(order["group_order_id"]) if order.get("group_order_id") else None
    had_split = order["settlement_status"] == "SPLIT_AUTHORIZED"
    order["fulfillment_status"] = "CANCELLED"
    order["settlement_status"] = "VOIDED"
    if had_split:
        void_authorised_split(order, group_order, adjust_group=adjust_group)
    touch(order)
    employee = db.employees.get(order["employee_id"])
    if employee:
        calc.recompute_program_rollups(employee["program_id"])


@bp.post("/orders/<order_id>/cancel")
def cancel_order(order_id):
    user_id, role = auth("Employee", "ProgramAdmin")
    order = db.orders.get(order_id)
    if order is not None and role == "Employee" and order["employee_id"] != user_id:
        raise ApiError("ERR_FORBIDDEN_RESOURCE", "An employee may only cancel their own orders.")
    if order is None:
        raise ApiError("ERR_ORDER_NOT_FOUND")

    status = order["fulfillment_status"]
    if status not in ("DRAFT", "PLACED", "CONFIRMED"):
        raise ApiError("ERR_INVALID_STATE",
                       "An order in status %s cannot be cancelled." % status)
    if status == "CONFIRMED" and role != "ProgramAdmin":
        raise ApiError("ERR_INVALID_STATE",
                       "A CONFIRMED order may only be cancelled by a ProgramAdmin.")

    cancel_order_row(order)
    return object_response(public(order))


# --------------------------------------------------------------------------
# refund ledger
# --------------------------------------------------------------------------
@bp.get("/orders/<order_id>/refund-entries")
def list_order_entries(order_id):
    auth("ProgramAdmin", "BenefitsController", "Employee")
    limit, offset = pagination()
    direction = q_enum("direction", DIRECTIONS)
    reason = q_enum("reason", REASONS)
    order = require(db.orders, order_id, "ERR_ORDER_NOT_FOUND")
    rows = [e for e in db.refund_entries.values() if e["order_id"] == order["id"]]
    if direction is not None:
        rows = [e for e in rows if e["direction"] == direction]
    if reason is not None:
        rows = [e for e in rows if e["reason"] == reason]
    items, total = paginate(rows, limit, offset)
    return list_response(items, limit, offset, total)
