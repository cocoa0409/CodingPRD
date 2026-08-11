"""Oral argument endpoints (PRD §3.7)."""
from datetime import timedelta

from flask import Blueprint, request

from db import STORE, now_iso, parse_iso
from errors import ApiError
from middleware import get_auth, require_roles
from response import success_object, success_list
from services.core import (
    get_body, req_iso, req_int, req_str_list, new_entity, paginate, touch,
    path_case, path_argument, court_for_case,
)

bp = Blueprint("arguments", __name__)

ALL = ("CourtAdmin", "Attorney", "CourtClerk", "ParalegalStaff")
TERMINAL_ARGUMENT = ("HELD", "WAIVED")
DEFAULT_ARGUMENT_NOTICE_DAYS = 14


@bp.post("/appellate/cases/<cid>/oral-arguments")
def create_argument(cid):
    auth = get_auth()
    require_roles(auth, ("Attorney", "CourtClerk"))
    case = path_case(cid)
    body = get_body()
    start = req_iso(body, "scheduled_start")
    duration = req_int(body, "duration_minutes")
    if duration <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "duration_minutes must be > 0", 400)
    panel = req_str_list(body, "panel_judges")
    oa = new_entity({
        "case_id": case["id"],
        "scheduled_start": start,
        "duration_minutes": duration,
        "panel_judges": panel,
        "moot_completed": False,
        "status": "REQUESTED",
    })
    STORE.oral_arguments[oa["id"]] = oa
    out = dict(oa)
    out.pop("_seq", None)
    return success_object(out, 201)


@bp.get("/appellate/cases/<cid>/oral-arguments")
def list_case_arguments(cid):
    auth = get_auth()
    require_roles(auth, ALL)
    case = path_case(cid)
    items = [o for o in STORE.oral_arguments.values() if o["case_id"] == case["id"]]
    st = request.args.get("status")
    if st is not None:
        items = [o for o in items if o["status"] == st]
    page, limit, offset, total = paginate(items)
    return success_list(page, limit, offset, total)


@bp.get("/appellate/oral-arguments/<aid>")
def get_argument(aid):
    auth = get_auth()
    require_roles(auth, ALL)
    oa = path_argument(aid)
    out = dict(oa)
    out.pop("_seq", None)
    return success_object(out)


@bp.post("/appellate/oral-arguments/<aid>/schedule")
def schedule_argument(aid):
    auth = get_auth()
    require_roles(auth, ("CourtClerk",))
    oa = path_argument(aid)
    if oa["status"] in TERMINAL_ARGUMENT:
        raise ApiError("ERR_ALREADY_TERMINAL", "Oral argument is terminal", 409)
    # Priority 5: state
    if oa["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE",
                       "Oral argument must be REQUESTED to schedule", 409)
    case = STORE.cases.get(oa["case_id"])
    if case is not None:
        from services.workflows import reconcile_case
        reconcile_case(case)
    court = court_for_case(case) if case else None
    if not case or case.get("posture") != "ARGUMENT_PENDING":
        raise ApiError("ERR_INVALID_STATE",
                       "Case posture must be ARGUMENT_PENDING", 409)
    body = get_body()
    start_iso = req_iso(body, "scheduled_start")
    duration = req_int(body, "duration_minutes")
    if duration <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "duration_minutes must be > 0", 400)

    new_start = parse_iso(start_iso)
    new_end = new_start + timedelta(minutes=duration)

    # Priority 12: overlap check (half-open intervals, same court, SCHEDULED/HELD)
    for other in STORE.oral_arguments.values():
        if other["id"] == oa["id"]:
            continue
        other_case = STORE.cases.get(other["case_id"])
        if not other_case or other_case["court_id"] != case["court_id"]:
            continue
        if other["status"] not in ("SCHEDULED", "HELD"):
            continue
        if not other.get("scheduled_start") or not other.get("duration_minutes"):
            continue
        ex_start = parse_iso(other["scheduled_start"])
        ex_end = ex_start + timedelta(minutes=other["duration_minutes"])
        if new_start < ex_end and ex_start < new_end:
            raise ApiError("ERR_ARGUMENT_OVERLAP",
                           "Proposed argument interval overlaps an existing argument", 409)

    # Priority 13: minimum notice window
    notice_days = (court or {}).get("argument_notice_days", DEFAULT_ARGUMENT_NOTICE_DAYS)
    earliest = parse_iso(now_iso()) + timedelta(days=notice_days)
    if new_start < earliest:
        raise ApiError("ERR_ARGUMENT_NOTICE_TOO_SHORT",
                       "Argument scheduled inside the court's minimum notice window", 422)

    oa["scheduled_start"] = start_iso
    oa["duration_minutes"] = duration
    oa["status"] = "SCHEDULED"
    touch(oa)
    out = dict(oa)
    out.pop("_seq", None)
    return success_object(out)


