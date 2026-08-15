"""RouteStop endpoints (§3.4)."""

from flask import Blueprint, request

from db import db
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_STOP_NOT_SCHEDULED,
    ERR_STOP_NOT_EN_ROUTE,
    ERR_STOP_NOT_CUTTING,
    ERR_STOP_NOT_PAUSED,
    ERR_STOP_NOT_SKIPPABLE,
    ERR_SEASON_NOT_ACTIVE,
    ERR_NO_COMBINE_ASSIGNED,
    ERR_OUT_OF_SEQUENCE,
    ERR_ACRES_OVERRUN,
)
from helpers import (
    get_json_body,
    require_fields,
    require_type,
    is_number,
    parse_date,
    stamp_new,
    touch,
    public,
    sort_key,
    get_contract_or_404,
    get_stop_or_404,
    get_season_or_404,
)
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list, parse_pagination, paginate
from services.domain import (
    recompute_contract_harvested_acres,
    recompute_season_harvested_acres,
    maybe_contract_harvested,
    skip_stop_cascade,
    release_machine_if_unallocated,
)

bp = Blueprint("route_stops", __name__)

ACTIVE_STOP_STATUSES = ("SCHEDULED", "EN_ROUTE", "CUTTING", "PAUSED_WEATHER")


@bp.route("/harvest/contracts/<contractId>/route-stops", methods=["POST"])
def create_route_stop(contractId):
    require_roles("GrowerLiaison")
    contract = get_contract_or_404(contractId)
    body = get_json_body()
    require_fields(
        body,
        ["planned_start_date", "planned_end_date", "planned_acres", "sequence_index"],
    )
    planned_start = parse_date(body["planned_start_date"], "planned_start_date")
    planned_end = parse_date(body["planned_end_date"], "planned_end_date")
    # Inclusive planned window: end must not fall before start.
    if planned_end < planned_start:
        raise ApiError(
            ERR_INVALID_REQUEST,
            400,
            "planned_end_date must not fall before planned_start_date",
        )
    planned_acres = require_type(body, "planned_acres", "number")
    sequence_index = require_type(body, "sequence_index", "int")

    record = stamp_new(
        {
            "contract_id": contract["id"],
            "season_id": contract["season_id"],
            "planned_start_date": body["planned_start_date"],
            "planned_end_date": body["planned_end_date"],
            "planned_acres": planned_acres,
            "actual_acres": 0,
            "sequence_index": sequence_index,
            "status": "SCHEDULED",
        }
    )
    db.route_stops[record["id"]] = record
    return success_object(public(record), status=201)


@bp.route("/harvest/contracts/<contractId>/route-stops", methods=["GET"])
def list_stops_for_contract(contractId):
    require_roles(*ALL_ROLES)
    contract = get_contract_or_404(contractId)
    pagination = parse_pagination(request.args)
    items = [s for s in db.route_stops.values() if s["contract_id"] == contract["id"]]
    items.sort(key=sort_key)
    page, pag = paginate(items, pagination)
    return success_list([public(r) for r in page], pag)


@bp.route("/harvest/route-stops", methods=["GET"])
def list_route_stops():
    require_roles(*ALL_ROLES)
    pagination = parse_pagination(request.args)
    contract_id = request.args.get("contract_id")
    season_id = request.args.get("season_id")
    items = list(db.route_stops.values())
    if contract_id is not None:
        items = [s for s in items if s["contract_id"] == contract_id]
    if season_id is not None:
        items = [s for s in items if s["season_id"] == season_id]
    items.sort(key=sort_key)
    page, pag = paginate(items, pagination)
    return success_list([public(r) for r in page], pag)


@bp.route("/harvest/route-stops/<stopId>", methods=["GET"])
def get_route_stop(stopId):
    require_roles(*ALL_ROLES)
    stop = get_stop_or_404(stopId)
    return success_object(public(stop))


@bp.route("/harvest/route-stops/<stopId>", methods=["PATCH"])
def patch_route_stop(stopId):
    require_roles("CrewBoss")
    stop = get_stop_or_404(stopId)
    # actual_acres editable only while CUTTING or PAUSED_WEATHER.
    if stop["status"] not in ("CUTTING", "PAUSED_WEATHER"):
        raise ApiError(
            ERR_STOP_NOT_CUTTING,
            409,
            "actual_acres is editable only while stop is CUTTING or PAUSED_WEATHER",
        )
    body = get_json_body()
    require_fields(body, ["actual_acres"])
    actual_acres = require_type(body, "actual_acres", "number")
    stop["actual_acres"] = actual_acres
    touch(stop)
    return success_object(public(stop))


@bp.route("/harvest/route-stops/<stopId>/depart", methods=["POST"])
def depart_stop(stopId):
    require_roles("CrewBoss")
    stop = get_stop_or_404(stopId)
    if stop["status"] != "SCHEDULED":
        raise ApiError(ERR_STOP_NOT_SCHEDULED, 409, "depart requires stop SCHEDULED")
    season = get_season_or_404(stop["season_id"])
    if season["status"] != "ACTIVE":
        raise ApiError(ERR_SEASON_NOT_ACTIVE, 409, "Operation requires season ACTIVE")
    # §2.6: sequence-ordering check is evaluated BEFORE combine-presence.
    for other in db.route_stops.values():
        if (
            other["id"] != stop["id"]
            and other["season_id"] == stop["season_id"]
            and other["sequence_index"] < stop["sequence_index"]
            and other["status"] in ACTIVE_STOP_STATUSES
        ):
            raise ApiError(
                ERR_OUT_OF_SEQUENCE,
                409,
                "Earlier sequence_index stop is still active in this season",
            )
    has_combine = any(
        a["route_stop_id"] == stop["id"]
        and a["status"] in ("RESERVED", "DEPLOYED")
        and db.machines[a["machine_id"]]["machine_kind"] == "COMBINE"
        for a in db.machine_assignments.values()
        if a["machine_id"] in db.machines
    )
    if not has_combine:
        raise ApiError(
            ERR_NO_COMBINE_ASSIGNED,
            409,
            "Stop lacks a RESERVED or DEPLOYED COMBINE assignment",
        )
    # Side effects: RESERVED assignments → DEPLOYED; machines ASSIGNED → IN_FIELD.
    for a in db.machine_assignments.values():
        if a["route_stop_id"] == stop["id"] and a["status"] == "RESERVED":
            a["status"] = "DEPLOYED"
            touch(a)
            machine = db.machines[a["machine_id"]]
            if machine["status"] == "ASSIGNED":
                machine["status"] = "IN_FIELD"
                touch(machine)
    stop["status"] = "EN_ROUTE"
    touch(stop)
    return success_object(public(stop))


