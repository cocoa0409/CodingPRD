"""RehearsalCall routes (PRD 3.6) — room overlap, publish gate, cancel cascade."""

from flask import Blueprint

from db import store
from errors import (ERR_INVALID_STATE, ERR_PROD_NOT_REHEARSAL,
                    ERR_ROOM_CONFLICT, ERR_TIME_RANGE, ApiError, conflict)
from middleware import require_roles
from response import ok_object
from routes.common import get_or_404, list_response
from services import recompute_headcount, room_conflict
from util import (json_body, new_record, opt_int, parse_dt, req_enum, req_str,
                  to_public, touch)

bp = Blueprint("rehearsal_calls", __name__)

CALL_TYPES = ("BLOCKING", "STAGING", "ORCHESTRA_READ", "DANCE_CALL", "TECH",
              "DRESS")
TARGET_STATES = ("PUBLISHED", "DRAFT", "COMPLETED", "CANCELLED")
REMOVABLE_PARTICIPANT_STATES = ("INVITED", "WAIVER_PENDING", "CONFIRMED",
                                "CHECKED_IN")


@bp.post("/opera/rehearsal-calls")
def create_call():
    require_roles("TechnicalDirector")
    body = json_body()
    production_id = req_str(body, "production_id")
    room_id = req_str(body, "room_id")
    call_type = req_enum(body, "call_type", CALL_TYPES)
    starts_at = parse_dt(body.get("starts_at"), "starts_at")
    ends_at = parse_dt(body.get("ends_at"), "ends_at")
    required = opt_int(body, "required_headcount", default=1, min_value=0)
    # Pipeline step 5: time range.
    if ends_at <= starts_at:
        raise ApiError(ERR_TIME_RANGE, 400, "ends_at must be strictly after starts_at")
    # Pipeline step 6: existence, body FKs in declared input order.
    prod = get_or_404(store.productions, production_id, "Production")
    room = get_or_404(store.rehearsal_rooms, room_id, "RehearsalRoom")
    # Pipeline step 11: room overlap against DRAFT/PUBLISHED calls on the room.
    if room_conflict(room["id"], starts_at, ends_at):
        raise conflict(ERR_ROOM_CONFLICT,
                       "Call overlaps another DRAFT/PUBLISHED call on this room")
    rec = new_record(
        production_id=prod["id"],
        room_id=room["id"],
        call_type=call_type,
        starts_at=starts_at,
        ends_at=ends_at,
        required_headcount=required,
        confirmed_headcount=0,
        status="DRAFT",
    )
    store.rehearsal_calls[rec["id"]] = rec
    return ok_object(to_public(rec), 201)


@bp.get("/opera/rehearsal-calls")
def list_calls():
    require_roles("Any")
    return list_response(
        store.rehearsal_calls.values(),
        [("production_id", "production_id"), ("room_id", "room_id"),
         ("status", "status")],
    )


@bp.get("/opera/rehearsal-calls/<cid>")
def get_call(cid):
    require_roles("Any")
    return ok_object(to_public(get_or_404(store.rehearsal_calls, cid,
                                          "RehearsalCall")))


@bp.post("/opera/rehearsal-calls/<cid>/transition")
def transition_call(cid):
    require_roles("TechnicalDirector")
    body = json_body()
    to_state = req_enum(body, "to_state", TARGET_STATES)
    call = get_or_404(store.rehearsal_calls, cid, "RehearsalCall")
    cur = call["status"]

    if cur == "DRAFT" and to_state == "PUBLISHED":
        prod = store.productions[call["production_id"]]
        if prod["status"] != "REHEARSAL":
            raise conflict(ERR_PROD_NOT_REHEARSAL,
                           "Publishing requires the production in REHEARSAL")
        if room_conflict(call["room_id"], call["starts_at"], call["ends_at"],
                         exclude_id=call["id"]):
            raise conflict(ERR_ROOM_CONFLICT,
                           "Call overlaps another DRAFT/PUBLISHED call on this room")
    elif cur == "PUBLISHED" and to_state == "DRAFT":
        pass  # unpublish-for-reschedule loop
    elif cur == "PUBLISHED" and to_state == "COMPLETED":
        pass
    elif cur in ("DRAFT", "PUBLISHED") and to_state == "CANCELLED":
        for p in store.call_participants.values():
            if p["call_id"] == call["id"] and p["status"] in REMOVABLE_PARTICIPANT_STATES:
                p["status"] = "REMOVED"
                touch(p)
        recompute_headcount(call)
    else:
        raise conflict(ERR_INVALID_STATE,
                       f"RehearsalCall cannot transition {cur} -> {to_state}")

    call["status"] = to_state
    touch(call)
    return ok_object(to_public(call))
