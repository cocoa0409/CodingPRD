from flask import Blueprint

import constants as C
import validators as V
from auth import authorize
from domain import (
    agent_duty_conflict, agent_holds_required_certs, agent_projected_daily_minutes,
    apply_changes, gse_occupation_conflict, gse_service_hold_conflict,
    recompute_agent_ledger, recompute_gse_ledger, recompute_turn_coverage,
    select_gse_unit, serialize_turn_resource,
)
from envelope import filter_equals, paginate, respond_object
from errors import ApiError
from store import as_dt, db, new_record, ordered, require, whole_minutes_between

bp = Blueprint("turn_resources", __name__)


@bp.post("/turn-resources")
def create_turn_resource():
    authorize([C.ROLE_DUTY_OFFICER])
    payload = V.body()

    # ---- step 4: request shape -------------------------------------------
    turn_id = V.req_string(payload, "turn_id")
    resource_kind = V.req_enum(payload, "resource_kind", C.RESOURCE_KINDS)
    window_start = V.req_datetime(payload, "window_start")
    window_end = V.req_datetime(payload, "window_end")
    expected_turn_version = V.req_int(payload, "expected_turn_version")
    if as_dt(window_end) <= as_dt(window_start):
        raise ApiError("ERR_INVALID_REQUEST", "window_end must be strictly after window_start.")

    agent_id = None
    gse_unit_id = None
    gse_type = None
    role_on_turn = None
    if resource_kind == "AGENT":
        agent_id = V.req_string(payload, "agent_id")
        role_on_turn = V.req_enum(payload, "role_on_turn", C.RAMP_ROLES)
        V.forbid(payload, "gse_unit_id")
        V.forbid(payload, "gse_type")
    else:
        V.forbid(payload, "agent_id")
        V.forbid(payload, "role_on_turn")
        has_unit = V.present(payload, "gse_unit_id")
        has_type = V.present(payload, "gse_type")
        if has_unit == has_type:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "a GSE occupation carries exactly one of gse_unit_id or gse_type.",
            )
        if has_unit:
            gse_unit_id = V.req_string(payload, "gse_unit_id")
        else:
            gse_type = V.req_enum(payload, "gse_type", C.GSE_TYPES)

    # ---- step 5: body foreign keys ---------------------------------------
    turn = require(db.turns, turn_id, "Turn")
    agent = require(db.agents, agent_id, "Agent") if agent_id else None
    unit = require(db.gse_units, gse_unit_id, "GseUnit") if gse_unit_id else None

    station = db.stations[turn["station_id"]]

    # ---- step 6: station-scope coherence ---------------------------------
    if agent is not None and agent["station_id"] != turn["station_id"]:
        raise ApiError("ERR_STATION_SCOPE_MISMATCH")
    if unit is not None and unit["station_id"] != turn["station_id"]:
        raise ApiError("ERR_STATION_SCOPE_MISMATCH")

    # ---- step 7: stale-view protection -----------------------------------
    if expected_turn_version != turn["version"]:
        raise ApiError("ERR_STALE_TURN_VERSION")

    # ---- step 10: own-state admissibility --------------------------------
    if turn["status"] not in ("SCHEDULED", "RESOURCED"):
        raise ApiError("ERR_TURN_NOT_ASSIGNABLE")

    # ---- step 11: cross-entity state gates -------------------------------
    if station["status"] != "OPEN":
        raise ApiError("ERR_STATION_NOT_OPEN")
    if agent is not None:
        if agent["status"] != "ACTIVE":
            raise ApiError("ERR_AGENT_NOT_ACTIVE")
        if agent["subcontractor_id"]:
            sub = db.subcontractors.get(agent["subcontractor_id"])
            if sub is None or sub["status"] not in ("APPROVED", "PROBATION"):
                raise ApiError("ERR_SUBCONTRACTOR_NOT_APPROVED")
    if unit is not None and unit["status"] != "AVAILABLE":
        raise ApiError("ERR_GSE_NOT_SERVICEABLE")

    start = as_dt(window_start)
    end = as_dt(window_end)

    # ---- step 12: safety gates -------------------------------------------
    if agent is not None:
        if station["oversight_posture"] == "ENHANCED" \
                and agent["employment_type"] == "SUBCONTRACTED":
            raise ApiError("ERR_STATION_POSTURE_RESTRICTED")
        if not agent_holds_required_certs(agent, turn["station_id"], role_on_turn, start):
            raise ApiError("ERR_CERT_NOT_CURRENT")

    # ---- step 13: interval geometry --------------------------------------
    buffer_minutes = station["gse_reposition_buffer_minutes"]
    if unit is not None:
        if gse_occupation_conflict(unit, start, end, buffer_minutes):
            raise ApiError("ERR_GSE_WINDOW_CONFLICT")
        if gse_service_hold_conflict(unit, start, end):
            raise ApiError("ERR_GSE_SERVICE_HOLD_CONFLICT")
    if agent is not None and agent_duty_conflict(agent, start, end):
        raise ApiError("ERR_AGENT_DUTY_OVERLAP")

    occupied_minutes = whole_minutes_between(start, end)

    # ---- step 14: aggregates, uniqueness and the selector pool -----------
    if agent is not None:
        projected = agent_projected_daily_minutes(agent, start, occupied_minutes)
        if projected > C.MAX_DUTY_MINUTES_PER_DAY:
            raise ApiError("ERR_AGENT_DUTY_LIMIT_EXCEEDED")
    if resource_kind == "GSE" and unit is None:
        unit = select_gse_unit(station, turn, gse_type, start, end)
        if unit is None:
            raise ApiError("ERR_NO_ELIGIBLE_GSE")

    resource = new_record("TurnResource", {
        "turn_id": turn["id"],
        "agent_id": agent["id"] if agent else None,
        "gse_unit_id": unit["id"] if unit else None,
        "resource_kind": resource_kind,
        "role_on_turn": role_on_turn,
        "gse_type": gse_type,
        "window_start": window_start,
        "window_end": window_end,
        "occupied_minutes": occupied_minutes,
        "status": "RESERVED",
        "cancel_reason": None,
    })
    db.turn_resources[resource["id"]] = resource

    if agent is not None:
        recompute_agent_ledger(agent)
    if unit is not None:
        recompute_gse_ledger(unit)
    recompute_turn_coverage(turn)

    return respond_object(serialize_turn_resource(resource), 201)


