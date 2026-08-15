"""Personnel, gowning qualifications, entry logs (PRD 3.2)."""

from datetime import timedelta

from flask import Blueprint, request

from db import store, new_record, mutate, pub, iso_ms, now
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_ROOM_NOT_ACTIVE,
    ERR_ROOM_NOT_IN_CONTROL,
    ERR_GOWNING_NOT_QUALIFIED,
    ERR_PERSONNEL_SUSPENDED,
    ERR_ENTRY_ALREADY_OPEN,
)
from middleware import require_role, body, QA, ET, PO
from response import ok, paginate
from services.core import (
    req_string,
    touch_room,
    touch_qualification,
    qualified_unexpired_qualification,
)

bp = Blueprint("people", __name__)
READERS = [QA, ET]

QUALIFICATION_VALID_DAYS = 365


def load_personnel(personnel_id):
    person = store.personnel.get(personnel_id)
    if person is None:
        raise ApiError(ERR_NOT_FOUND, 404,
                       "personnel %s not found" % personnel_id)
    return person


def load_qualification(qual_id):
    qual = store.qualifications.get(qual_id)
    if qual is None:
        raise ApiError(ERR_NOT_FOUND, 404,
                       "gowning qualification %s not found" % qual_id)
    return touch_qualification(qual)


# ---------------------------------------------------------------------------
# Personnel
# ---------------------------------------------------------------------------


@bp.post("/cleanroom/personnel")
def create_personnel():
    require_role([QA])
    payload = body()
    person = new_record({
        "employee_code": req_string(payload, "employee_code"),
        "full_name": req_string(payload, "full_name"),
        "role_title": req_string(payload, "role_title"),
        "status": "ACTIVE",
    })
    store.personnel[person["id"]] = person
    return ok(pub(person), 201)


@bp.get("/cleanroom/personnel")
def list_personnel():
    require_role(READERS)
    return paginate(list(store.personnel.values()), request.args)


@bp.get("/cleanroom/personnel/<personnelId>")
def get_personnel(personnelId):
    require_role(READERS)
    return ok(pub(load_personnel(personnelId)))


