"""Hearing and Witness endpoints: scheduling (dockets the appeal), witness
prep ladder, continuances with re-validation, and holding the hearing."""
from datetime import timedelta

from flask import Blueprint

from db import STORE
from errors import (
    err,
    ERR_APPEAL_NOT_DOCKETABLE,
    ERR_CONTINUANCE_LIMIT,
    ERR_CROSS_PARENT_REFERENCE,
    ERR_HEARING_NOT_READY,
    ERR_INVALID_STATE,
    ERR_REFEREE_DOUBLE_BOOKED,
    ERR_WINDOW_VIOLATION,
    ERR_WITNESS_UNAVAILABLE,
)
from middleware import require_roles
from response import paginate, success
from services.core import find_or_404, new_record, serialize, sorted_created, touch
from util import as_dt, as_str, body_json, check_enum, req

bp = Blueprint("hearings", __name__)

WITNESS_ROLES = ("DIRECT_SUPERVISOR", "HR_CUSTODIAN", "POLICY_AUTHOR", "CLAIMANT", "OTHER")
REFEREE_BUSY_STATUSES = ("SCHEDULED", "HELD")
BUFFER = timedelta(minutes=30)
PREP_LADDER = ("UNPREPARED", "BRIEFED", "EXHIBITS_REVIEWED", "READY")


def _check_referee_buffer(referee_id, start, end, exclude_hearing_id=None):
    """The same referee may hold no other SCHEDULED or HELD hearing whose
    interval, expanded by 30 minutes on both sides, intersects the new one
    (closed-closed intersection)."""
    for h in STORE.hearings.values():
        if h["referee_id"] != referee_id or h["status"] not in REFEREE_BUSY_STATUSES:
            continue
        if exclude_hearing_id is not None and h["id"] == exclude_hearing_id:
            continue
        other_start = h["scheduled_start"] - BUFFER
        other_end = h["scheduled_end"] + BUFFER
        if other_start <= end and other_end >= start:
            raise err(ERR_REFEREE_DOUBLE_BOOKED, 409, "referee has a hearing within the 30-minute buffer")


def _check_witnesses_contain(hearing, start, end):
    """Every witness's availability window must contain the hearing interval."""
    for w in STORE.witnesses.values():
        if w["hearing_id"] != hearing["id"]:
            continue
        if w["availability_start"] > start or w["availability_end"] < end:
            raise err(ERR_WITNESS_UNAVAILABLE, 409, "witness availability does not contain the new interval")


def _auto_ready(hearing):
    """PREP_IN_PROGRESS -> READY when at least one witness exists and every
    witness has reached READY."""
    witnesses = [w for w in STORE.witnesses.values() if w["hearing_id"] == hearing["id"]]
    if witnesses and all(w["prep_status"] == "READY" for w in witnesses):
        if hearing["status"] in ("SCHEDULED", "PREP_IN_PROGRESS"):
            hearing["status"] = "READY"
            touch(hearing)


@bp.post("/ui/appeals/<aid>/hearings")
def schedule_hearing(aid):
    require_roles("ClaimsAnalyst")
    body = body_json()
    claim_id = as_str(req(body, "claim_id"), "claim_id")
    scheduled_start = as_dt(req(body, "scheduled_start"), "scheduled_start")
    scheduled_end = as_dt(req(body, "scheduled_end"), "scheduled_end")
    referee_id = as_str(req(body, "referee_id"), "referee_id")
    location = as_str(req(body, "location"), "location")

    appeal = find_or_404(STORE.appeals, aid, "appeal")
    claim = find_or_404(STORE.claims, claim_id, "claim")
    det = STORE.determinations.get(appeal["determination_id"])
    if det is None or det["claim_id"] != claim_id:
        raise err(
            ERR_CROSS_PARENT_REFERENCE,
            422,
            "claim_id does not match the appeal's adjudicated claim",
        )
    if appeal["status"] != "FILED":
        raise err(ERR_APPEAL_NOT_DOCKETABLE, 409, "appeal is not FILED")
    if scheduled_end <= scheduled_start:
        raise err(ERR_WINDOW_VIOLATION, 422, "scheduled_end must be strictly after scheduled_start")
    _check_referee_buffer(referee_id, scheduled_start, scheduled_end)

    rec = new_record({
        "appeal_id": aid,
        "claim_id": claim_id,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "referee_id": referee_id,
        "location": location,
        "continuance_count": 0,
        "status": "SCHEDULED",
    })
    STORE.hearings[rec["id"]] = rec
    appeal["status"] = "DOCKETED"
    touch(appeal)
    return success(serialize(rec), 201)


@bp.get("/ui/hearings/<rid>")
def get_hearing(rid):
    require_roles("PlatformAdmin", "ClaimsAnalyst", "AgencyLiaison")
    rec = find_or_404(STORE.hearings, rid, "hearing")
    return success(serialize(rec))


