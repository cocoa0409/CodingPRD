"""Discovery calls and the fit gate (PRD §3.2, §2.9)."""
from flask import Blueprint, request

from auth import authenticate, require_role, require_ownership, body, get_str, get_int
from db import store
from engine import discovery_call_overlap
from envelope import success, success_list, paginate
from errors import (ApiError, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
                    ERR_DUPLICATE_RESOURCE, ERR_SEGREGATION_OF_DUTIES,
                    ERR_DISCOVERY_CALL_OVERLAP, not_found)
from serializers import (discovery_call as ser_call, fit_assessment as ser_fit,
                         base_row, append_row, touch)
from timeutil import parse_datetime, now
from datetime import timedelta

bp = Blueprint("discovery", __name__)

SCOPE_FITS = ("WITHIN_SCOPE", "OUTSIDE_SCOPE")


@bp.post("/discovery-calls")
def book_call():
    role, uid = authenticate()
    require_role(role, uid, ("Client", "PracticeManager"))
    b = body()
    client_id = b.get("client_id")
    coach_id = b.get("coach_id")
    if role == "Client":
        require_ownership(client_id if isinstance(client_id, str) else None, uid)
    # Body FK references in declared order: client_id, then coach_id.
    if not isinstance(client_id, str) or client_id not in store.clients:
        raise not_found("client_id does not reference an existing client")
    if not isinstance(coach_id, str) or coach_id not in store.coaches:
        raise not_found("coach_id does not reference an existing coach")
    start = parse_datetime(b.get("scheduled_start"))
    duration = get_int(b, "duration_minutes")
    # Priority 9: closed-interval collision, no buffer, touching endpoints collide.
    if start is not None and duration is not None and duration >= 1:
        if discovery_call_overlap(coach_id, start, duration):
            raise ApiError(ERR_DISCOVERY_CALL_OVERLAP, 409,
                           "Discovery call collides with another SCHEDULED call for this coach")
    # Priority 20: request shape.
    if start is None or duration is None or duration < 15:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "Required: scheduled_start (ISO 8601), duration_minutes >= 15")
    d = base_row()
    d.update({
        "client_id": client_id,
        "coach_id": coach_id,
        "scheduled_start": start,
        "duration_minutes": duration,
        "call_status": "SCHEDULED",
    })
    store.discovery_calls[d["id"]] = d
    return success(ser_call(d)), 201


@bp.get("/discovery-calls/<did>")
def get_call(did):
    role, uid = authenticate()
    require_role(role, uid, ("PlatformAdmin", "PracticeManager", "Coach", "Client"))
    d = store.discovery_calls.get(did)
    if d is None:
        raise not_found("DiscoveryCall not found")
    return success(ser_call(d))


@bp.get("/discovery-calls")
def list_calls():
    role, uid = authenticate()
    require_role(role, uid, ("PlatformAdmin", "PracticeManager", "Coach", "Client"))
    rows = list(store.discovery_calls.values())
    client_id = request.args.get("client_id")
    coach_id = request.args.get("coach_id")
    if client_id is not None:
        rows = [d for d in rows if d["client_id"] == client_id]
    if coach_id is not None:
        rows = [d for d in rows if d["coach_id"] == coach_id]
    rows.sort(key=lambda d: (d["created_at"], d["_created_sort"]))
    page, meta = paginate(rows)
    return success_list([ser_call(d) for d in page], meta)


@bp.post("/discovery-calls/<did>/complete")
def complete_call(did):
    role, uid = authenticate()
    require_role(role, uid, ("Coach",))
    d = store.discovery_calls.get(did)
    if d is None:
        raise not_found("DiscoveryCall not found")
    require_ownership(d["coach_id"], uid)
    if d["call_status"] != "SCHEDULED":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a SCHEDULED call can be completed")
    if now() < d["scheduled_start"]:
        raise ApiError(ERR_INVALID_STATE, 409,
                       "The current time has not reached the scheduled start")
    d["call_status"] = "COMPLETED"
    touch(d)
    return success(ser_call(d))


