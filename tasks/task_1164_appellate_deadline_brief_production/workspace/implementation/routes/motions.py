"""Extension motion endpoints (PRD §3.4)."""
from flask import Blueprint, request

from db import STORE, now_iso
from errors import ApiError
from middleware import get_auth, require_roles
from response import success_object, success_list
from services.core import (
    get_body, req_str, req_int, req_enum, new_entity, paginate, touch,
    path_case, path_motion, path_schedule, fk_schedule,
    briefs_for_schedule, deadlines_for_case, add_calendar_days,
    schedule_due_for_brief_type, granted_motions_for_schedule,
    compute_schedule_dates, court_for_case,
)
from services.workflows import BRIEF_TYPE_TO_DEADLINE_KIND

bp = Blueprint("motions", __name__)

ALL = ("CourtAdmin", "Attorney", "CourtClerk", "ParalegalStaff")
MOTION_TARGETS = ("OPENING", "RESPONSE", "REPLY")
TERMINAL_MOTION = ("GRANTED", "DENIED", "WITHDRAWN")


@bp.post("/appellate/cases/<cid>/extension-motions")
def create_motion(cid):
    auth = get_auth()
    require_roles(auth, ("Attorney",))
    case = path_case(cid)
    body = get_body()
    schedule = fk_schedule(body.get("schedule_id"))
    target = req_enum(body, "target", MOTION_TARGETS)
    requested = req_int(body, "requested_days")
    reason = req_str(body, "reason")
    if requested <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "requested_days must be > 0", 400)
    if schedule["case_id"] != case["id"]:
        raise ApiError("ERR_FK_NOT_FOUND",
                       "schedule_id does not belong to this case", 404)
    m = new_entity({
        "case_id": case["id"],
        "schedule_id": schedule["id"],
        "target": target,
        "requested_days": requested,
        "reason": reason,
        "granted_days": 0,
        "status": "PENDING",
        "decided_at": None,
    })
    STORE.extension_motions[m["id"]] = m
    out = dict(m)
    out.pop("_seq", None)
    return success_object(out, 201)


def _list_motions(items):
    st = request.args.get("status")
    if st is not None:
        items = [m for m in items if m["status"] == st]
    tgt = request.args.get("target")
    if tgt is not None:
        items = [m for m in items if m["target"] == tgt]
    sid = request.args.get("schedule_id")
    if sid is not None:
        items = [m for m in items if m["schedule_id"] == sid]
    return paginate(items)


@bp.get("/appellate/cases/<cid>/extension-motions")
def list_case_motions(cid):
    auth = get_auth()
    require_roles(auth, ALL)
    case = path_case(cid)
    items = [m for m in STORE.extension_motions.values() if m["case_id"] == case["id"]]
    page, limit, offset, total = _list_motions(items)
    return success_list(page, limit, offset, total)


@bp.get("/appellate/extension-motions/<mid>")
def get_motion(mid):
    auth = get_auth()
    require_roles(auth, ALL)
    m = path_motion(mid)
    out = dict(m)
    out.pop("_seq", None)
    return success_object(out)


@bp.get("/appellate/extension-motions")
def list_motions():
    auth = get_auth()
    require_roles(auth, ALL)
    page, limit, offset, total = _list_motions(list(STORE.extension_motions.values()))
    return success_list(page, limit, offset, total)


@bp.get("/appellate/briefing-schedules/<sid>/extension-motions")
def list_schedule_motions(sid):
    auth = get_auth()
    require_roles(auth, ALL)
    schedule = path_schedule(sid)
    items = [m for m in STORE.extension_motions.values()
             if m["schedule_id"] == schedule["id"]]
    page, limit, offset, total = _list_motions(items)
    return success_list(page, limit, offset, total)


