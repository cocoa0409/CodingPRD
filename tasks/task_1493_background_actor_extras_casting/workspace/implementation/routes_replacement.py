"""ReplacementCase and StandbyEntry endpoints."""
from flask import Blueprint, request

from db import STORE
from domain import _base, ser_case, ser_standby, touch
from errors import (
    ApiError,
    ERR_ACTOR_NOT_ELIGIBLE,
    ERR_CALL_INVALID_STATE,
    ERR_CASE_INVALID_STATE,
    ERR_DUPLICATE_BOOKING,
    ERR_FORBIDDEN_OWNERSHIP,
    ERR_PRODUCTION_NOT_ACTIVE,
    ERR_REPLACEMENT_CASE_NOT_FOUND,
    ERR_STANDBY_ENTRY_NOT_FOUND,
    ERR_STANDBY_NOT_ACTIVE,
)
from middleware import ALL_ROLES, auth, body, req_str
from response import ok_list, ok_obj, paginate
from routes_actors import get_actor
from routes_calls import get_call
from routes_productions import get_production
from services import create_booking_record, select_standby_candidate

bp = Blueprint("replacement", __name__)


# --- ReplacementCase ------------------------------------------------------------

def get_case(rid):
    c = STORE.replacement_cases.get(rid)
    if c is None:
        raise ApiError(ERR_REPLACEMENT_CASE_NOT_FOUND, 404, "Replacement case not found")
    return c


@bp.get("/central-casting/replacement-cases")
def list_cases():
    auth(ALL_ROLES)
    rows = sorted(STORE.replacement_cases.values(), key=lambda c: c["_seq"])
    for param in ("casting_call_id", "original_booking_id", "status"):
        value = request.args.get(param)
        if value is not None:
            rows = [c for c in rows if c.get(param) == value]
    page, total, limit, offset = paginate(rows)
    return ok_list([ser_case(c) for c in page], total, limit, offset)


@bp.get("/central-casting/replacement-cases/<rid>")
def get_case_route(rid):
    auth(ALL_ROLES)
    return ok_obj(ser_case(get_case(rid)))


@bp.post("/central-casting/replacement-cases/<rid>/offer-next")
def offer_next(rid):
    auth(["CastingAssociate"])
    case = get_case(rid)
    if case["status"] != "OPEN":
        raise ApiError(ERR_CASE_INVALID_STATE, 409, "Offer-next requires the case OPEN")
    call = STORE.casting_calls[case["casting_call_id"]]
    if call["status"] != "SHOOTING":
        raise ApiError(ERR_CALL_INVALID_STATE, 409, "Offer-next requires the call SHOOTING")
    picked = select_standby_candidate(case)
    if picked is None:
        # Empty eligible pool: the case slides OPEN -> EXPIRED, HTTP 200, no booking.
        case["status"] = "EXPIRED"
        touch(case)
        return ok_obj(ser_case(case))
    entry, actor = picked
    original = STORE.bookings[case["original_booking_id"]]
    booking = create_booking_record(
        call,
        actor,
        original["call_time"],
        is_replacement=True,
        case=case,
        replaces=original,
    )
    touch(call)  # slot consumed: slots_available -1, call version +1
    case["status"] = "CANDIDATE_OFFERED"
    case["offered_booking_id"] = booking["id"]
    case["offered_actor_id"] = actor["id"]
    case["attempts_count"] += 1
    touch(case)
    return ok_obj(ser_case(case))


@bp.post("/central-casting/replacement-cases/<rid>/expire")
def expire_case(rid):
    auth(["CastingAssociate"])
    case = get_case(rid)
    if case["status"] != "OPEN":
        raise ApiError(ERR_CASE_INVALID_STATE, 409, "Only an OPEN case can be expired manually")
    case["status"] = "EXPIRED"
    touch(case)
    return ok_obj(ser_case(case))


# --- StandbyEntry -----------------------------------------------------------------

@bp.post("/central-casting/standby-entries")
def create_standby():
    auth(["CastingAssociate"])
    data = body()
    casting_call_id = req_str(data, "casting_call_id")
    actor_id = req_str(data, "actor_id")
    call = get_call(casting_call_id)
    actor = get_actor(actor_id)
    production = get_production(call["production_id"])
    if production["status"] != "ACTIVE":
        raise ApiError(ERR_PRODUCTION_NOT_ACTIVE, 409, "Production must be ACTIVE")
    if call["status"] not in ("PUBLISHED", "LOCKED"):
        raise ApiError(
            ERR_CALL_INVALID_STATE,
            409,
            "Standby registration requires the call PUBLISHED or LOCKED",
        )
    if actor["status"] != "ELIGIBLE":
        raise ApiError(ERR_ACTOR_NOT_ELIGIBLE, 409, "Actor must be ELIGIBLE for standby")
    duplicate = any(
        s["casting_call_id"] == call["id"] and s["actor_id"] == actor["id"] and s["status"] == "ACTIVE"
        for s in STORE.standby_entries.values()
    )
    if duplicate:
        raise ApiError(
            ERR_DUPLICATE_BOOKING, 409, "Actor already holds an ACTIVE standby entry on this call"
        )
    s = _base()
    s.update(
        {
            "casting_call_id": casting_call_id,
            "actor_id": actor_id,
            "slot_type": "UNION" if actor["union_status"] == "SAG_AFTRA" else "NONUNION",
            "status": "ACTIVE",
        }
    )
    STORE.standby_entries[s["id"]] = s
    return ok_obj(ser_standby(s), code=201)


@bp.get("/central-casting/standby-entries")
def list_standby():
    auth(ALL_ROLES)
    rows = sorted(STORE.standby_entries.values(), key=lambda s: s["_seq"])
    for param in ("casting_call_id", "actor_id", "status"):
        value = request.args.get(param)
        if value is not None:
            rows = [s for s in rows if s.get(param) == value]
    page, total, limit, offset = paginate(rows)
    return ok_list([ser_standby(s) for s in page], total, limit, offset)


@bp.get("/central-casting/standby-entries/<sid>")
def get_standby(sid):
    auth(ALL_ROLES)
    s = STORE.standby_entries.get(sid)
    if s is None:
        raise ApiError(ERR_STANDBY_ENTRY_NOT_FOUND, 404, "Standby entry not found")
    return ok_obj(ser_standby(s))


@bp.post("/central-casting/standby-entries/<sid>/withdraw")
def withdraw_standby(sid):
    user_id, role = auth(["BackgroundActor", "CastingAssociate"])
    s = STORE.standby_entries.get(sid)
    if s is None:
        raise ApiError(ERR_STANDBY_ENTRY_NOT_FOUND, 404, "Standby entry not found")
    if role == "BackgroundActor" and s["actor_id"] != user_id:
        raise ApiError(ERR_FORBIDDEN_OWNERSHIP, 403, "Caller does not own this standby entry")
    if s["status"] != "ACTIVE":
        raise ApiError(ERR_STANDBY_NOT_ACTIVE, 409, "Only an ACTIVE standby entry can be withdrawn")
    s["status"] = "WITHDRAWN"
    touch(s)
    return ok_obj(ser_standby(s))