@bp.post("/discovery-calls/<did>/mark-no-show")
def no_show_call(did):
    role, uid = authenticate()
    require_role(role, uid, ("Coach",))
    d = store.discovery_calls.get(did)
    if d is None:
        raise not_found("DiscoveryCall not found")
    require_ownership(d["coach_id"], uid)
    if d["call_status"] != "SCHEDULED":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a SCHEDULED call can be marked NO_SHOW")
    if now() < d["scheduled_start"] + timedelta(minutes=d["duration_minutes"]):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "The call window (start + duration) has not yet passed")
    d["call_status"] = "NO_SHOW"
    touch(d)
    return success(ser_call(d))


@bp.put("/discovery-calls/<did>")
def reschedule_call(did):
    """NO_SHOW -> SCHEDULED, the machine's only cycle (PRD §3.2)."""
    role, uid = authenticate()
    require_role(role, uid, ("Client",))
    d = store.discovery_calls.get(did)
    if d is None:
        raise not_found("DiscoveryCall not found")
    require_ownership(d["client_id"], uid)
    if d["call_status"] != "NO_SHOW":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only a NO_SHOW call can be rescheduled")
    start = parse_datetime(body().get("scheduled_start"))
    if start is not None and start <= now():
        raise ApiError(ERR_INVALID_STATE, 409,
                       "The new scheduled_start must lie strictly in the future")
    if start is not None and discovery_call_overlap(
            d["coach_id"], start, d["duration_minutes"], exclude_call_id=d["id"]):
        raise ApiError(ERR_DISCOVERY_CALL_OVERLAP, 409,
                       "Discovery call collides with another SCHEDULED call for this coach")
    if start is None:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "scheduled_start must be a valid ISO 8601 datetime")
    d["scheduled_start"] = start
    d["call_status"] = "SCHEDULED"
    touch(d)
    return success(ser_call(d))


@bp.post("/discovery-calls/<did>/cancel")
def cancel_call(did):
    role, uid = authenticate()
    require_role(role, uid, ("Client",))
    d = store.discovery_calls.get(did)
    if d is None:
        raise not_found("DiscoveryCall not found")
    require_ownership(d["client_id"], uid)
    if d["call_status"] != "SCHEDULED":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a SCHEDULED call can be cancelled")
    d["call_status"] = "CANCELLED"
    touch(d)
    return success(ser_call(d))


@bp.post("/discovery-calls/<did>/fit-assessment")
def create_fit_assessment(did):
    """Fit is graded by a second coach — never the one who took the call
    (segregation of duties, PRD §2.7/§3.2). Outcome is computed at creation."""
    role, uid = authenticate()
    require_role(role, uid, ("Coach",))
    d = store.discovery_calls.get(did)
    if d is None:
        raise not_found("DiscoveryCall not found")
    if d["call_status"] != "COMPLETED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Fit assessment requires a COMPLETED discovery call")
    if any(f["discovery_call_id"] == did for f in store.fit_assessments.values()):
        raise ApiError(ERR_DUPLICATE_RESOURCE, 409,
                       "A discovery call carries at most one fit assessment")
    if uid == d["coach_id"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, 422,
                       "The coach who took the call may not grade its fit")
    b = body()
    scope_fit = b.get("scope_fit")
    commitment = get_int(b, "commitment_score")
    if (scope_fit not in SCOPE_FITS
            or commitment is None or commitment < 0 or commitment > 100):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "Required: scope_fit in {WITHIN_SCOPE,OUTSIDE_SCOPE}, commitment_score 0..100")
    f = append_row()
    f.update({
        "discovery_call_id": did,
        "scope_fit": scope_fit,
        "commitment_score": commitment,
        "outcome": "REFER_OUT" if scope_fit == "OUTSIDE_SCOPE" else "PROCEED",
        "assessor_coach_id": uid,
    })
    store.fit_assessments[f["id"]] = f
    return success(ser_fit(f)), 201


@bp.get("/discovery-calls/<did>/fit-assessment")
def get_fit_assessment(did):
    role, uid = authenticate()
    require_role(role, uid, ("PlatformAdmin", "PracticeManager", "Coach", "Client"))
    d = store.discovery_calls.get(did)
    if d is None:
        raise not_found("DiscoveryCall not found")
    rows = [f for f in store.fit_assessments.values() if f["discovery_call_id"] == did]
    rows.sort(key=lambda f: (f["created_at"], f["_created_sort"]))
    page, meta = paginate(rows)
    return success_list([ser_fit(f) for f in page], meta)
