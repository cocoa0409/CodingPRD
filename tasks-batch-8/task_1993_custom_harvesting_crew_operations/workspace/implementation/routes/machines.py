"""Machine endpoints (§3.3, §3.5)."""

from flask import Blueprint, request

from db import db
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_MACHINE_NOT_IN_FIELD,
    ERR_MACHINE_NOT_DOWN,
    ERR_MACHINE_NOT_REPAIRING,
)
from helpers import (
    get_json_body,
    require_fields,
    require_type,
    require_enum,
    stamp_new,
    touch,
    public,
    sort_key,
    get_season_or_404,
    get_machine_or_404,
)
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list, parse_pagination, paginate

bp = Blueprint("machines", __name__)

MACHINE_KINDS = ("COMBINE", "GRAIN_CART", "TRUCK")


@bp.route("/harvest/seasons/<seasonId>/machines", methods=["POST"])
def create_machine(seasonId):
    require_roles("HarvestOperator")
    season = get_season_or_404(seasonId)
    body = get_json_body()
    require_fields(body, ["machine_kind", "label", "daily_capacity_acres"])
    machine_kind = require_enum(body, "machine_kind", MACHINE_KINDS)
    label = require_type(body, "label", "string")
    daily_capacity_acres = require_type(body, "daily_capacity_acres", "number")
    # Must be > 0 for every machine (ignored for non-COMBINE kinds).
    if daily_capacity_acres <= 0:
        raise ApiError(
            ERR_INVALID_REQUEST, 400, "daily_capacity_acres must be > 0"
        )

    record = stamp_new(
        {
            "season_id": season["id"],
            "machine_kind": machine_kind,
            "label": label,
            "daily_capacity_acres": daily_capacity_acres,
            "status": "AVAILABLE",
        }
    )
    db.machines[record["id"]] = record
    return success_object(public(record), status=201)


@bp.route("/harvest/seasons/<seasonId>/machines", methods=["GET"])
def list_machines_for_season(seasonId):
    require_roles(*ALL_ROLES)
    season = get_season_or_404(seasonId)
    pagination = parse_pagination(request.args)
    items = [m for m in db.machines.values() if m["season_id"] == season["id"]]
    items.sort(key=sort_key)
    page, pag = paginate(items, pagination)
    return success_list([public(r) for r in page], pag)


@bp.route("/harvest/machines", methods=["GET"])
def list_machines():
    require_roles(*ALL_ROLES)
    pagination = parse_pagination(request.args)
    season_id = request.args.get("season_id")
    items = list(db.machines.values())
    if season_id is not None:
        items = [m for m in items if m["season_id"] == season_id]
    items.sort(key=sort_key)
    page, pag = paginate(items, pagination)
    return success_list([public(r) for r in page], pag)


@bp.route("/harvest/machines/<machineId>", methods=["GET"])
def get_machine(machineId):
    require_roles(*ALL_ROLES)
    machine = get_machine_or_404(machineId)
    return success_object(public(machine))


@bp.route("/harvest/machines/<machineId>/report-breakdown", methods=["POST"])
def report_breakdown(machineId):
    require_roles("CrewBoss")
    machine = get_machine_or_404(machineId)
    if machine["status"] != "IN_FIELD":
        raise ApiError(
            ERR_MACHINE_NOT_IN_FIELD, 409, "report-breakdown requires machine IN_FIELD"
        )
    machine["status"] = "DOWN"
    touch(machine)
    # Cascade: every stop holding a DEPLOYED assignment for this machine and
    # itself in CUTTING or PAUSED_WEATHER transitions to PAUSED_WEATHER.
    affected_stop_ids = {
        a["route_stop_id"]
        for a in db.machine_assignments.values()
        if a["machine_id"] == machine["id"] and a["status"] == "DEPLOYED"
    }
    for stop_id in affected_stop_ids:
        stop = db.route_stops.get(stop_id)
        if stop is not None and stop["status"] in ("CUTTING", "PAUSED_WEATHER"):
            if stop["status"] != "PAUSED_WEATHER":
                stop["status"] = "PAUSED_WEATHER"
                touch(stop)
    return success_object(public(machine))


@bp.route("/harvest/machines/<machineId>/dispatch-repair", methods=["POST"])
def dispatch_repair(machineId):
    require_roles("HarvestOperator")
    machine = get_machine_or_404(machineId)
    if machine["status"] != "DOWN":
        raise ApiError(ERR_MACHINE_NOT_DOWN, 409, "dispatch-repair requires machine DOWN")
    machine["status"] = "REPAIRING"
    touch(machine)
    return success_object(public(machine))


@bp.route("/harvest/machines/<machineId>/return-to-service", methods=["POST"])
def return_to_service(machineId):
    require_roles("HarvestOperator")
    machine = get_machine_or_404(machineId)
    if machine["status"] != "REPAIRING":
        raise ApiError(
            ERR_MACHINE_NOT_REPAIRING, 409, "return-to-service requires machine REPAIRING"
        )
    machine["status"] = "AVAILABLE"
    touch(machine)
    return success_object(public(machine))
