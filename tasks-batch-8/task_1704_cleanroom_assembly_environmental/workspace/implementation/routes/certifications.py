"""Room certifications: record (OCC-guarded), list, void (PRD 3.1, 2.9)."""

from flask import Blueprint, request

from db import store, new_record, mutate, pub, iso_ms
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_REFERENTIAL_INTEGRITY,
    ERR_STALE_ROOM_VERSION,
    ERR_INVALID_STATE,
    ERR_ROOM_NOT_ACTIVE,
    ERR_CERTIFICATION_GRADE_FAILED,
    ERR_OPEN_EXCURSIONS_BLOCK_CERTIFICATION,
    ERR_CLEANING_NOT_VALIDATED,
    ERR_NOT_LATEST_CERTIFICATION,
)
from middleware import require_role, body, QA, ET
from response import ok, paginate
from services.core import (
    req_iso,
    opt_string,
    touch_room,
    recompute_posture,
    open_excursions_for_room,
    has_validated_cleaning_program,
    latest_pass_certification,
    grade_check,
)

bp = Blueprint("certifications", __name__)
READERS = [QA, ET]


def load_room(room_id):
    room = store.rooms.get(room_id)
    if room is None:
        raise ApiError(ERR_NOT_FOUND, 404, "cleanroom %s not found" % room_id)
    return touch_room(room)


def load_cert(cert_id):
    cert = store.certifications.get(cert_id)
    if cert is None:
        raise ApiError(ERR_NOT_FOUND, 404,
                       "certification %s not found" % cert_id)
    return cert


@bp.post("/cleanroom/rooms/<roomId>/certifications")
def create_certification(roomId):
    require_role([QA])
    payload = body()

    # priority 3: path id, then body FK ids, left to right
    room = load_room(roomId)
    supersedes_id = payload.get("supersedes_certification_id")
    supersedes = None
    if supersedes_id is not None:
        if not isinstance(supersedes_id, str):
            raise ApiError(ERR_NOT_FOUND, 404, "certification not found")
        supersedes = store.certifications.get(supersedes_id)
        if supersedes is None:
            raise ApiError(ERR_NOT_FOUND, 404,
                           "certification %s not found" % supersedes_id)

    # priority 4: OCC expected_room_version
    expected = payload.get("expected_room_version")
    if expected is not None:
        if isinstance(expected, bool) or not isinstance(expected, int) \
                or expected != room["version"]:
            raise ApiError(ERR_STALE_ROOM_VERSION, 412,
                           "expected_room_version does not match the room's "
                           "current version")

    # priority 5: room lifecycle state
    if room["status"] != "ACTIVE":
        raise ApiError(ERR_ROOM_NOT_ACTIVE, 409, "room is not ACTIVE")

    # priority 9: structural validity
    if expected is None:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "expected_room_version is required")
    executed_at = req_iso(payload, "executed_at")
    means = payload.get("location_mean_values")
    if not isinstance(means, list) or len(means) == 0:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "location_mean_values must be a non-empty array")
    for v in means:
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "location_mean_values must contain only numbers")

    # priority 10: referential coherence of the supersedes link
    if supersedes is not None and supersedes["cleanroom_id"] != room["id"]:
        raise ApiError(ERR_REFERENTIAL_INTEGRITY, 422,
                       "supersedes_certification_id must reference a "
                       "certification of the same room")

    # business gates, in scaffold precondition order
    passed_grade = grade_check(room, means)
    if not passed_grade:
        raise ApiError(ERR_CERTIFICATION_GRADE_FAILED, 409,
                       "mean(location_mean_values) must be strictly below "
                       "particle_alert_limit")
    if open_excursions_for_room(room["id"]):
        raise ApiError(ERR_OPEN_EXCURSIONS_BLOCK_CERTIFICATION, 409,
                       "room has excursions in OPEN or UNDER_INVESTIGATION")
    if not has_validated_cleaning_program(room["id"]):
        raise ApiError(ERR_CLEANING_NOT_VALIDATED, 409,
                       "no VALIDATED cleaning validation program for the room")

    cert = new_record({
        "cleanroom_id": room["id"],
        "executed_at": iso_ms(executed_at),
        "location_mean_values": means,
        "grade_passed": passed_grade,
        "result": "PASS",
        "supersedes_certification_id": supersedes_id,
    })
    store.certifications[cert["id"]] = cert

    # PASS side effects: certify the room, pin certified_at to executed_at,
    # bump the room version once, recompute posture (may recover SHUTDOWN /
    # lift the non-CERTIFIED floor).
    room["certification_status"] = "CERTIFIED"
    room["certified_at"] = iso_ms(executed_at)
    recompute_posture(room)
    mutate(room)
    return ok(pub(cert), 201)


@bp.get("/cleanroom/rooms/<roomId>/certifications")
def list_room_certifications(roomId):
    require_role(READERS)
    room = load_room(roomId)
    records = [c for c in store.certifications.values()
               if c["cleanroom_id"] == room["id"]]
    return paginate(records, request.args)


@bp.get("/cleanroom/certifications/<certId>")
def get_certification(certId):
    require_role(READERS)
    return ok(pub(load_cert(certId)))


@bp.get("/cleanroom/certifications")
def list_certifications():
    require_role(READERS)
    records = list(store.certifications.values())
    room_id = request.args.get("cleanroom_id")
    supersedes_id = request.args.get("supersedes_certification_id")
    if room_id is not None:
        records = [c for c in records if c["cleanroom_id"] == room_id]
    if supersedes_id is not None:
        records = [c for c in records
                   if c["supersedes_certification_id"] == supersedes_id]
    return paginate(records, request.args)


@bp.post("/cleanroom/rooms/<roomId>/certifications/<certId>/void")
def void_certification(roomId, certId):
    require_role([QA])
    room = load_room(roomId)
    cert = store.certifications.get(certId)
    if cert is None or cert["cleanroom_id"] != room["id"]:
        raise ApiError(ERR_NOT_FOUND, 404,
                       "certification %s not found in room %s" % (certId, roomId))
    if room["status"] != "ACTIVE":
        raise ApiError(ERR_ROOM_NOT_ACTIVE, 409, "room is not ACTIVE")
    if room["certification_status"] != "CERTIFIED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "room certification_status is not CERTIFIED")
    latest = latest_pass_certification(room["id"])
    if latest is None or latest["id"] != cert["id"]:
        raise ApiError(ERR_NOT_LATEST_CERTIFICATION, 409,
                       "void target is not the room's latest PASS certification")
    room["certification_status"] = "CERTIFICATION_SUSPENDED"
    recompute_posture(room)
    mutate(room)
    return ok(pub(cert))
