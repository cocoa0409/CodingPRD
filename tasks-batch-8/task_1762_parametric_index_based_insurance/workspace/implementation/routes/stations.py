"""MeasurementStation endpoints (PRD §3.2)."""

from flask import Blueprint, request

import db
from errors import (
    err, ERR_INVALID_REQUEST, ERR_STATION_NOT_COMMISSIONED, ERR_STATION_NOT_OFFLINE,
    ERR_STATION_NOT_FOUND,
)
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list
from routes.common import (
    body, require_fields, require_enum, pagination_params, paginate,
    sorted_by_created, get_program, get_station_in_program,
)
from services import domain

bp = Blueprint("stations", __name__)

STATION_KINDS = {"PHYSICAL_STATION", "GRID_MODEL"}


@bp.post("/programs/<programId>/stations")
def create_station(programId):
    require_roles("DataOperations")
    prog = get_program(programId)
    data = body()
    require_fields(data, ["station_code", "station_kind", "reliability_weight"])
    require_enum(data, "station_kind", STATION_KINDS)
    w = data["reliability_weight"]
    if not isinstance(w, (int, float)) or w < 0.1 or w > 1.0:
        raise err(ERR_INVALID_REQUEST, 400, "reliability_weight must be in [0.1, 1.0]")
    st = domain.stamp_new({
        "program_id": prog["id"],
        "station_code": data["station_code"],
        "station_kind": data["station_kind"],
        "reliability_weight": w,
        "status": "COMMISSIONED",
    })
    db.stations[st["id"]] = st
    return success_object(domain.serialize(st), 201)


@bp.get("/programs/<programId>/stations")
def list_stations(programId):
    require_roles(*ALL_ROLES)
    prog = get_program(programId)
    limit, offset = pagination_params()
    items = sorted_by_created(
        s for s in db.stations.values() if s["program_id"] == prog["id"]
    )
    page, total = paginate(items, limit, offset)
    return success_list(domain.serialize_list(page), limit, offset, total)


@bp.get("/programs/<programId>/stations/<stationId>")
def get_station(programId, stationId):
    require_roles(*ALL_ROLES)
    prog = get_program(programId)
    st = get_station_in_program(prog, stationId)
    return success_object(domain.serialize(st))


@bp.post("/programs/<programId>/stations/<stationId>/take-offline")
def take_offline(programId, stationId):
    require_roles("DataOperations")
    prog = get_program(programId)
    st = get_station_in_program(prog, stationId)
    if st["status"] != "COMMISSIONED":
        raise err(ERR_STATION_NOT_COMMISSIONED, 409, "Operation requires station COMMISSIONED")
    st["status"] = "OFFLINE"
    domain.touch(st)
    return success_object(domain.serialize(st))


@bp.post("/programs/<programId>/stations/<stationId>/recommission")
def recommission(programId, stationId):
    require_roles("DataOperations")
    prog = get_program(programId)
    st = get_station_in_program(prog, stationId)
    if st["status"] != "OFFLINE":
        raise err(ERR_STATION_NOT_OFFLINE, 409, "Operation requires station OFFLINE")
    st["status"] = "COMMISSIONED"
    domain.touch(st)
    return success_object(domain.serialize(st))


@bp.post("/programs/<programId>/stations/<stationId>/decommission")
def decommission_station(programId, stationId):
    require_roles("DataOperations")
    prog = get_program(programId)
    st = get_station_in_program(prog, stationId)
    if st["status"] == "COMMISSIONED":
        pass
    elif st["status"] == "OFFLINE":
        pass
    elif st["status"] == "DECOMMISSIONED":
        # Already terminal — surface the generic state error
        from errors import ERR_INVALID_STATE
        raise err(ERR_INVALID_STATE, 409, "Station already DECOMMISSIONED")
    else:
        from errors import ERR_INVALID_STATE
        raise err(ERR_INVALID_STATE, 409, "Invalid station state")
    st["status"] = "DECOMMISSIONED"
    domain.touch(st)
    return success_object(domain.serialize(st))


# --- Flat reads ---

@bp.get("/programs/stations")
def list_stations_flat():
    require_roles(*ALL_ROLES)
    limit, offset = pagination_params()
    program_id = request.args.get("program_id")
    items = list(db.stations.values())
    if program_id is not None:
        items = [s for s in items if s["program_id"] == program_id]
    items = sorted_by_created(items)
    page, total = paginate(items, limit, offset)
    return success_list(domain.serialize_list(page), limit, offset, total)


@bp.get("/programs/stations/<stationId>")
def get_station_flat(stationId):
    require_roles(*ALL_ROLES)
    st = db.stations.get(stationId)
    if not st:
        raise err(ERR_STATION_NOT_FOUND, 404, "Station id does not exist")
    return success_object(domain.serialize(st))
