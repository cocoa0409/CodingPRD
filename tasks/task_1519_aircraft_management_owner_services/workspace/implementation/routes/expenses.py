"""Expense endpoints."""
from flask import Blueprint, request

from db import db
from errors import validation, ApiError, ERR_EXPENSE_NOT_POSTED, ERR_QUOTE_REQUIRED
from middleware import require_roles, require_read
from response import success_object, success_list
from serializers import expense_view
from services.core import (
    make_record, touch, require_exists, filter_value_exists,
    get_pagination, paginate, recompute_draft_statements_for_date,
)
from util import parse_date

bp = Blueprint("expenses", __name__)

CATEGORIES = {"FUEL", "CREW", "MAINTENANCE", "HANGAR", "INSURANCE",
              "PROGRAM_ACCRUAL", "CHARTER_DIRECT", "OTHER"}
TAX_USES = {"OWNER_USE", "CHARTER_USE", "MIXED"}
STATUSES = {"POSTED", "BILLED", "VOID"}


@bp.route("/expenses", methods=["POST"])
def create_expense():
    require_roles("FinanceController")
    body = request.get_json(silent=True) or {}

    aircraft_id = body.get("aircraft_id")
    trip_id = body.get("trip_id")
    if aircraft_id is not None:
        require_exists(db.aircraft, aircraft_id, "aircraft_id does not resolve")
    if trip_id is not None:
        require_exists(db.trips, trip_id, "trip_id does not resolve")

    if not isinstance(aircraft_id, str) or not aircraft_id:
        raise validation("aircraft_id is required")
    category = body.get("category")
    if category not in CATEGORIES:
        raise validation("category is not a valid enum value")
    amount = body.get("amount_cents")
    if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
        raise validation("amount_cents must be an integer > 0")

    service_date = body.get("service_date")
    parse_date(service_date, "service_date")  # raises on malformed

    paid_date = body.get("paid_date")
    if paid_date is not None:
        parse_date(paid_date, "paid_date")

    vendor_name = body.get("vendor_name")
    if not isinstance(vendor_name, str) or not vendor_name:
        raise validation("vendor_name is required")
    tax_use = body.get("tax_use")
    if tax_use not in TAX_USES:
        raise validation("tax_use is not a valid enum value")

    # quote/trip linkage rules (ERR_QUOTE_REQUIRED)
    if category == "CHARTER_DIRECT":
        if trip_id is None:
            raise ApiError(ERR_QUOTE_REQUIRED,
                           "CHARTER_DIRECT expense must carry trip_id of an existing CHARTER trip", 422)
        trip = db.trips[trip_id]
        if trip["trip_use"] != "CHARTER":
            raise ApiError(ERR_QUOTE_REQUIRED,
                           "CHARTER_DIRECT expense must carry trip_id of an existing CHARTER trip", 422)
    else:
        if trip_id is not None:
            raise ApiError(ERR_QUOTE_REQUIRED,
                           "Only CHARTER_DIRECT expenses may carry trip_id", 422)

    rec = make_record({
        "aircraft_id": aircraft_id,
        "statement_id": None,
        "trip_id": trip_id if category == "CHARTER_DIRECT" else None,
        "category": category,
        "amount_cents": amount,
        "service_date": service_date,
        "paid_date": paid_date,
        "vendor_name": vendor_name,
        "tax_use": tax_use,
        "status": "POSTED",
    })
    db.expenses[rec["id"]] = rec
    recompute_draft_statements_for_date(aircraft_id, service_date)
    return success_object(expense_view(rec), 201)


@bp.route("/expenses/<expense_id>", methods=["GET"])
def get_expense(expense_id):
    require_read()
    rec = require_exists(db.expenses, expense_id)
    return success_object(expense_view(rec))


@bp.route("/expenses", methods=["GET"])
def list_expenses():
    require_read()
    aircraft_id = request.args.get("aircraft_id")
    statement_id = request.args.get("statement_id")
    trip_id = request.args.get("trip_id")
    status = request.args.get("status")
    category = request.args.get("category")
    filter_value_exists(db.aircraft, aircraft_id)
    filter_value_exists(db.statements, statement_id)
    filter_value_exists(db.trips, trip_id)
    if status is not None and status not in STATUSES:
        raise validation("status is not a valid enum value")
    if category is not None and category not in CATEGORIES:
        raise validation("category is not a valid enum value")

    limit, offset = get_pagination(request.args)
    records = list(db.expenses.values())
    if aircraft_id is not None:
        records = [r for r in records if r["aircraft_id"] == aircraft_id]
    if statement_id is not None:
        records = [r for r in records if r["statement_id"] == statement_id]
    if trip_id is not None:
        records = [r for r in records if r["trip_id"] == trip_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    if category is not None:
        records = [r for r in records if r["category"] == category]
    page, total = paginate(records, limit, offset)
    return success_list([expense_view(r) for r in page], limit, offset, total)


@bp.route("/expenses/<expense_id>/void", methods=["POST"])
def void_expense(expense_id):
    require_roles("FinanceController")
    rec = require_exists(db.expenses, expense_id)
    if rec["status"] != "POSTED":
        raise ApiError(ERR_EXPENSE_NOT_POSTED, "Expense must be POSTED to be voided", 409)
    rec["status"] = "VOID"
    touch(rec, bump_version=True)
    recompute_draft_statements_for_date(rec["aircraft_id"], rec["service_date"])
    return success_object(expense_view(rec))
