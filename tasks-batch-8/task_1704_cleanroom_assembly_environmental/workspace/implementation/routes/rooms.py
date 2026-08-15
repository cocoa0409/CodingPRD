"""Rooms, sampling points, decommissioning (PRD 3.1, 3.9)."""

from flask import Blueprint, request

from db import store, new_record, mutate, pub
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_INVALID_REQUEST,
    ERR_ROOM_NOT_ACTIVE,
)
from middleware import require_role, body, QA, ALL_ROLES
from response import ok, paginate
from services.core import (
    req_string,
    req_int,
    req_enum,
    touch_room,
)

bp = Blueprint("rooms", __name__)

ISO_CLASSES = {"ISO_5", "ISO_6", "ISO_7", "ISO_8"}
METRICS = {"PARTICLE", "VIABLE"}


def load_room(room_id):
    room = store.rooms.get(room_id)
    if room is None:
        raise ApiError(ERR_NOT_FOUND, 404, "cleanroom %s not found" % room_id)
    return touch_room(room)


# ---------------------------------------------------------------------------
# Cleanrooms
# ---------------------------------------------------------------------------


@bp.post("/cleanroom/rooms")
def create_room():
    require_role([QA])
    payload = body()
    room_code = req_string(payload, "room_code")
    iso_class = req_enum(payload, "iso_class", ISO_CLASSES)
    p_alert = req_int(payload, "particle_alert_limit")
    p_action = req_int(payload, "particle_action_limit")
    v_alert = req_int(payload, "viable_alert_limit")
    v_action = req_int(payload, "viable_action_limit")
    recert = req_int(payload, "recert_interval_days")
    if p_action <= p_alert:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "particle_action_limit must be > particle_alert_limit")
    if v_action <= v_alert:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "viable_action_limit must be > viable_alert_limit")
    room = new_record({
        "room_code": room_code,
        "iso_class": iso_class,
        "particle_alert_limit": p_alert,
        "particle_action_limit": p_action,
        "viable_alert_limit": v_alert,
        "viable_action_limit": v_action,
        "recert_interval_days": recert,
        "certification_status": "UNCERTIFIED",
        "certified_at": None,
        "environment_posture": "IN_CONTROL",
        "status": "ACTIVE",
    })
    store.rooms[room["id"]] = room
    return ok(pub(room), 201)


@bp.get("/cleanroom/rooms")
def list_rooms():
    require_role(ALL_ROLES)
    records = [touch_room(r) for r in store.rooms.values()]
    iso_class = request.args.get("iso_class")
    cert_status = request.args.get("certification_status")
    if iso_class is not None:
        records = [r for r in records if r["iso_class"] == iso_class]
    if cert_status is not None:
        records = [r for r in records if r["certification_status"] == cert_status]
    return paginate(records, request.args)


@bp.get("/cleanroom/rooms/<roomId>")
def get_room(roomId):
    require_role(ALL_ROLES)
    room = load_room(roomId)
    return ok(pub(room))


@bp.post("/cleanroom/rooms/<roomId>/decommission")
def decommission_room(roomId):
    require_role([QA])
    room = load_room(roomId)
    if room["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409, "room is not ACTIVE")
    busy = any(
        b["cleanroom_id"] == room["id"]
        and b["status"] in ("OPEN", "IN_PROGRESS", "ON_HOLD")
        for b in store.batches.values()
    )
    if busy:
        raise ApiError(ERR_INVALID_STATE, 409,
                       "room has batches in OPEN, IN_PROGRESS or ON_HOLD")
    staged = any(
        t["cleanroom_id"] == room["id"] and t["status"] == "STAGED"
        for t in store.transfers.values()
    )
    if staged:
        raise ApiError(ERR_INVALID_STATE, 409,
                       "room has STAGED material transfers")
    room["status"] = "DECOMMISSIONED"
    mutate(room)
    return ok(pub(room))


# ---------------------------------------------------------------------------
# Sampling points
# ---------------------------------------------------------------------------


@bp.post("/cleanroom/rooms/<roomId>/sampling-points")
def create_sampling_point(roomId):
    require_role([QA])
    room = load_room(roomId)
    if room["status"] != "ACTIVE":
        raise ApiError(ERR_ROOM_NOT_ACTIVE, 409, "room is not ACTIVE")
    payload = body()
    point_code = req_string(payload, "point_code")
    metric = req_enum(payload, "metric", METRICS)
    zone = req_enum(payload, "zone_iso_class", ISO_CLASSES)
    if zone != room["iso_class"]:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "zone_iso_class must equal the room's iso_class")
    point = new_record({
        "cleanroom_id": room["id"],
        "point_code": point_code,
        "metric": metric,
        "zone_iso_class": zone,
        "status": "ACTIVE",
    })
    store.sampling_points[point["id"]] = point
    return ok(pub(point), 201)


@bp.get("/cleanroom/rooms/<roomId>/sampling-points")
def list_sampling_points(roomId):
    require_role(ALL_ROLES)
    room = load_room(roomId)
    records = [p for p in store.sampling_points.values()
               if p["cleanroom_id"] == room["id"]]
    return paginate(records, request.args)


@bp.get("/cleanroom/sampling-points/<pointId>")
def get_sampling_point(pointId):
    require_role(ALL_ROLES)
    point = store.sampling_points.get(pointId)
    if point is None:
        raise ApiError(ERR_NOT_FOUND, 404, "sampling point %s not found" % pointId)
    return ok(pub(point))


@bp.post("/cleanroom/sampling-points/<pointId>/retire")
def retire_sampling_point(pointId):
    require_role([QA])
    point = store.sampling_points.get(pointId)
    if point is None:
        raise ApiError(ERR_NOT_FOUND, 404, "sampling point %s not found" % pointId)
    if point["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409, "sampling point is not ACTIVE")
    point["status"] = "RETIRED"
    mutate(point)
    return ok(pub(point))
