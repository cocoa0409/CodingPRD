"""Closing notices: posting, withdrawal and reserve settlement (PRD 3.9)."""

from flask import Blueprint

import db
import errors
import response
import validation as v
from errors import fail
from middleware import (COMPTROLLER, GENERAL_MANAGER, INVESTOR, LEAD_PRODUCER,
                        ctx, endpoint, find_production, lookup, user_id)
from services import ledger
from services import queries as q

bp = Blueprint("closing_notices", __name__)

REASONS = ("SCHEDULED_END", "ECONOMIC", "VENUE_LOSS")
NOTICE_STATUSES = ("ISSUED", "WITHDRAWN", "SETTLED")
OPEN_WRAP_STATUSES = ("DRAFT", "SUBMITTED", "DISPUTED", "AMENDED")
READ_ROLES = (GENERAL_MANAGER, COMPTROLLER, LEAD_PRODUCER, INVESTOR)


def _find_notice(notice_id):
    return lookup("closing_notices", notice_id,
                  errors.ERR_CLOSING_NOTICE_NOT_FOUND)


def _move_reserve_lines(production, from_status, to_status):
    for line in q.budget_lines_of(production["id"]):
        if line["component"] != "RESERVE":
            continue
        if line["commitment_status"] != from_status:
            continue
        ctx().watch(line)
        line["commitment_status"] = to_status


@bp.post("/closing-notices")
@endpoint((LEAD_PRODUCER,))
def create_closing_notice():
    data = v.body()
    production_id = v.req_id(data, "production_id")
    notice_text, notice_date = v.req_date(data, "notice_date")
    final_text, final_date = v.req_date(data, "final_performance_date")
    reason = v.req_enum(data, "reason", REASONS)

    production = find_production(production_id)

    # The single-notice rule is checked first: posting a notice always drives
    # the production to CLOSING_NOTICE, so a second attempt would otherwise
    # always trip the operating-state guard and ERR_CLOSING_NOTICE_ALREADY_ISSUED
    # could never be observed (PRD 3.9).
    for other in q.notices_of(production_id):
        if other["status"] == "ISSUED":
            fail(errors.ERR_CLOSING_NOTICE_ALREADY_ISSUED,
                 "The production already holds an ISSUED closing notice.")

    if production["operating_status"] not in ("PREVIEWS", "RUNNING"):
        fail(errors.ERR_INVALID_OPERATING_STATE,
             "A closing notice may only be posted from PREVIEWS or RUNNING.")

    if notice_date < db.logical_date():
        fail(errors.ERR_NOTICE_DATE_IN_PAST,
             "A closing notice may not be back-dated.")
    notice_days = db.days_between(notice_date, final_date)
    if notice_days < production["closing_notice_min_days"]:
        fail(errors.ERR_INSUFFICIENT_CLOSING_NOTICE,
             "The notice period is shorter than closing_notice_min_days.")

    row = db.insert("closing_notices", {
        "production_id": production_id,
        "notice_date": notice_text,
        "final_performance_date": final_text,
        "reason": reason,
        "notice_days": notice_days,
        "closing_costs_cents": None,
        "reserve_balance_at_settlement_cents": 0,
        "reserve_released_cents": 0,
        "closing_cost_shortfall_cents": 0,
        "status": "ISSUED",
        "issued_by_user_id": user_id(),
        "settled_by_user_id": None,
        "withdrawal_reason": None,
    })
    ctx().created(row)
    ctx().force(production)
    production["operating_status"] = "CLOSING_NOTICE"
    _move_reserve_lines(production, "PLANNED", "COMMITTED")
    ledger.capitalization_budget_rollup(ctx(), production)
    return response.obj(row, 201)


@bp.post("/closing-notices/<notice_id>/withdraw")
@endpoint((LEAD_PRODUCER,))
def withdraw_closing_notice(notice_id):
    notice = _find_notice(notice_id)
    data = v.body()
    reason = v.req_str(data, "withdrawal_reason")
    production = db.get("productions", notice["production_id"])

    if notice["status"] != "ISSUED":
        fail(errors.ERR_INVALID_CLOSING_NOTICE_STATE,
             "Only an ISSUED closing notice may be withdrawn.")
    if production["operating_status"] != "CLOSING_NOTICE":
        fail(errors.ERR_INVALID_OPERATING_STATE,
             "The production's operating axis must read CLOSING_NOTICE.")

    ctx().force(production)
    ctx().watch(notice)
    notice["status"] = "WITHDRAWN"
    notice["withdrawal_reason"] = reason
    production["operating_status"] = "RUNNING"
    _move_reserve_lines(production, "COMMITTED", "PLANNED")
    ledger.capitalization_budget_rollup(ctx(), production)
    return response.obj(notice)


@bp.post("/closing-notices/<notice_id>/settle")
@endpoint((COMPTROLLER,))
def settle_closing_notice(notice_id):
    notice = _find_notice(notice_id)
    data = v.body()
    closing_costs = v.req_int(data, "closing_costs_cents", 0)
    production = db.get("productions", notice["production_id"])

    # Priority 7 outranks the state checks (PRD 2.10).
    if notice["issued_by_user_id"] == user_id():
        fail(errors.ERR_SEGREGATION_OF_DUTIES,
             "The settling operator may not be the issuing operator.")
    if notice["status"] != "ISSUED":
        fail(errors.ERR_INVALID_CLOSING_NOTICE_STATE,
             "Only an ISSUED closing notice may be settled.")
    if production["operating_status"] != "CLOSING_NOTICE":
        fail(errors.ERR_INVALID_OPERATING_STATE,
             "The production's operating axis must read CLOSING_NOTICE.")
    for wrap in q.wraps_of(production["id"]):
        if wrap["status"] in OPEN_WRAP_STATUSES:
            fail(errors.ERR_UNCERTIFIED_WRAPS_EXIST,
                 "Every wrap of the production must be certified or voided first.")

    # The reserve balance is read BEFORE the lines move to SPENT (PRD 3.9).
    settlement = ledger.closing_reserve_settlement(production, closing_costs)

    ctx().force(production)
    ctx().watch(notice)
    notice["closing_costs_cents"] = closing_costs
    notice.update(settlement)
    notice["settled_by_user_id"] = user_id()
    notice["status"] = "SETTLED"

    _move_reserve_lines(production, "COMMITTED", "SPENT")
    ledger.capitalization_budget_rollup(ctx(), production)
    production["operating_status"] = "CLOSED"
    ledger.recoupment_progress(ctx(), production)
    return response.obj(notice)


@bp.get("/closing-notices/<notice_id>")
@endpoint(READ_ROLES)
def read_closing_notice(notice_id):
    return response.obj(_find_notice(notice_id))


@bp.get("/closing-notices")
@endpoint(READ_ROLES)
def list_closing_notices():
    production_id = v.q_str("production_id")
    status = v.q_enum("status", NOTICE_STATUSES)
    limit, offset = v.pagination()
    rows = [r for r in db.all_rows("closing_notices")
            if (production_id is None or r["production_id"] == production_id)
            and (status is None or r["status"] == status)]
    return response.listing(rows, limit, offset)
