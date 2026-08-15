"""OperatingBudget endpoints."""
from flask import Blueprint, request

from db import db
from errors import validation, ApiError, ERR_BUDGET_INVALID_STATE, ERR_BUDGET_YEAR_EXISTS
from middleware import require_roles, require_read, require_owner_of
from response import success_object, success_list
from serializers import budget_view
from services.core import (
    make_record, touch, require_exists, get_pagination, paginate,
    current_agreement_for_aircraft,
)

bp = Blueprint("budgets", __name__)

AMOUNT_FIELDS = ("fuel_cents", "maintenance_cents", "crew_cents",
                 "hangar_cents", "insurance_cents", "other_cents")


def _check_amount(value, field):
    if isinstance(value, bool) or not isinstance(value, int):
        raise validation(f"{field} must be an integer")


@bp.route("/budgets", methods=["POST"])
def create_budget():
    require_roles("AccountExecutive")
    body = request.get_json(silent=True) or {}

    aircraft_id = body.get("aircraft_id")
    if aircraft_id is not None:
        require_exists(db.aircraft, aircraft_id, "aircraft_id does not resolve")

    if not isinstance(aircraft_id, str) or not aircraft_id:
        raise validation("aircraft_id is required")

    fiscal_year = body.get("fiscal_year")
    if isinstance(fiscal_year, bool) or not isinstance(fiscal_year, int):
        raise validation("fiscal_year must be an integer")
    if fiscal_year < 1000 or fiscal_year > 9999:
        raise validation("fiscal_year must be a four-digit year")

    amounts = {}
    for f in AMOUNT_FIELDS:
        v = body.get(f)
        _check_amount(v, f)
        amounts[f] = v

    for b in db.budgets.values():
        if b["aircraft_id"] == aircraft_id and b["fiscal_year"] == fiscal_year:
            raise ApiError(ERR_BUDGET_YEAR_EXISTS,
                           "A budget already exists for this (aircraft_id, fiscal_year)", 409)

    fields = {
        "aircraft_id": aircraft_id,
        "fiscal_year": fiscal_year,
        "status": "DRAFT",
        "rejection_reason": None,
    }
    fields.update(amounts)
    rec = make_record(fields)
    db.budgets[rec["id"]] = rec
    return success_object(budget_view(rec), 201)


@bp.route("/aircraft/<aircraft_id>/budgets", methods=["GET"])
def list_budgets(aircraft_id):
    require_read()
    require_exists(db.aircraft, aircraft_id)
    limit, offset = get_pagination(request.args)
    records = [b for b in db.budgets.values() if b["aircraft_id"] == aircraft_id]
    page, total = paginate(records, limit, offset)
    return success_list([budget_view(r) for r in page], limit, offset, total)


@bp.route("/budgets/<budget_id>", methods=["PATCH"])
def revise_budget(budget_id):
    require_roles("AccountExecutive")
    rec = require_exists(db.budgets, budget_id)
    body = request.get_json(silent=True) or {}
    for f in AMOUNT_FIELDS:
        if f in body and body[f] is not None:
            _check_amount(body[f], f)

    if rec["status"] not in ("DRAFT", "REJECTED"):
        raise ApiError(ERR_BUDGET_INVALID_STATE,
                       "Budget may only be revised from DRAFT or REJECTED", 409)

    for f in AMOUNT_FIELDS:
        if f in body and body[f] is not None:
            rec[f] = body[f]
    rec["rejection_reason"] = None
    if rec["status"] == "REJECTED":
        rec["status"] = "DRAFT"
    touch(rec, bump_version=True)
    return success_object(budget_view(rec))


@bp.route("/budgets/<budget_id>/submit", methods=["POST"])
def submit_budget(budget_id):
    require_roles("AccountExecutive")
    rec = require_exists(db.budgets, budget_id)
    if rec["status"] != "DRAFT":
        raise ApiError(ERR_BUDGET_INVALID_STATE, "Budget must be in DRAFT", 409)
    rec["status"] = "SUBMITTED"
    touch(rec, bump_version=True)
    return success_object(budget_view(rec))


def _owner_scoped_check(rec, user_id, role):
    agreement = current_agreement_for_aircraft(rec["aircraft_id"])
    owner_id = agreement["owner_id"] if agreement is not None else None
    require_owner_of(user_id, role, owner_id)


@bp.route("/budgets/<budget_id>/approve", methods=["POST"])
def approve_budget(budget_id):
    user_id, role = require_roles("Owner")
    rec = require_exists(db.budgets, budget_id)
    _owner_scoped_check(rec, user_id, role)
    if rec["status"] != "SUBMITTED":
        raise ApiError(ERR_BUDGET_INVALID_STATE, "Budget must be in SUBMITTED", 409)
    rec["status"] = "APPROVED"
    touch(rec, bump_version=True)
    return success_object(budget_view(rec))


@bp.route("/budgets/<budget_id>/reject", methods=["POST"])
def reject_budget(budget_id):
    user_id, role = require_roles("Owner")
    rec = require_exists(db.budgets, budget_id)
    _owner_scoped_check(rec, user_id, role)
    body = request.get_json(silent=True) or {}
    if rec["status"] != "SUBMITTED":
        raise ApiError(ERR_BUDGET_INVALID_STATE, "Budget must be in SUBMITTED", 409)
    rec["status"] = "REJECTED"
    rec["rejection_reason"] = body.get("reason")
    touch(rec, bump_version=True)
    return success_object(budget_view(rec))