@bp.get("/ui/hearings/<rid>/witnesses")
def hearing_witnesses(rid):
    require_roles("PlatformAdmin", "ClaimsAnalyst", "AgencyLiaison")
    find_or_404(STORE.hearings, rid, "hearing")
    items = [serialize(w) for w in sorted_created(STORE.witnesses.values()) if w["hearing_id"] == rid]
    return paginate(items)


@bp.post("/ui/hearings/<rid>/witnesses")
def add_witness(rid):
    require_roles("ClaimsAnalyst")
    body = body_json()
    full_name = as_str(req(body, "full_name"), "full_name")
    witness_role = check_enum(
        as_str(req(body, "witness_role"), "witness_role"), WITNESS_ROLES, "witness_role"
    )
    availability_start = as_dt(req(body, "availability_start"), "availability_start")
    availability_end = as_dt(req(body, "availability_end"), "availability_end")

    hearing = find_or_404(STORE.hearings, rid, "hearing")
    if hearing["status"] in ("HELD", "CLOSED"):
        raise err(ERR_INVALID_STATE, 409, "witnesses cannot be added to a terminal hearing")
    # availability window must contain the entire hearing interval
    if availability_start > hearing["scheduled_start"] or availability_end < hearing["scheduled_end"]:
        raise err(ERR_WITNESS_UNAVAILABLE, 409, "availability window does not contain the hearing interval")
    # the referee buffer check re-runs at every witness addition
    _check_referee_buffer(
        hearing["referee_id"], hearing["scheduled_start"], hearing["scheduled_end"],
        exclude_hearing_id=hearing["id"],
    )

    rec = new_record({
        "hearing_id": rid,
        "full_name": full_name,
        "witness_role": witness_role,
        "availability_start": availability_start,
        "availability_end": availability_end,
        "prep_status": "UNPREPARED",
    })
    STORE.witnesses[rec["id"]] = rec
    # first witness starts preparation; a fresh unprepared witness on a READY
    # hearing sends it back to PREP_IN_PROGRESS
    if hearing["status"] in ("SCHEDULED", "READY"):
        hearing["status"] = "PREP_IN_PROGRESS"
        touch(hearing)
    return success(serialize(rec), 201)


@bp.post("/ui/hearings/<rid>/witnesses/<wid>/prep")
def prep_witness(rid, wid):
    require_roles("ClaimsAnalyst")
    hearing = find_or_404(STORE.hearings, rid, "hearing")
    witness = find_or_404(STORE.witnesses, wid, "witness")
    if witness["hearing_id"] != rid:
        raise err(
            ERR_CROSS_PARENT_REFERENCE,
            422,
            "witness belongs to a different hearing than the path scope",
        )
    try:
        rung = PREP_LADDER.index(witness["prep_status"])
    except ValueError:
        rung = -1
    if rung < 0 or rung >= len(PREP_LADDER) - 1:
        raise err(ERR_INVALID_STATE, 409, "witness prep cannot advance further")
    witness["prep_status"] = PREP_LADDER[rung + 1]
    touch(witness)
    _auto_ready(hearing)
    return success(serialize(witness))


@bp.post("/ui/hearings/<rid>/continue")
def continue_hearing(rid):
    require_roles("ClaimsAnalyst")
    body = body_json()
    scheduled_start = as_dt(req(body, "scheduled_start"), "scheduled_start")
    scheduled_end = as_dt(req(body, "scheduled_end"), "scheduled_end")

    hearing = find_or_404(STORE.hearings, rid, "hearing")
    if hearing["status"] not in ("SCHEDULED", "PREP_IN_PROGRESS", "READY"):
        raise err(ERR_INVALID_STATE, 409, "hearing cannot be continued from its current state")
    if scheduled_end <= scheduled_start:
        raise err(ERR_WINDOW_VIOLATION, 422, "scheduled_end must be strictly after scheduled_start")
    # the new interval re-runs both temporal checks
    _check_referee_buffer(
        hearing["referee_id"], scheduled_start, scheduled_end,
        exclude_hearing_id=hearing["id"],
    )
    _check_witnesses_contain(hearing, scheduled_start, scheduled_end)
    if hearing["continuance_count"] >= 3:
        raise err(ERR_CONTINUANCE_LIMIT, 409, "continuance limit of 3 reached")

    hearing["continuance_count"] += 1
    hearing["scheduled_start"] = scheduled_start
    hearing["scheduled_end"] = scheduled_end
    # CONTINUED is transitory: the hearing re-enters SCHEDULED immediately
    hearing["status"] = "SCHEDULED"
    touch(hearing)
    _auto_ready(hearing)
    return success(serialize(hearing))


@bp.post("/ui/hearings/<rid>/hold")
def hold_hearing(rid):
    require_roles("AgencyLiaison")
    hearing = find_or_404(STORE.hearings, rid, "hearing")
    if hearing["status"] != "READY":
        raise err(ERR_HEARING_NOT_READY, 409, "hearing is not READY")
    hearing["status"] = "HELD"
    touch(hearing)
    appeal = STORE.appeals.get(hearing["appeal_id"])
    if appeal is not None and appeal["status"] == "DOCKETED":
        appeal["status"] = "HEARD"
        touch(appeal)
    return success(serialize(hearing))