@bp.post("/appellate/extension-motions/<mid>/grant")
def grant_motion(mid):
    auth = get_auth()
    require_roles(auth, ("CourtClerk",))
    m = path_motion(mid)
    if m["status"] in TERMINAL_MOTION:
        raise ApiError("ERR_ALREADY_TERMINAL", "Motion is in a terminal state", 409)

    body = get_body()
    granted = req_int(body, "granted_days")
    expected_sched = req_int(body, "expected_schedule_version")
    schedule = STORE.briefing_schedules.get(m["schedule_id"])
    if not schedule:
        raise ApiError("ERR_NOT_FOUND", "Briefing schedule not found", 404)

    # Priority 5: state
    if m["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", "Motion must be PENDING to grant", 409)
    # Priority 14: grant-days validity (0 < granted <= requested)
    if granted <= 0 or granted > m["requested_days"]:
        raise ApiError("ERR_GRANT_DAYS_INVALID",
                       "granted_days must satisfy 0 < granted_days <= requested_days", 422)
    # Schedule must be ACTIVE (state)
    if schedule["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE",
                       "Briefing schedule must be ACTIVE to grant extension", 409)
    # Priority 15: OCC
    if schedule["version"] != expected_sched:
        raise ApiError("ERR_STALE_VERSION",
                       "expected_schedule_version does not match current schedule version", 412)

    # Apply
    m["granted_days"] = granted
    m["decided_at"] = now_iso()
    m["status"] = "GRANTED"
    touch(m)

    # Cascade shift: recompute schedule dates from anchor + all granted motions
    case = STORE.cases.get(schedule["case_id"])
    court = court_for_case(case) if case else None
    # Recompute from anchor to keep multi-motion ordering deterministic
    rec = None
    for r in STORE.records.values():
        if r["case_id"] == schedule["case_id"]:
            rec = r
            break
    anchor = (rec or {}).get("completed_at") or schedule.get("updated_at") or now_iso()
    opening, response, reply = compute_schedule_dates(
        anchor, court, granted_motions_for_schedule(schedule["id"]))
    schedule["opening_due_at"] = opening
    schedule["response_due_at"] = response
    schedule["reply_due_at"] = reply
    schedule["extensions_granted_count"] = schedule.get("extensions_granted_count", 0) + 1
    touch(schedule)

    # Recompute Brief.due_at for affected brief types (target + cascades)
    affected = {"REPLY": ["REPLY"],
                "RESPONSE": ["RESPONSE", "REPLY"],
                "OPENING": ["OPENING", "RESPONSE", "REPLY"]}[m["target"]]
    for b in briefs_for_schedule(schedule["id"]):
        if b["brief_type"] in affected:
            b["due_at"] = schedule_due_for_brief_type(schedule, b["brief_type"])
            touch(b)

    # Deadline rows of matching kind: final = provisional + sum(granted days of
    # all granted motions whose cascade reaches this kind). SCAFFOLD §3.4:
    # "Deadline rows of kind matching target: recompute final_due_at =
    # provisional_due_at + sum(granted_days)".
    kind = BRIEF_TYPE_TO_DEADLINE_KIND.get(m["target"])
    if kind and case:
        granted_all = granted_motions_for_schedule(schedule["id"])
        for d in deadlines_for_case(case["id"]):
            if d["kind"] != kind:
                continue
            total = 0
            for gm in granted_all:
                if gm["target"] == "OPENING" and kind in ("OPENING_BRIEF", "RESPONSE_BRIEF", "REPLY_BRIEF"):
                    total += gm["granted_days"]
                elif gm["target"] == "RESPONSE" and kind in ("RESPONSE_BRIEF", "REPLY_BRIEF"):
                    total += gm["granted_days"]
                elif gm["target"] == "REPLY" and kind == "REPLY_BRIEF":
                    total += gm["granted_days"]
            d["final_due_at"] = add_calendar_days(d["provisional_due_at"], total)
            touch(d)

    out = dict(m)
    out.pop("_seq", None)
    return success_object(out)


@bp.post("/appellate/extension-motions/<mid>/deny")
def deny_motion(mid):
    auth = get_auth()
    require_roles(auth, ("CourtClerk",))
    m = path_motion(mid)
    if m["status"] in TERMINAL_MOTION:
        raise ApiError("ERR_ALREADY_TERMINAL", "Motion is in a terminal state", 409)
    if m["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", "Motion must be PENDING to deny", 409)
    m["granted_days"] = 0
    m["decided_at"] = now_iso()
    m["status"] = "DENIED"
    touch(m)
    out = dict(m)
    out.pop("_seq", None)
    return success_object(out)


@bp.post("/appellate/extension-motions/<mid>/withdraw")
def withdraw_motion(mid):
    auth = get_auth()
    require_roles(auth, ("Attorney",))
    m = path_motion(mid)
    if m["status"] in TERMINAL_MOTION:
        raise ApiError("ERR_ALREADY_TERMINAL", "Motion is in a terminal state", 409)
    if m["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", "Motion must be PENDING to withdraw", 409)
    case = STORE.cases.get(m["case_id"])
    if not case or case.get("lead_attorney_id") != auth.user_id:
        raise ApiError("ERR_FORBIDDEN_ROLE",
                       "Only the lead attorney on the case may withdraw the motion", 403)
    m["decided_at"] = now_iso()
    m["status"] = "WITHDRAWN"
    touch(m)
    out = dict(m)
    out.pop("_seq", None)
    return success_object(out)
