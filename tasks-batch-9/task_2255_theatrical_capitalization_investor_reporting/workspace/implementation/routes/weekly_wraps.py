"""Weekly wraps: reporting, certification, dispute, amendment and void.

PRD 3.6 / 3.7.  Certification is the pivotal write of the show-accounting half:
it settles the royalty burden, splits the pool, and posts the week to the
recoupment ledger.
"""

from flask import Blueprint

import db
import errors
import response
import validation as v
from errors import fail
from middleware import (COMPTROLLER, GENERAL_MANAGER, OPERATOR_ROLES, ctx,
                        endpoint, find_production, lookup, user_id)
from services import ledger
from services import queries as q

bp = Blueprint("weekly_wraps", __name__)

WRAP_STATUSES = ("DRAFT", "SUBMITTED", "CERTIFIED", "DISPUTED", "AMENDED",
                 "VOID")
PERFORMING_STATUSES = ("PREVIEWS", "RUNNING", "CLOSING_NOTICE")
OPEN_WRAP_STATUSES = ("DRAFT", "SUBMITTED", "DISPUTED", "AMENDED")
WEEK_LENGTH_DAYS = 7
MAX_PERFORMANCES_PER_WEEK = 16


def _find_wrap(wrap_id):
    return lookup("weekly_wraps", wrap_id, errors.ERR_WEEKLY_WRAP_NOT_FOUND)


def _require_performing(production):
    if production["operating_status"] not in PERFORMING_STATUSES:
        fail(errors.ERR_PRODUCTION_NOT_PERFORMING,
             "The production is not in a performing operating state.")


def _sole_active_budget(production_id):
    active = q.active_operating_budgets(production_id)
    if len(active) != 1:
        fail(errors.ERR_ACTIVE_OPERATING_BUDGET_MISSING,
             "Exactly one ACTIVE operating budget is required.")
    return active[0]


def _require_week_not_future(week_ending):
    if week_ending > db.logical_date():
        fail(errors.ERR_WRAP_WEEK_IN_FUTURE,
             "The performance week has not finished yet.")


@bp.post("/weekly-wraps")
@endpoint((GENERAL_MANAGER,))
def create_weekly_wrap():
    data = v.body()
    production_id = v.req_id(data, "production_id")
    week_text, week_ending = v.req_date(data, "week_ending_date")
    performances = v.req_int(data, "performances", 1,
                             MAX_PERFORMANCES_PER_WEEK)
    gross_receipts = v.req_int(data, "gross_receipts_cents", 0)
    paid_attendance = v.req_int(data, "paid_attendance", 0)
    running_expenses = v.req_int(data, "running_expenses_cents", 0)

    production = find_production(production_id)
    _require_performing(production)
    budget = _sole_active_budget(production_id)
    _require_week_not_future(week_ending)

    # Half-open week rule: two non-VOID wraps of a production collide whenever
    # their week_ending_date values are fewer than seven days apart (PRD 3.6).
    for other in q.wraps_of(production_id):
        if other["status"] == "VOID":
            continue
        other_week = db.parse_iso_date(other["week_ending_date"])
        if abs(db.days_between(other_week, week_ending)) < WEEK_LENGTH_DAYS:
            fail(errors.ERR_WRAP_WEEK_OVERLAP,
                 "The performance week overlaps another wrap of this production.")

    theatre = db.get("theatres", production["theatre_id"])
    row = db.insert("weekly_wraps", {
        "production_id": production_id,
        "operating_budget_id": budget["id"],
        "operating_budget_version_pinned": budget["version"],
        "week_ending_date": week_text,
        "performances": performances,
        "gross_receipts_cents": gross_receipts,
        "paid_attendance": paid_attendance,
        "running_expenses_cents": running_expenses,
        "capacity_gross_cents": 0,
        "paid_capacity_pct": db.ZERO4,
        "variable_cost_cents": 0,
        "adjusted_gross_cents": 0,
        "royalty_base_cents": 0,
        "royalty_basis_applied": None,
        "royalty_pool_cents": 0,
        "weekly_operating_profit_cents": 0,
        "deferred_royalty_added_cents": 0,
        "status": "DRAFT",
        "submitted_by_user_id": None,
        "certified_by_user_id": None,
        "dispute_note": None,
        "void_reason": None,
    })
    ledger.derive_wrap_provisional(row, theatre, budget)
    return response.obj(row, 201)


@bp.post("/weekly-wraps/<wrap_id>/submit")
@endpoint((GENERAL_MANAGER,))
def submit_weekly_wrap(wrap_id):
    wrap = _find_wrap(wrap_id)
    production = db.get("productions", wrap["production_id"])
    if wrap["status"] not in ("DRAFT", "AMENDED"):
        fail(errors.ERR_INVALID_WRAP_STATE,
             "Only a DRAFT or AMENDED wrap may be submitted.")
    _require_performing(production)

    ctx().watch(wrap)
    wrap["status"] = "SUBMITTED"
    wrap["submitted_by_user_id"] = user_id()
    return response.obj(wrap)