@bp.route("/harvest/route-stops/<stopId>/start-cutting", methods=["POST"])
def start_cutting(stopId):
    require_roles("CrewBoss")
    stop = get_stop_or_404(stopId)
    if stop["status"] != "EN_ROUTE":
        raise ApiError(
            ERR_STOP_NOT_EN_ROUTE, 409, "start-cutting requires stop EN_ROUTE"
        )
    has_deployed_combine = any(
        a["route_stop_id"] == stop["id"]
        and a["status"] == "DEPLOYED"
        and db.machines[a["machine_id"]]["status"] == "IN_FIELD"
        and db.machines[a["machine_id"]]["machine_kind"] == "COMBINE"
        for a in db.machine_assignments.values()
        if a["machine_id"] in db.machines
    )
    if not has_deployed_combine:
        raise ApiError(
            ERR_NO_COMBINE_ASSIGNED,
            409,
            "Stop lacks a DEPLOYED IN_FIELD COMBINE assignment",
        )
    stop["status"] = "CUTTING"
    touch(stop)
    # System cascade: parent contract COMMITTED → IN_PROGRESS.
    contract = get_contract_or_404(stop["contract_id"])
    if contract["status"] == "COMMITTED":
        contract["status"] = "IN_PROGRESS"
        touch(contract)
    return success_object(public(stop))


@bp.route("/harvest/route-stops/<stopId>/pause-weather", methods=["POST"])
def pause_weather(stopId):
    require_roles("CrewBoss")
    stop = get_stop_or_404(stopId)
    if stop["status"] != "CUTTING":
        raise ApiError(
            ERR_STOP_NOT_CUTTING, 409, "pause-weather requires stop CUTTING"
        )
    stop["status"] = "PAUSED_WEATHER"
    touch(stop)
    return success_object(public(stop))


@bp.route("/harvest/route-stops/<stopId>/resume", methods=["POST"])
def resume_stop(stopId):
    require_roles("CrewBoss")
    stop = get_stop_or_404(stopId)
    if stop["status"] != "PAUSED_WEATHER":
        raise ApiError(ERR_STOP_NOT_PAUSED, 409, "resume requires stop PAUSED_WEATHER")
    stop["status"] = "CUTTING"
    touch(stop)
    return success_object(public(stop))


@bp.route("/harvest/route-stops/<stopId>/complete", methods=["POST"])
def complete_stop(stopId):
    require_roles("CrewBoss")
    stop = get_stop_or_404(stopId)
    if stop["status"] != "CUTTING":
        raise ApiError(ERR_STOP_NOT_CUTTING, 409, "complete requires stop CUTTING")
    actual = stop.get("actual_acres", 0)
    planned = stop.get("planned_acres", 0)
    # actual_acres must be > 0 and <= planned_acres * 1.10.
    if not is_number(actual) or actual <= 0 or actual > planned * 1.10:
        raise ApiError(
            ERR_ACRES_OVERRUN,
            422,
            "actual_acres must be > 0 and <= planned_acres * 1.10 on complete",
        )
    # Cascade 1: DEPLOYED assignments → RELEASED; machines IN_FIELD →
    # AVAILABLE if not allocated to any other DEPLOYED assignment.
    for a in db.machine_assignments.values():
        if a["route_stop_id"] == stop["id"] and a["status"] == "DEPLOYED":
            a["status"] = "RELEASED"
            touch(a)
            release_machine_if_unallocated(a["machine_id"], exclude_assignment_id=a["id"])
    # Cascade 2: BOOKED / CHECKED_IN lodging on this stop → CHECKED_OUT.
    for r in db.lodging_reservations.values():
        if r["route_stop_id"] == stop["id"] and r["status"] in ("BOOKED", "CHECKED_IN"):
            r["status"] = "CHECKED_OUT"
            touch(r)
    stop["status"] = "COMPLETED"
    touch(stop)
    # Cascade 3: contract harvested_acres; auto-transition to HARVESTED when
    # every stop is terminal.
    contract = get_contract_or_404(stop["contract_id"])
    recompute_contract_harvested_acres(contract)
    maybe_contract_harvested(contract)
    # Cascade 4: season harvested_acres_total.
    season = get_season_or_404(stop["season_id"])
    recompute_season_harvested_acres(season)
    return success_object(public(stop))


@bp.route("/harvest/route-stops/<stopId>/skip", methods=["POST"])
def skip_stop(stopId):
    require_roles("HarvestOperator")
    stop = get_stop_or_404(stopId)
    if stop["status"] != "SCHEDULED":
        raise ApiError(ERR_STOP_NOT_SKIPPABLE, 409, "skip requires stop SCHEDULED")
    skip_stop_cascade(stop)
    return success_object(public(stop))
