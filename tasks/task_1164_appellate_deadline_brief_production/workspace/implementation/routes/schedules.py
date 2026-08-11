"""Briefing schedule endpoints (PRD §3.4)."""
from flask import Blueprint

from db import STORE
from errors import ApiError
from middleware import get_auth, require_roles
from response import success_object, success_list
from services.core import (
    get_body, req_int, paginate, touch, path_case, path_schedule,
    briefs_for_schedule, deadlines_for_case,
)
from services.workflows import reconcile_case

bp = Blueprint("schedules", __name__)

ALL = ("CourtAdmin", "Attorney", "CourtClerk", "ParalegalStaff")
TERMINAL_SCHEDULE = ("COMPLETE", "VACATED")
BRIEF_DEADLINE_KINDS = ("OPENING_BRIEF", "RESPONSE_BRIEF", "REPLY_BRIEF")


@bp.get("/appellate/cases/<cid>/briefing-schedule")
def get_case_schedule(cid):
    auth = get_auth()
    require_roles(auth, ALL)
    case = path_case(cid)
    reconcile_case(case)
    items = [s for s in STORE.briefing_schedules.values() if s["case_id"] == case["id"]]
    page, limit, offset, total = paginate(items)
    return success_list(page, limit, offset, total)


@bp.get("/appellate/briefing-schedules/<sid>")
def get_schedule(sid):
    auth = get_auth()
    require_roles(auth, ALL)
    s = path_schedule(sid)
    case = STORE.cases.get(s["case_id"])
    if case is not None:
        reconcile_case(case)
    out = dict(s)
    out.pop("_seq", None)
    return success_object(out)


@bp.post("/appellate/briefing-schedules/<sid>/vacate")
def vacate_schedule(sid):
    auth = get_auth()
    require_roles(auth, ("CourtClerk", "CourtAdmin"))
    s = path_schedule(sid)
    if s["status"] in TERMINAL_SCHEDULE:
        raise ApiError("ERR_ALREADY_TERMINAL", "Schedule is in a terminal state", 409)

    body = get_body()
    expected = req_int(body, "expected_case_version")
    case = STORE.cases.get(s["case_id"])
    if not case:
        raise ApiError("ERR_NOT_FOUND", "Parent case not found", 404)

    # State validity (priority 5)
    if s["status"] == "ACTIVE":
        blocking = [b for b in briefs_for_schedule(s["id"])
                    if b["status"] in ("EFILED", "ACCEPTED")]
        if blocking:
            raise ApiError("ERR_INVALID_STATE",
                           "Cannot vacate: briefs already e-filed or accepted", 409)
    elif s["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE",
                       "Schedule cannot be vacated from its current state", 409)

    # OCC check (priority 15)
    if case["version"] != expected:
        raise ApiError("ERR_STALE_VERSION",
                       "expected_case_version does not match current case version", 412)

    # Side effects: briefs -> DRAFT, brief deadlines unmet
    for b in briefs_for_schedule(s["id"]):
        if b["status"] != "DRAFT":
            b["status"] = "DRAFT"
            touch(b)
    for d in deadlines_for_case(case["id"]):
        if d["kind"] in BRIEF_DEADLINE_KINDS and d["met"]:
            d["met"] = False
            d["met_at"] = None
            touch(d)
    s["status"] = "VACATED"
    touch(s)
    touch(case)
    out = dict(s)
    out.pop("_seq", None)
    return success_object(out)