@bp.post("/appellate/oral-arguments/<aid>/mark-held")
def mark_held(aid):
    auth = get_auth()
    require_roles(auth, ("CourtClerk",))
    oa = path_argument(aid)
    if oa["status"] in TERMINAL_ARGUMENT:
        raise ApiError("ERR_ALREADY_TERMINAL", "Oral argument is terminal", 409)
    if oa["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE",
                       "Oral argument must be SCHEDULED to mark held", 409)
    if not oa.get("scheduled_start"):
        raise ApiError("ERR_INVALID_STATE", "Oral argument has no scheduled start", 409)
    if parse_iso(now_iso()) < parse_iso(oa["scheduled_start"]):
        raise ApiError("ERR_INVALID_STATE",
                       "Cannot mark held before the scheduled start", 409)
    oa["status"] = "HELD"
    touch(oa)
    out = dict(oa)
    out.pop("_seq", None)
    return success_object(out)


@bp.post("/appellate/oral-arguments/<aid>/continue")
def continue_argument(aid):
    auth = get_auth()
    require_roles(auth, ("CourtClerk",))
    oa = path_argument(aid)
    if oa["status"] in TERMINAL_ARGUMENT:
        raise ApiError("ERR_ALREADY_TERMINAL", "Oral argument is terminal", 409)
    if oa["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE",
                       "Oral argument must be SCHEDULED to continue", 409)
    if oa.get("scheduled_start") and parse_iso(now_iso()) >= parse_iso(oa["scheduled_start"]):
        raise ApiError("ERR_INVALID_STATE",
                       "Cannot continue an argument whose start has arrived", 409)
    # Passes through CONTINUED and cycles back to REQUESTED
    oa["status"] = "REQUESTED"
    oa["scheduled_start"] = None
    touch(oa)
    out = dict(oa)
    out.pop("_seq", None)
    return success_object(out)


@bp.post("/appellate/oral-arguments/<aid>/waive")
def waive_argument(aid):
    auth = get_auth()
    require_roles(auth, ("Attorney",))
    oa = path_argument(aid)
    if oa["status"] in TERMINAL_ARGUMENT:
        raise ApiError("ERR_ALREADY_TERMINAL", "Oral argument is terminal", 409)
    if oa["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE",
                       "Oral argument must be REQUESTED to waive", 409)
    case = STORE.cases.get(oa["case_id"])
    if not case or case.get("lead_attorney_id") != auth.user_id:
        raise ApiError("ERR_FORBIDDEN_ROLE",
                       "Only the lead attorney may waive oral argument", 403)
    oa["status"] = "WAIVED"
    touch(oa)
    out = dict(oa)
    out.pop("_seq", None)
    return success_object(out)


@bp.post("/appellate/oral-arguments/<aid>/log-moot")
def log_moot(aid):
    auth = get_auth()
    require_roles(auth, ("Attorney", "ParalegalStaff"))
    oa = path_argument(aid)
    if oa["status"] in TERMINAL_ARGUMENT:
        raise ApiError("ERR_ALREADY_TERMINAL", "Oral argument is terminal", 409)
    oa["moot_completed"] = True
    touch(oa)
    out = dict(oa)
    out.pop("_seq", None)
    return success_object(out)
