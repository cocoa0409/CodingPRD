"""IndexDefinition endpoints (PRD §3.2)."""

from flask import Blueprint, request

import db
from errors import (
    err, ERR_INVALID_REQUEST, ERR_INDEX_NOT_PENDING, ERR_INDEX_NOT_ACTIVE,
    ERR_INDEX_NOT_SUSPENDED, ERR_INDEX_IN_USE, ERR_NO_COMMISSIONED_STATION,
)
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list
from routes.common import (
    body, require_fields, require_enum, pagination_params, paginate,
    sorted_by_created, get_program, get_index_in_program,
)
from services import domain

bp = Blueprint("indexes", __name__)

SOURCE_MODES = {"STATION_PRIMARY", "MODEL_PRIMARY"}
STRIKE_DIRECTIONS = {"BELOW", "ABOVE"}
UNITS = {"mm", "m/s", "Mw", "degC"}


def _validate_thresholds(thresholds):
    if not isinstance(thresholds, list) or not thresholds:
        raise err(ERR_INVALID_REQUEST, 400, "trigger_thresholds must be a non-empty list")
    for t in thresholds:
        if not isinstance(t, dict) or "tier" not in t or "threshold_value" not in t or "payout_fraction" not in t:
            raise err(ERR_INVALID_REQUEST, 400, "Each threshold requires tier, threshold_value, payout_fraction")
        pf = t["payout_fraction"]
        if not isinstance(pf, (int, float)) or pf <= 0 or pf > 1:
            raise err(ERR_INVALID_REQUEST, 400, "payout_fraction must be in (0,1]")


@bp.post("/programs/<programId>/index-definitions")
def create_index(programId):
    require_roles("Actuary")
    prog = get_program(programId)
    data = body()
    require_fields(data, ["index_code", "measurement_unit", "aggregation_window_days",
                          "data_source_agreement_ref", "source_priority_mode",
                          "trigger_thresholds", "strike_direction",
                          "historical_breach_frequency", "expected_loss_ratio"])
    require_enum(data, "source_priority_mode", SOURCE_MODES)
    require_enum(data, "strike_direction", STRIKE_DIRECTIONS)
    if not isinstance(data["data_source_agreement_ref"], str) or not data["data_source_agreement_ref"]:
        raise err(ERR_INVALID_REQUEST, 400, "data_source_agreement_ref must be non-empty")
    _validate_thresholds(data["trigger_thresholds"])
    idx = domain.stamp_new({
        "program_id": prog["id"],
        "index_code": data["index_code"],
        "measurement_unit": data["measurement_unit"],
        "aggregation_window_days": data["aggregation_window_days"],
        "data_source_agreement_ref": data["data_source_agreement_ref"],
        "source_priority_mode": data["source_priority_mode"],
        "trigger_thresholds": data["trigger_thresholds"],
        "strike_direction": data["strike_direction"],
        "historical_breach_frequency": data["historical_breach_frequency"],
        "expected_loss_ratio": data["expected_loss_ratio"],
        "status": "PENDING_AGREEMENT",
    })
    db.index_definitions[idx["id"]] = idx
    return success_object(domain.serialize(idx), 201)


@bp.get("/programs/<programId>/index-definitions")
def list_indexes(programId):
    require_roles(*ALL_ROLES)
    domain.run_expiry_sweep()
    prog = get_program(programId)
    limit, offset = pagination_params()
    items = sorted_by_created(
        i for i in db.index_definitions.values() if i["program_id"] == prog["id"]
    )
    page, total = paginate(items, limit, offset)
    return success_list(domain.serialize_list(page), limit, offset, total)


@bp.get("/programs/<programId>/index-definitions/<indexId>")
def get_index(programId, indexId):
    require_roles(*ALL_ROLES)
    domain.run_expiry_sweep()
    prog = get_program(programId)
    idx = get_index_in_program(prog, indexId)
    return success_object(domain.serialize(idx))


