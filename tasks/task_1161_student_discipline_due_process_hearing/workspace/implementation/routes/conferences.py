"""Parent conferences (PRD §3.4)."""
from flask import Blueprint

from db import db, stamp, touch, serialize
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_CONFERENCE_DEADLINE_PASSED,
    ERR_CONFERENCE_ATTEMPT_LIMIT,
)
from middleware import endpoint
from response import success
from routes.common import get_or_404, guardian_owns, render_list
from services.calc import current_issued_notice
from util import parse_dt

bp = Blueprint("conferences", __name__)


@bp.post("/cases/<cid>/conferences")
@endpoint("SchoolAdministrator")
def create_conference(ctx, cid):
    case = get_or_404(db.cases, cid, "case")
    scheduled_at = parse_dt(ctx.body.get("scheduled_at"))
    if scheduled_at is None:
        raise_err(ERR_INVALID_REQUEST, "scheduled_at must be a valid ISO 8601 timestamp")
    if case["status"] != "NOTICE_ISSUED":
        raise_err(ERR_INVALID_STATE, "case must be NOTICE_ISSUED to schedule a conference")
    notice = current_issued_notice(cid)
    if notice is None:
        raise_err(ERR_INVALID_STATE, "case has no issued notice")
    if scheduled_at > notice["conference_deadline"]:
        raise_err(ERR_CONFERENCE_DEADLINE_PASSED, "scheduled_at exceeds the conference deadline")

    conf = stamp(
        {
            "case_id": cid,
            "scheduled_at": scheduled_at,
            "attempt_number": 1,
            "status": "SCHEDULED",
        }
    )
    db.conferences[conf["id"]] = conf
    return success(serialize(conf), 201)


@bp.get("/cases/<cid>/conferences")
@endpoint("DistrictAdmin", "SchoolAdministrator", "ParentGuardian")
def list_conferences(ctx, cid):
    case = get_or_404(db.cases, cid, "case")
    if ctx.role == "ParentGuardian":
        guardian_owns(ctx, db.students[case["student_id"]])
    confs = {k: v for k, v in db.conferences.items() if v["case_id"] == cid}
    return render_list(confs)


@bp.post("/conferences/<cid>/outcome")
@endpoint("SchoolAdministrator")
def conference_outcome(ctx, cid):
    conf = get_or_404(db.conferences, cid, "conference")
    outcome = ctx.body.get("outcome")
    if outcome not in ("HELD", "WAIVED", "NO_SHOW"):
        raise_err(ERR_INVALID_REQUEST, "outcome must be HELD, WAIVED, or NO_SHOW")
    if conf["status"] != "SCHEDULED":
        raise_err(ERR_INVALID_STATE, "conference is not SCHEDULED")
    conf["status"] = outcome
    touch(conf)
    return success(serialize(conf))


@bp.post("/conferences/<cid>/reschedule")
@endpoint("SchoolAdministrator")
def conference_reschedule(ctx, cid):
    conf = get_or_404(db.conferences, cid, "conference")
    scheduled_at = parse_dt(ctx.body.get("scheduled_at"))
    if scheduled_at is None:
        raise_err(ERR_INVALID_REQUEST, "scheduled_at must be a valid ISO 8601 timestamp")
    if conf["status"] != "NO_SHOW":
        raise_err(ERR_INVALID_STATE, "only a NO_SHOW conference may be rescheduled")
    notice = current_issued_notice(conf["case_id"])
    if notice is None:
        raise_err(ERR_INVALID_STATE, "case has no issued notice")
    # Deadline window (rung 10) precedes the attempt cap (rung 11) per PRD §2.9
    if scheduled_at > notice["conference_deadline"]:
        raise_err(ERR_CONFERENCE_DEADLINE_PASSED, "scheduled_at exceeds the conference deadline")
    if conf["attempt_number"] >= 2:
        raise_err(ERR_CONFERENCE_ATTEMPT_LIMIT, "conference attempt cap (2) reached")
    conf["attempt_number"] += 1
    conf["scheduled_at"] = scheduled_at
    conf["status"] = "SCHEDULED"
    touch(conf)
    return success(serialize(conf))
