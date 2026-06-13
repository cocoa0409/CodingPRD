"""Deadlines and the calendaring engine."""
from flask import Blueprint, request

import db
import errors
from middleware import get_actor, require_role
from response import success
from services import domain, validate, calc

bp = Blueprint("deadlines", __name__)

DEADLINE_TYPES = {"RESPONSE", "DISCOVERY", "MOTION_HEARING", "STATUTE_OF_LIMITATIONS", "APPEAL"}
ANCHOR_EVENTS = {"SERVICE_COMPLETED", "FILING_ACCEPTED", "JUDGMENT_ENTERED", "CASE_OPENED", "MANUAL"}
COUNTING_MODES = {"CALENDAR", "COURT_DAYS"}


@bp.post("/deadlines")
def create_deadline():
    _, role = get_actor()
    require_role(role, {"Clerk"})
    data = validate.body(request)
    case_id = validate.require_str(data, "case_id")
    parent_deadline_id = data.get("parent_deadline_id")

    # Existence (priority 3) before remaining body validation (priority 4).
    case = domain.get_or_404(db.cases, case_id)
    if parent_deadline_id is not None:
        domain.get_or_404(db.deadlines, parent_deadline_id)

    deadline_type = validate.enum(data, "deadline_type", DEADLINE_TYPES)
    anchor_event = validate.enum(data, "anchor_event", ANCHOR_EVENTS)
    validate.require(data, "anchor_date")
    anchor_date = data["anchor_date"]
    if calc.parse_dt(anchor_date) is None:
        raise errors.err(errors.ERR_INVALID_REQUEST, "Invalid anchor_date")
    interval_days = validate.non_negative_int(data, "interval_days", required=True)
    counting_mode = validate.enum(data, "counting_mode", COUNTING_MODES)

    court = db.courts[case["court_id"]]
    rec = db.base_record()
    rec.update({
        "case_id": case_id,
        "deadline_type": deadline_type,
        "anchor_event": anchor_event,
        "anchor_date": anchor_date,
        "interval_days": interval_days,
        "counting_mode": counting_mode,
        "due_date": calc.due_date_calc(anchor_date, interval_days, counting_mode, court),
        "status": "PENDING",
        "parent_deadline_id": parent_deadline_id,
        "satisfied_by_filing_id": None,
    })
    db.deadlines[rec["id"]] = rec
    domain.bump_case(case)
    return success(domain._clean(rec), status=201)


@bp.get("/deadlines/<deadline_id>")
def get_deadline(deadline_id):
    get_actor()
    rec = domain.get_or_404(db.deadlines, deadline_id)
    return success(domain._clean(rec), status=200)


@bp.get("/deadlines")
def list_deadlines():
    get_actor()
    args = request.args
    items = list(db.deadlines.values())
    for field in ("case_id", "parent_deadline_id", "satisfied_by_filing_id", "deadline_type", "status"):
        val = args.get(field)
        if val is not None:
            items = [d for d in items if d.get(field) == val]
    window, pagination = domain.paginate(items, args)
    return success([domain._clean(d) for d in window], status=200, pagination=pagination)


@bp.post("/deadlines/<deadline_id>/satisfy")
def satisfy_deadline(deadline_id):
    _, role = get_actor()
    require_role(role, {"Clerk"})
    data = validate.body(request)
    d = domain.get_or_404(db.deadlines, deadline_id)
    case = db.cases[d["case_id"]]
    if d["status"] != "PENDING":
        raise errors.err(errors.ERR_INVALID_STATE, "Deadline is not PENDING")
    satisfied_by = data.get("satisfied_by_filing_id")
    if satisfied_by is not None:
        domain.get_or_404(db.filings, satisfied_by)
        d["satisfied_by_filing_id"] = satisfied_by
    d["status"] = "SATISFIED"
    db.touch(d)
    domain.bump_case(case)
    return success(domain._clean(d), status=200)


@bp.post("/deadlines/<deadline_id>/mark-missed")
def mark_missed(deadline_id):
    _, role = get_actor()
    require_role(role, {"Clerk"})
    d = domain.get_or_404(db.deadlines, deadline_id)
    case = db.cases[d["case_id"]]
    if d["status"] != "PENDING":
        raise errors.err(errors.ERR_INVALID_STATE, "Deadline is not PENDING")
    clock = db.now_clock()
    due = calc.parse_dt(d["due_date"])
    if not (clock > due):
        raise errors.err(errors.ERR_DEADLINE_NOT_YET_DUE, "Deadline is not yet due")
    d["status"] = "MISSED"
    db.touch(d)
    domain.bump_case(case)
    return success(domain._clean(d), status=200)


@bp.post("/deadlines/<deadline_id>/vacate")
def vacate_deadline(deadline_id):
    _, role = get_actor()
    require_role(role, {"Judge"})
    d = domain.get_or_404(db.deadlines, deadline_id)
    case = db.cases[d["case_id"]]
    if d["status"] != "PENDING":
        raise errors.err(errors.ERR_INVALID_STATE, "Deadline is not PENDING")
    d["status"] = "VACATED"
    db.touch(d)
    domain.bump_case(case)
    return success(domain._clean(d), status=200)
