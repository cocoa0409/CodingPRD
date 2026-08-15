"""Station registry routes (PRD 3.3)."""
from flask import Blueprint

import db
from db import store
from errors import ApiError
from middleware import body_json, ctx, list_response, need_enum, need_str, require_role
from response import ok

bp = Blueprint("stations", __name__)

STATION_TYPES = ("FIXED_SCALE", "WIM_ONLY", "MOBILE_PATROL")
CHANNELS = ("TRANSPONDER", "MOBILE_APP", "BOTH")
OP_STATUSES = ("OPERATIONAL", "CLOSED_TEMP", "CLOSED_PERM")

_LEGAL_OP = {
    ("OPERATIONAL", "CLOSED_TEMP"),
    ("CLOSED_TEMP", "OPERATIONAL"),
    ("OPERATIONAL", "CLOSED_PERM"),
    ("CLOSED_TEMP", "CLOSED_PERM"),
}


@bp.post("/api/stations")
def create_station():
    _uid, role = ctx()
    require_role(role, ("StateProgramManager",))
    body = body_json()
    # Rung 4: referenced config must exist (when the reference is well-formed)
    cfg_id = body.get("state_program_config_id")
    if isinstance(cfg_id, str) and cfg_id not in store.configs:
        raise ApiError(
            "ERR_STATE_PROGRAM_CONFIG_NOT_FOUND", 404, "state config id does not exist"
        )
    # Rung 12: fields
    cfg_id = need_str(body, "state_program_config_id")
    code = need_str(body, "station_code")
    stype = need_enum(body, "station_type", STATION_TYPES)
    channel = need_enum(body, "supported_channel", CHANNELS)
    # Rung 13: uniqueness
    for s in store.stations.values():
        if s["station_code"] == code:
            raise ApiError(
                "ERR_DUPLICATE_STATION_CODE", 409, "station_code already registered"
            )
    rec = {
        "id": db.new_id(),
        "_seq": store.next_seq(),
        "state_program_config_id": cfg_id,
        "station_code": code,
        "station_type": stype,
        "supported_channel": channel,
        "operational_status": "OPERATIONAL",
        "version": 1,
    }
    db.stamp(rec)
    store.stations[rec["id"]] = rec
    return ok(db.public(rec), 201)


@bp.get("/api/stations")
def list_stations():
    return list_response(
        store.stations.values(),
        [
            ("state_program_config_id", "state_program_config_id"),
            ("operational_status", "operational_status"),
        ],
    )


@bp.get("/api/stations/<stationId>")
def get_station(stationId):
    ctx()
    station = store.stations.get(stationId)
    if station is None:
        raise ApiError("ERR_STATION_NOT_FOUND", 404, "station id does not exist")
    return ok(db.public(station), 200)


@bp.patch("/api/stations/<stationId>")
def patch_station(stationId):
    _uid, role = ctx()
    require_role(role, ("StateProgramManager",))
    station = store.stations.get(stationId)
    if station is None:
        raise ApiError("ERR_STATION_NOT_FOUND", 404, "station id does not exist")
    body = body_json()
    target = body.get("operational_status")
    # Rung 5 for valid enum members; rung 12 otherwise
    if isinstance(target, str) and target in OP_STATUSES:
        if (station["operational_status"], target) not in _LEGAL_OP:
            raise ApiError(
                "ERR_INVALID_STATE_TRANSITION",
                409,
                f"station cannot move from {station['operational_status']} to {target}",
            )
    else:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            400,
            "operational_status must be one of OPERATIONAL, CLOSED_TEMP, CLOSED_PERM",
        )
    station["operational_status"] = target
    db.bump(station)
    return ok(db.public(station), 200)