@bp.post("/programs/<programId>/index-definitions/<indexId>/activate")
def activate_index(programId, indexId):
    require_roles("Actuary")
    prog = get_program(programId)
    idx = get_index_in_program(prog, indexId)
    if idx["status"] != "PENDING_AGREEMENT":
        raise err(ERR_INDEX_NOT_PENDING, 409, "Index activation requires PENDING_AGREEMENT")
    has_station = any(
        s["program_id"] == prog["id"] and s["status"] == "COMMISSIONED"
        for s in db.stations.values()
    )
    if not has_station:
        raise err(ERR_NO_COMMISSIONED_STATION, 409,
                  "Index activation requires at least one COMMISSIONED station in the program")
    idx["status"] = "ACTIVE"
    domain.touch(idx)
    return success_object(domain.serialize(idx))


@bp.post("/programs/<programId>/index-definitions/<indexId>/suspend")
def suspend_index(programId, indexId):
    require_roles("ProgramManager")
    prog = get_program(programId)
    idx = get_index_in_program(prog, indexId)
    if idx["status"] != "ACTIVE":
        raise err(ERR_INDEX_NOT_ACTIVE, 409, "Operation requires index status ACTIVE")
    idx["status"] = "SUSPENDED"
    domain.touch(idx)
    return success_object(domain.serialize(idx))


@bp.post("/programs/<programId>/index-definitions/<indexId>/resume")
def resume_index(programId, indexId):
    require_roles("ProgramManager")
    prog = get_program(programId)
    idx = get_index_in_program(prog, indexId)
    if idx["status"] != "SUSPENDED":
        raise err(ERR_INDEX_NOT_SUSPENDED, 409, "Index resume requires SUSPENDED")
    idx["status"] = "ACTIVE"
    domain.touch(idx)
    return success_object(domain.serialize(idx))


@bp.post("/programs/<programId>/index-definitions/<indexId>/decommission")
def decommission_index(programId, indexId):
    require_roles("Actuary")
    domain.run_expiry_sweep()
    prog = get_program(programId)
    idx = get_index_in_program(prog, indexId)
    # Precondition: no BOUND policy references this index; no DETECTED/UNDER_REVIEW events
    for p in db.policies.values():
        if p["index_definition_id"] == idx["id"] and p["lifecycle_status"] == "BOUND":
            raise err(ERR_INDEX_IN_USE, 409,
                      "Index decommission blocked by BOUND policies or open trigger events")
    for ev in db.trigger_events.values():
        if ev["index_definition_id"] == idx["id"] and ev["status"] in ("DETECTED", "UNDER_REVIEW"):
            raise err(ERR_INDEX_IN_USE, 409,
                      "Index decommission blocked by BOUND policies or open trigger events")
    idx["status"] = "DECOMMISSIONED"
    domain.touch(idx)
    return success_object(domain.serialize(idx))


# --- Flat reverse-reachability reads ---

@bp.get("/programs/index-definitions")
def list_indexes_flat():
    require_roles(*ALL_ROLES)
    domain.run_expiry_sweep()
    limit, offset = pagination_params()
    program_id = request.args.get("program_id")
    items = list(db.index_definitions.values())
    if program_id is not None:
        items = [i for i in items if i["program_id"] == program_id]
    items = sorted_by_created(items)
    page, total = paginate(items, limit, offset)
    return success_list(domain.serialize_list(page), limit, offset, total)


@bp.get("/programs/index-definitions/<indexId>")
def get_index_flat(indexId):
    require_roles(*ALL_ROLES)
    domain.run_expiry_sweep()
    idx = db.index_definitions.get(indexId)
    if not idx:
        from errors import ERR_INDEX_NOT_FOUND
        raise err(ERR_INDEX_NOT_FOUND, 404, "Index definition id does not exist")
    return success_object(domain.serialize(idx))
