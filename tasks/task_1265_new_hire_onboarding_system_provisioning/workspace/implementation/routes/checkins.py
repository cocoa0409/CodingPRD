"""CheckIn action endpoints (PRD §3.7)."""

from datetime import timedelta

from flask import Blueprint

from auth import require_roles
from db import store, clock
from errors import (ApiError, ERR_CHECKIN_NOT_FOUND, ERR_NOT_RESOURCE_OWNER,
                    ERR_INVALID_CHECKIN_STATE, ERR_CHECKIN_TOO_CLOSE,
                    ERR_CHECKIN_TIME_IN_PAST)
from helpers import touch, get_or_404, ser_checkin
from sweep import refresh_health, reeval_probation_gate
from util import (success, get_body, req_present, as_dt, as_opt_str,
                  as_rating, fmt_dt)

bp = Blueprint("checkins", __name__)

BUFFER = timedelta(minutes=30)


@bp.post("/api/check-ins/<cid>/complete")
def complete_checkin(cid):
    uid, role = require_roles("Buddy", "HiringManager")
    body = get_body()
    rating = body.get("productivity_rating")
    if rating is not None:
        rating = as_rating(rating, "productivity_rating")
    notes = as_opt_str(body.get("notes"), "notes")
    ci = get_or_404("checkins", cid, ERR_CHECKIN_NOT_FOUND, "CheckIn")
    # Stage 5: ownership — the owner acting in the role matching the kind
    if ci["owner_employee_id"] != uid or \
            (ci["kind"] == "MANAGER" and role != "HiringManager") or \
            (ci["kind"] == "BUDDY" and role != "Buddy"):
        raise ApiError(ERR_NOT_RESOURCE_OWNER, 403,
                       "Only the check-in owner acting in the matching role "
                       "may complete it")
    # Stage 6: only a SCHEDULED check-in can be completed (early is allowed)
    if ci["status"] != "SCHEDULED":
        raise ApiError(ERR_INVALID_CHECKIN_STATE, 409,
                       "complete requires a SCHEDULED check-in")
    now = clock.current
    ci["status"] = "COMPLETED"
    ci["_completed_dt"] = now
    ci["completed_at"] = fmt_dt(now)
    if rating is not None:
        ci["productivity_rating"] = rating
    if notes is not None:
        ci["notes"] = notes
    touch(ci)
    case = store["cases"].get(ci["case_id"])
    if case is not None:
        refresh_health(case)
        reeval_probation_gate(case)
        touch(case)
    return success(ser_checkin(ci))


@bp.post("/api/check-ins/<cid>/reschedule")
def reschedule_checkin(cid):
    require_roles("HRAdmin", "HiringManager")
    body = get_body()
    new_dt = as_dt(req_present(body, "scheduled_at"), "scheduled_at")
    ci = get_or_404("checkins", cid, ERR_CHECKIN_NOT_FOUND, "CheckIn")
    # Stage 6: state gate
    if ci["status"] not in ("SCHEDULED", "MISSED"):
        raise ApiError(ERR_INVALID_CHECKIN_STATE, 409,
                       "reschedule requires a SCHEDULED or MISSED check-in")
    # Stage 9: thirty-minute buffer per owner — every other check-in of the
    # same owner in SCHEDULED or COMPLETED must sit >= 30 minutes away
    # (exactly 30 minutes is permitted).
    for other in store["checkins"].values():
        if other["id"] == ci["id"] or \
                other["owner_employee_id"] != ci["owner_employee_id"] or \
                other["status"] not in ("SCHEDULED", "COMPLETED"):
            continue
        if abs(new_dt - other["_sched_dt"]) < BUFFER:
            raise ApiError(ERR_CHECKIN_TOO_CLOSE, 409,
                           "Check-in conflicts with the owner's 30-minute "
                           "buffer")
    # Stage 10: the new time must lie in the future of the logical clock
    if new_dt <= clock.current:
        raise ApiError(ERR_CHECKIN_TIME_IN_PAST, 409,
                       "scheduled_at must be in the future")
    ci["_sched_dt"] = new_dt
    ci["scheduled_at"] = fmt_dt(new_dt)
    ci["status"] = "SCHEDULED"
    touch(ci)
    case = store["cases"].get(ci["case_id"])
    if case is not None:
        refresh_health(case)  # a rescued MISSED check-in restores health
        touch(case)
    return success(ser_checkin(ci))
