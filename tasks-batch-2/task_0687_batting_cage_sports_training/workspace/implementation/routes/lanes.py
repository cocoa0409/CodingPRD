"""Lane and PitchingMachine routes (PRD 3.1)."""
from flask import Blueprint, request

from db import db
from errors import err, ERR_INVALID_REQUEST, ERR_NOT_FOUND
from helpers import (
    get_json_body,
    require_fields,
    require_enum,
    lookup,
    base_common_fields,
    parse_pagination,
    paginate,
)
from middleware import authenticate, require_role
from response import success
from serializers import lane_out, machine_out

bp = Blueprint("lanes", __name__)

READ_ROLES = ["FacilityManager", "FrontDesk", "Member", "Instructor"]


@bp.post("/v1/lanes")
def create_lane():
    _, role = authenticate()
    require_role(role, ["FacilityManager"])
    body = get_json_body()
    require_fields(body, ["facility_id", "label", "kind"])
    # Existence (priority 3) before well-formedness of optional fields.
    lookup(db.facilities, body["facility_id"])
    require_enum(body["kind"], {"CAGE", "TUNNEL", "LANE"}, "kind")

    buffer_minutes = body.get("buffer_minutes", 0)
    if not isinstance(buffer_minutes, int) or isinstance(buffer_minutes, bool) or buffer_minutes < 0:
        raise err(ERR_INVALID_REQUEST, "buffer_minutes must be >= 0")
    hourly_rate_cents = body.get("hourly_rate_cents", None)
    if hourly_rate_cents is not None:
        if not isinstance(hourly_rate_cents, int) or isinstance(hourly_rate_cents, bool) or hourly_rate_cents < 0:
            raise err(ERR_INVALID_REQUEST, "hourly_rate_cents must be >= 0")

    lane = base_common_fields()
    lane.update({
        "facility_id": body["facility_id"],
        "label": body["label"],
        "kind": body["kind"],
        "buffer_minutes": buffer_minutes,
        "hourly_rate_cents": hourly_rate_cents,
        "maint_status": "AVAILABLE",
    })
    db.lanes[lane["id"]] = lane
    return success(lane_out(lane), status=201)


@bp.get("/v1/lanes/<lane_id>")
def get_lane(lane_id):
    _, role = authenticate()
    require_role(role, READ_ROLES)
    lane = lookup(db.lanes, lane_id)
    return success(lane_out(lane), status=200)


@bp.get("/v1/lanes")
def list_lanes():
    _, role = authenticate()
    require_role(role, READ_ROLES)
    limit, offset = parse_pagination()
    facility_id = request.args.get("facility_id")
    items = [l for l in db.lanes.values()
             if facility_id is None or l["facility_id"] == facility_id]
    page, meta = paginate(items, limit, offset)
    return success([lane_out(l) for l in page], status=200, pagination=meta)


# --- PitchingMachine ---
@bp.post("/v1/machines")
def create_machine():
    _, role = authenticate()
    require_role(role, ["FacilityManager"])
    body = get_json_body()
    require_fields(body, ["facility_id", "lane_id", "model"])
    facility = lookup(db.facilities, body["facility_id"])
    lane = lookup(db.lanes, body["lane_id"])
    if lane["facility_id"] != facility["id"]:
        raise err(ERR_NOT_FOUND, "Lane not in facility scope")
    require_enum(body["model"], {"WHEEL", "ARM", "SOFT_TOSS"}, "model")

    machine = base_common_fields()
    machine.update({
        "facility_id": body["facility_id"],
        "lane_id": body["lane_id"],
        "model": body["model"],
        "pitch_count": 0,
        "status": "OPERATIONAL",
    })
    db.machines[machine["id"]] = machine
    return success(machine_out(machine), status=201)


@bp.get("/v1/machines/<machine_id>")
def get_machine(machine_id):
    _, role = authenticate()
    require_role(role, READ_ROLES)
    machine = lookup(db.machines, machine_id)
    return success(machine_out(machine), status=200)


@bp.get("/v1/machines")
def list_machines():
    _, role = authenticate()
    require_role(role, READ_ROLES)
    limit, offset = parse_pagination()
    facility_id = request.args.get("facility_id")
    lane_id = request.args.get("lane_id")
    items = [
        m for m in db.machines.values()
        if (facility_id is None or m["facility_id"] == facility_id)
        and (lane_id is None or m["lane_id"] == lane_id)
    ]
    page, meta = paginate(items, limit, offset)
    return success([machine_out(m) for m in page], status=200, pagination=meta)