@bp.post("/cleanroom/personnel/<personnelId>/suspend")
def suspend_personnel(personnelId):
    require_role([QA])
    person = load_personnel(personnelId)
    if person["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409, "personnel is not ACTIVE")
    person["status"] = "SUSPENDED"
    mutate(person)
    # Force-close any open entry logs for this person.
    for log in store.entry_logs.values():
        if log["personnel_id"] == person["id"] and log["exited_at"] is None:
            log["exited_at"] = iso_ms(now())
            mutate(log)
    return ok(pub(person))


@bp.post("/cleanroom/personnel/<personnelId>/reinstate")
def reinstate_personnel(personnelId):
    require_role([QA])
    person = load_personnel(personnelId)
    if person["status"] != "SUSPENDED":
        raise ApiError(ERR_INVALID_STATE, 409, "personnel is not SUSPENDED")
    person["status"] = "ACTIVE"
    mutate(person)
    return ok(pub(person))


# ---------------------------------------------------------------------------
# Gowning qualifications
# ---------------------------------------------------------------------------


@bp.post("/cleanroom/gowning-qualifications")
def create_qualification():
    require_role([QA])
    payload = body()
    personnel_id = payload.get("personnel_id")
    if not isinstance(personnel_id, str) \
            or store.personnel.get(personnel_id) is None:
        raise ApiError(ERR_NOT_FOUND, 404,
                       "personnel %s not found" % personnel_id)
    cleanroom_id = payload.get("cleanroom_id")
    if not isinstance(cleanroom_id, str) \
            or store.rooms.get(cleanroom_id) is None:
        raise ApiError(ERR_NOT_FOUND, 404,
                       "cleanroom %s not found" % cleanroom_id)
    granted = now()
    qual = new_record({
        "personnel_id": personnel_id,
        "cleanroom_id": cleanroom_id,
        "qualified_at": iso_ms(granted),
        "qualification_expires_at": iso_ms(
            granted + timedelta(days=QUALIFICATION_VALID_DAYS)),
        "status": "QUALIFIED",
    })
    store.qualifications[qual["id"]] = qual
    return ok(pub(qual), 201)


@bp.get("/cleanroom/gowning-qualifications")
def list_qualifications():
    require_role(READERS)
    records = [touch_qualification(q) for q in store.qualifications.values()]
    personnel_id = request.args.get("personnel_id")
    cleanroom_id = request.args.get("cleanroom_id")
    status = request.args.get("status")
    if personnel_id is not None:
        records = [q for q in records if q["personnel_id"] == personnel_id]
    if cleanroom_id is not None:
        records = [q for q in records if q["cleanroom_id"] == cleanroom_id]
    if status is not None:
        records = [q for q in records if q["status"] == status]
    return paginate(records, request.args)


@bp.get("/cleanroom/gowning-qualifications/<qualId>")
def get_qualification(qualId):
    require_role(READERS)
    return ok(pub(load_qualification(qualId)))


@bp.post("/cleanroom/gowning-qualifications/<qualId>/revoke")
def revoke_qualification(qualId):
    require_role([QA])
    qual = load_qualification(qualId)
    if qual["status"] not in ("QUALIFIED", "EXPIRED"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "qualification is not QUALIFIED or EXPIRED")
    qual["status"] = "REVOKED"
    mutate(qual)
    return ok(pub(qual))


@bp.get("/cleanroom/rooms/<roomId>/gowning-qualifications")
def list_room_qualifications(roomId):
    require_role(READERS)
    room = store.rooms.get(roomId)
    if room is None:
        raise ApiError(ERR_NOT_FOUND, 404, "cleanroom %s not found" % roomId)
    touch_room(room)
    records = [touch_qualification(q) for q in store.qualifications.values()
               if q["cleanroom_id"] == room["id"]]
    return paginate(records, request.args)


@bp.get("/cleanroom/personnel/<personnelId>/gowning-qualifications")
def list_personnel_qualifications(personnelId):
    require_role(READERS)
    person = load_personnel(personnelId)
    records = [touch_qualification(q) for q in store.qualifications.values()
               if q["personnel_id"] == person["id"]]
    return paginate(records, request.args)


# ---------------------------------------------------------------------------
# Entry logs
# ---------------------------------------------------------------------------


@bp.post("/cleanroom/entry-logs")
def create_entry_log():
    require_role([PO])
    payload = body()
    # priority 3: body FK existence, left to right
    personnel_id = payload.get("personnel_id")
    if not isinstance(personnel_id, str) \
            or store.personnel.get(personnel_id) is None:
        raise ApiError(ERR_NOT_FOUND, 404,
                       "personnel %s not found" % personnel_id)
    cleanroom_id = payload.get("cleanroom_id")
    if not isinstance(cleanroom_id, str) \
            or store.rooms.get(cleanroom_id) is None:
        raise ApiError(ERR_NOT_FOUND, 404,
                       "cleanroom %s not found" % cleanroom_id)

    person = store.personnel[personnel_id]
    room = touch_room(store.rooms[cleanroom_id])

    # priority 5: room operational-write gate
    if room["status"] != "ACTIVE":
        raise ApiError(ERR_ROOM_NOT_ACTIVE, 409, "room is not ACTIVE")
    # priority 6: posture gate
    if room["environment_posture"] != "IN_CONTROL":
        raise ApiError(ERR_ROOM_NOT_IN_CONTROL, 409,
                       "room environment_posture is not IN_CONTROL")
    # priority 11: gowning qualification present, QUALIFIED, unexpired
    if qualified_unexpired_qualification(personnel_id, cleanroom_id) is None:
        raise ApiError(ERR_GOWNING_NOT_QUALIFIED, 409,
                       "no QUALIFIED, unexpired gowning qualification for "
                       "this personnel and room")
    # priority 11.5: personnel must be ACTIVE
    if person["status"] != "ACTIVE":
        raise ApiError(ERR_PERSONNEL_SUSPENDED, 409,
                       "personnel is SUSPENDED")
    # priority 12: one open entry per (personnel, room) pair
    if any(l["personnel_id"] == personnel_id
           and l["cleanroom_id"] == cleanroom_id
           and l["exited_at"] is None
           for l in store.entry_logs.values()):
        raise ApiError(ERR_ENTRY_ALREADY_OPEN, 409,
                       "an open entry log already exists for this "
                       "personnel and room")

    log = new_record({
        "personnel_id": personnel_id,
        "cleanroom_id": cleanroom_id,
        "entered_at": iso_ms(now()),
        "exited_at": None,
    })
    store.entry_logs[log["id"]] = log
    return ok(pub(log), 201)


@bp.get("/cleanroom/entry-logs")
def list_entry_logs():
    require_role(READERS)
    records = list(store.entry_logs.values())
    personnel_id = request.args.get("personnel_id")
    cleanroom_id = request.args.get("cleanroom_id")
    if personnel_id is not None:
        records = [l for l in records if l["personnel_id"] == personnel_id]
    if cleanroom_id is not None:
        records = [l for l in records if l["cleanroom_id"] == cleanroom_id]
    return paginate(records, request.args)


@bp.get("/cleanroom/entry-logs/<entryLogId>")
def get_entry_log(entryLogId):
    require_role(READERS)
    log = store.entry_logs.get(entryLogId)
    if log is None:
        raise ApiError(ERR_NOT_FOUND, 404, "entry log %s not found" % entryLogId)
    return ok(pub(log))


@bp.post("/cleanroom/entry-logs/<entryLogId>/exit")
def exit_entry_log(entryLogId):
    require_role([PO])
    log = store.entry_logs.get(entryLogId)
    if log is None:
        raise ApiError(ERR_NOT_FOUND, 404, "entry log %s not found" % entryLogId)
    if log["exited_at"] is not None:
        raise ApiError(ERR_INVALID_STATE, 409, "entry log is already closed")
    log["exited_at"] = iso_ms(now())
    mutate(log)
    return ok(pub(log))