@bp.post("/weekly-wraps/<wrap_id>/certify")
@endpoint((COMPTROLLER,))
def certify_weekly_wrap(wrap_id):
    wrap = _find_wrap(wrap_id)
    production = db.get("productions", wrap["production_id"])

    # Priority 7 outranks the state check (PRD 2.10).
    if wrap["submitted_by_user_id"] is not None \
            and wrap["submitted_by_user_id"] == user_id():
        fail(errors.ERR_SEGREGATION_OF_DUTIES,
             "The certifying operator may not be the submitting operator.")
    if wrap["status"] != "SUBMITTED":
        fail(errors.ERR_INVALID_WRAP_STATE,
             "Only a SUBMITTED wrap may be certified.")

    budget = db.get("operating_budgets", wrap["operating_budget_id"])
    if budget is None or budget["version"] != wrap[
            "operating_budget_version_pinned"]:
        fail(errors.ERR_OPERATING_BUDGET_CHANGED,
             "The pinned operating budget has changed since the wrap was opened.")

    theatre = db.get("theatres", production["theatre_id"])
    ctx().force(production)
    ctx().watch(wrap)
    wrap["status"] = "CERTIFIED"
    wrap["certified_by_user_id"] = user_id()

    ledger.settle_wrap(wrap, production, theatre, budget)
    ledger.royalty_pool_split(ctx(), wrap, production)
    for participant in q.participants_of(production["id"]):
        ledger.refresh_participant_cumulative(ctx(), participant)
    production["deferred_royalty_cents"] += wrap["deferred_royalty_added_cents"]
    ledger.recoupment_progress(ctx(), production)
    return response.obj(wrap)


@bp.post("/weekly-wraps/<wrap_id>/dispute")
@endpoint((COMPTROLLER,))
def dispute_weekly_wrap(wrap_id):
    wrap = _find_wrap(wrap_id)
    data = v.body()
    note = v.req_str(data, "dispute_note")
    if wrap["status"] != "SUBMITTED":
        fail(errors.ERR_INVALID_WRAP_STATE,
             "Only a SUBMITTED wrap may be disputed.")

    ctx().watch(wrap)
    wrap["status"] = "DISPUTED"
    wrap["dispute_note"] = note
    return response.obj(wrap)


@bp.post("/weekly-wraps/<wrap_id>/amend")
@endpoint((GENERAL_MANAGER,))
def amend_weekly_wrap(wrap_id):
    wrap = _find_wrap(wrap_id)
    data = v.body()
    performances = v.opt_int(data, "performances", None, 1,
                             MAX_PERFORMANCES_PER_WEEK)
    gross_receipts = v.opt_int(data, "gross_receipts_cents", None, 0)
    paid_attendance = v.opt_int(data, "paid_attendance", None, 0)
    running_expenses = v.opt_int(data, "running_expenses_cents", None, 0)

    production = db.get("productions", wrap["production_id"])
    if wrap["status"] != "DISPUTED":
        fail(errors.ERR_INVALID_WRAP_STATE,
             "Only a DISPUTED wrap may be amended.")
    _require_performing(production)
    budget = _sole_active_budget(production["id"])
    _require_week_not_future(db.parse_iso_date(wrap["week_ending_date"]))

    ctx().watch(wrap)
    if performances is not None:
        wrap["performances"] = performances
    if gross_receipts is not None:
        wrap["gross_receipts_cents"] = gross_receipts
    if paid_attendance is not None:
        wrap["paid_attendance"] = paid_attendance
    if running_expenses is not None:
        wrap["running_expenses_cents"] = running_expenses

    wrap["operating_budget_id"] = budget["id"]
    wrap["operating_budget_version_pinned"] = budget["version"]
    theatre = db.get("theatres", production["theatre_id"])
    ledger.derive_wrap_provisional(wrap, theatre, budget)
    wrap["submitted_by_user_id"] = None
    wrap["status"] = "AMENDED"
    return response.obj(wrap)


@bp.post("/weekly-wraps/<wrap_id>/void")
@endpoint((COMPTROLLER,))
def void_weekly_wrap(wrap_id):
    wrap = _find_wrap(wrap_id)
    data = v.body()
    reason = v.req_str(data, "void_reason")
    production = db.get("productions", wrap["production_id"])
    if wrap["status"] != "CERTIFIED":
        fail(errors.ERR_INVALID_WRAP_STATE,
             "Only a CERTIFIED wrap may be voided.")
    if production["operating_status"] == "CLOSED":
        fail(errors.ERR_PRODUCTION_NOT_PERFORMING,
             "A wrap of a CLOSED production may not be voided.")

    ctx().force(production)
    ctx().watch(wrap)
    wrap["status"] = "VOID"
    wrap["void_reason"] = reason

    for allocation in q.allocations_of_wrap(wrap["id"]):
        if allocation["status"] != "ALLOCATED":
            continue
        ctx().watch(allocation)
        allocation["status"] = "REVERSED"
    for participant in q.participants_of(production["id"]):
        ledger.refresh_participant_cumulative(ctx(), participant)

    production["deferred_royalty_cents"] -= wrap["deferred_royalty_added_cents"]
    ledger.recoupment_progress(ctx(), production)
    return response.obj(wrap)


@bp.get("/weekly-wraps/<wrap_id>")
@endpoint(OPERATOR_ROLES)
def read_weekly_wrap(wrap_id):
    return response.obj(_find_wrap(wrap_id))


@bp.get("/weekly-wraps")
@endpoint(OPERATOR_ROLES)
def list_weekly_wraps():
    production_id = v.q_str("production_id")
    budget_id = v.q_str("operating_budget_id")
    status = v.q_enum("status", WRAP_STATUSES)
    limit, offset = v.pagination()
    rows = [r for r in db.all_rows("weekly_wraps")
            if (production_id is None or r["production_id"] == production_id)
            and (budget_id is None or r["operating_budget_id"] == budget_id)
            and (status is None or r["status"] == status)]
    return response.listing(rows, limit, offset)
