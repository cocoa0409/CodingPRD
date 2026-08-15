"""MonthlyStatement endpoints."""
from flask import Blueprint, request

import clock
from db import db
from errors import (
    validation, ApiError,
    ERR_STATEMENT_EXISTS, ERR_STATEMENT_INVALID_STATE,
    ERR_SEGREGATION_OF_DUTIES, ERR_STATEMENT_STALE,
)
from middleware import require_roles, require_read
from response import success_object, success_list
from serializers import statement_view
from services.core import (
    make_record, touch, require_exists, get_pagination, paginate,
    find_draft_statement, stamp_computed,
)
from services.statements import compute_statement_fields
from util import fmt_ts, parse_period, period_bounds, parse_date

bp = Blueprint("statements", __name__)


@bp.route("/statements", methods=["POST"])
def generate_statement():
    user_id, _role = require_roles("AccountExecutive")
    body = request.get_json(silent=True) or {}

    aircraft_id = body.get("aircraft_id")
    if aircraft_id is not None:
        require_exists(db.aircraft, aircraft_id, "aircraft_id does not resolve")
    if not isinstance(aircraft_id, str) or not aircraft_id:
        raise validation("aircraft_id is required")

    period = body.get("period")
    parse_period(period)  # raises ERR_VALIDATION on malformed

    # uniqueness over CERTIFIED/DELIVERED; regenerate over DRAFT
    existing_draft = find_draft_statement(aircraft_id, period)
    for st in db.statements.values():
        if (st["aircraft_id"] == aircraft_id and st["period"] == period
                and st["status"] in ("CERTIFIED", "DELIVERED")):
            raise ApiError(ERR_STATEMENT_EXISTS,
                           "A CERTIFIED or DELIVERED statement already exists for this (aircraft_id, period)", 409)

    if existing_draft is not None:
        compute_statement_fields(existing_draft)
        existing_draft["prepared_by_user_id"] = user_id
        stamp_computed(existing_draft)
        touch(existing_draft)
        return success_object(statement_view(existing_draft), 201)

    rec = make_record({
        "aircraft_id": aircraft_id,
        "period": period,
        "prepared_by_user_id": user_id,
        "certified_by_user_id": None,
        "accrual_total_cents": 0,
        "cash_total_cents": 0,
        "management_fee_cents": 0,
        "charter_offset_cents": 0,
        "budget_variance_cents": None,
        "mixed_owner_share_cents": 0,
        "mixed_charter_share_cents": 0,
        "tax_method_used": None,
        "status": "DRAFT",
    })
    compute_statement_fields(rec)
    stamp_computed(rec)
    db.statements[rec["id"]] = rec
    return success_object(statement_view(rec), 201)


@bp.route("/statements/<statement_id>", methods=["GET"])
def get_statement(statement_id):
    require_read()
    rec = require_exists(db.statements, statement_id)
    return success_object(statement_view(rec))


@bp.route("/aircraft/<aircraft_id>/statements", methods=["GET"])
def list_statements(aircraft_id):
    require_read()
    require_exists(db.aircraft, aircraft_id)
    limit, offset = get_pagination(request.args)
    records = [s for s in db.statements.values() if s["aircraft_id"] == aircraft_id]
    page, total = paginate(records, limit, offset)
    return success_list([statement_view(r) for r in page], limit, offset, total)


@bp.route("/statements/<statement_id>/certify", methods=["POST"])
def certify_statement(statement_id):
    user_id, _role = require_roles("FinanceController")
    rec = require_exists(db.statements, statement_id)
    if rec["status"] != "DRAFT":
        raise ApiError(ERR_STATEMENT_INVALID_STATE, "Statement must be in DRAFT", 409)
    if user_id == rec["prepared_by_user_id"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES,
                       "Statement certifier must differ from prepared_by_user_id", 403)

    # staleness: any in-period POSTED expense created after the last computation
    start, end = period_bounds(rec["period"])
    marker = (rec.get("_computed_at") or rec["created_at"],
              rec.get("_computed_seq") if rec.get("_computed_seq") is not None else rec["_seq"])
    for e in db.expenses.values():
        if e["aircraft_id"] != rec["aircraft_id"] or e["status"] != "POSTED":
            continue
        d = parse_date(e["service_date"], "service_date")
        if not (start <= d < end):
            continue
        if (e["created_at"], e["_seq"]) > marker:
            raise ApiError(ERR_STATEMENT_STALE,
                           "A POSTED expense in the statement's period is not reflected in the statement's last computation", 409)

    rec["certified_by_user_id"] = user_id
    rec["status"] = "CERTIFIED"
    touch(rec, bump_version=True)

    # lock in-period POSTED expenses to BILLED
    for e in db.expenses.values():
        if e["aircraft_id"] != rec["aircraft_id"] or e["status"] != "POSTED":
            continue
        d = parse_date(e["service_date"], "service_date")
        if start <= d < end:
            e["status"] = "BILLED"
            e["statement_id"] = rec["id"]
            touch(e, bump_version=True)

    return success_object(statement_view(rec))


@bp.route("/statements/<statement_id>/deliver", methods=["POST"])
def deliver_statement(statement_id):
    require_roles("AccountExecutive")
    rec = require_exists(db.statements, statement_id)
    if rec["status"] != "CERTIFIED":
        raise ApiError(ERR_STATEMENT_INVALID_STATE, "Statement must be in CERTIFIED", 409)
    rec["status"] = "DELIVERED"
    touch(rec, bump_version=True)
    return success_object(statement_view(rec))
