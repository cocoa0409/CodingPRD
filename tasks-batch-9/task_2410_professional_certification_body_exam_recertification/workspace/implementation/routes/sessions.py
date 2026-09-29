"""ExamSession endpoints: the delivery calendar (PRD 3.7)."""

from flask import Blueprint

import serialize
from db import DB, mark_created, new_record, ordered
from dispatch import api
from errors import ApiError
from middleware import (
    ROLE_CANDIDATE,
    ROLE_EXAM_OPERATIONS,
    ROLE_PROGRAM_ADMIN,
    authenticate,
    ensure_body,
    must_be_absent,
    peek_body,
    req_enum,
    req_int,
    req_str,
    req_ts,
)
from response import apply_filters, created_response, object_response, paginate, read_pagination
from services import calc, derive, lookup

bp = Blueprint("sessions", __name__)

MODALITIES = ("TEST_CENTER", "ONLINE_PROCTORED")


def _overlaps(new_starts, new_ends, other):
    """Half-open overlap: adjacency is permitted, intersection is not."""
    return new_starts < other["ends_at"] and other["starts_at"] < new_ends


@bp.post("/exam-sessions")
@api
def create_session():
    authenticate([ROLE_EXAM_OPERATIONS])
    body = ensure_body(peek_body())

    modality = req_enum(body, "modality", MODALITIES)
    starts_at = req_ts(body, "starts_at")
    ends_at = req_ts(body, "ends_at")
    seat_capacity = req_int(body, "seat_capacity", minimum=0)

    # Layer 7: the location fields are modality-conditional and strictly so.
    if modality == "TEST_CENTER":
        center_code = req_str(body, "center_code")
        room_code = req_str(body, "room_code")
        must_be_absent(body, "proctor_pool_code")
        proctor_pool_code = None
    else:
        proctor_pool_code = req_str(body, "proctor_pool_code")
        must_be_absent(body, "center_code")
        must_be_absent(body, "room_code")
        center_code = None
        room_code = None

    # Layer 9: window shape.
    if not starts_at < ends_at:
        raise ApiError("ERR_INVALID_REQUEST")
    if seat_capacity < 1:
        raise ApiError("ERR_INVALID_REQUEST")

    if modality == "TEST_CENTER":
        # Layer 27: a physical room cannot be double-booked.
        for other in ordered(DB.sessions.values()):
            if other["modality"] != "TEST_CENTER":
                continue
            if other["center_code"] != center_code or other["room_code"] != room_code:
                continue
            if _overlaps(starts_at, ends_at, other):
                raise ApiError("ERR_ROOM_WINDOW_CONFLICT")
    else:
        # Layer 47: the proctor pool is constrained collectively.
        committed = 0
        for other in ordered(DB.sessions.values()):
            if other["modality"] != "ONLINE_PROCTORED":
                continue
            if other["proctor_pool_code"] != proctor_pool_code:
                continue
            if _overlaps(starts_at, ends_at, other):
                committed += other["seat_capacity"]
        if committed + seat_capacity > calc.POOL_MAX_CONCURRENT_SEATS:
            raise ApiError("ERR_PROCTOR_POOL_CAPACITY_EXCEEDED")

    session = new_record(
        modality=modality,
        center_code=center_code,
        room_code=room_code,
        proctor_pool_code=proctor_pool_code,
        starts_at=starts_at,
        ends_at=ends_at,
        seat_capacity=seat_capacity,
        seats_reserved=0,
        status="OPEN",
    )
    mark_created(session)
    DB.sessions[session["id"]] = session
    derive.refresh_session_projection(session)
    return created_response(serialize.session(session))


@bp.get("/exam-sessions/<session_id>")
@api
def read_session(session_id):
    authenticate([ROLE_EXAM_OPERATIONS, ROLE_CANDIDATE, ROLE_PROGRAM_ADMIN])
    return object_response(serialize.session(lookup.session(session_id)))


@bp.get("/exam-sessions")
@api
def list_sessions():
    authenticate([ROLE_EXAM_OPERATIONS, ROLE_CANDIDATE, ROLE_PROGRAM_ADMIN])
    limit, offset = read_pagination()
    rows = ordered(DB.sessions.values())
    for session in rows:
        derive.refresh_session_projection(session)
    rows = apply_filters(rows, {
        "modality": "modality",
        "center_code": "center_code",
        "room_code": "room_code",
        "proctor_pool_code": "proctor_pool_code",
        "status": "status",
    })
    return paginate(rows, serialize.session, limit, offset)