@bp.get("/turn-resources/<turn_resource_id>")
def read_turn_resource(turn_resource_id):
    authorize(C.ALL_ROLES)
    resource = require(db.turn_resources, turn_resource_id, "TurnResource")
    return respond_object(serialize_turn_resource(resource))


@bp.get("/turn-resources")
def list_turn_resources():
    authorize(C.ALL_ROLES)
    records = filter_equals(db.turn_resources.values(), {
        "turn_id": "turn_id",
        "agent_id": "agent_id",
        "gse_unit_id": "gse_unit_id",
        "status": "status",
        "resource_kind": "resource_kind",
    })
    return paginate(ordered(records), serialize_turn_resource)


@bp.post("/turn-resources/<turn_resource_id>/release")
def release_turn_resource(turn_resource_id):
    authorize([C.ROLE_DUTY_OFFICER])
    resource = require(db.turn_resources, turn_resource_id, "TurnResource")
    payload = V.body()
    V.opt_string(payload, "reason")

    if resource["status"] not in ("RESERVED", "COMMITTED"):
        raise ApiError("ERR_INVALID_STATE")

    apply_changes(resource, {"status": "RELEASED"})
    if resource["resource_kind"] == "AGENT":
        agent = db.agents.get(resource["agent_id"])
        if agent:
            recompute_agent_ledger(agent)
    else:
        unit = db.gse_units.get(resource["gse_unit_id"])
        if unit:
            recompute_gse_ledger(unit)
    turn = db.turns.get(resource["turn_id"])
    if turn:
        recompute_turn_coverage(turn)

    return respond_object(serialize_turn_resource(resource))
