"""Placement endpoints: release and malfunction reporting."""
from flask import Blueprint

from calc import malfunction_severity_tier
from core import (
    LOGISTICS_READERS,
    ROLE_THERAPIST,
    ApiError,
    authenticate,
    db,
    enum_filter,
    now,
    paginate,
    pagination,
    respond,
    sorted_rows,
    str_filter,
    touch,
)
from domain import apply_risk_variant, get_contract, get_placement, recompute_allowable
from serial import placement_out
from validate import Field, validate

bp = Blueprint("placements", __name__)

PLACEMENT_ROLES = ("PRIMARY_STATIONARY", "PORTABLE", "BACKUP")
PLACEMENT_STATUSES = ("RESERVED", "PLACED", "REMOVED", "RECALLED_OUT_OF_SERVICE")
SYMPTOMS = ("NO_FLOW", "ALARM_CONTINUOUS", "LOW_PURITY", "POWER_FAILURE", "LEAK")

MALFUNCTION_FIELDS = [
    Field("symptom", "enum", required=True, enum=SYMPTOMS),
    Field("oxygen_gap_minutes", "integer", required=True, minimum=0),
]


@bp.get("/placements")
def list_placements():
    authenticate(LOGISTICS_READERS)
    contract_id = str_filter("contract_id")
    unit_id = str_filter("equipment_unit_id")
    role = enum_filter("role", PLACEMENT_ROLES)
    status = enum_filter("status", PLACEMENT_STATUSES)
    limit, offset = pagination()
    rows = sorted_rows(db.placements.values())
    if contract_id is not None:
        rows = [r for r in rows if r["contract_id"] == contract_id]
    if unit_id is not None:
        rows = [r for r in rows if r["equipment_unit_id"] == unit_id]
    if role is not None:
        rows = [r for r in rows if r["role"] == role]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate(rows, limit, offset, placement_out)


@bp.get("/placements/<placement_id>")
def read_placement(placement_id):
    authenticate(LOGISTICS_READERS)
    return respond(placement_out(get_placement(placement_id)))


@bp.delete("/placements/<placement_id>")
def release_placement(placement_id):
    """Compensating counterpart of the equipment assignment."""
    authenticate((ROLE_THERAPIST,))
    placement = get_placement(placement_id)
    if placement["status"] != "RESERVED":
        raise ApiError("ERR_INVALID_STATE")
    placement["status"] = "REMOVED"
    placement["removal_reason"] = "RELEASED"
    placement["removed_at"] = now()
    touch(placement)
    unit = db.equipment_units.get(placement["equipment_unit_id"])
    if unit is not None and unit["status"] == "RESERVED":
        unit["status"] = "IN_STOCK"
        touch(unit)
    contract = db.contracts.get(placement["contract_id"])
    if contract is not None:
        recompute_allowable(contract)
        touch(contract)
    return respond(placement_out(placement))


@bp.post("/placements/<placement_id>/malfunction")
def report_malfunction(placement_id):
    """File a malfunction report; TIER_1 pulls the unit out of service."""
    authenticate((ROLE_THERAPIST,))
    placement = get_placement(placement_id)
    data = validate(MALFUNCTION_FIELDS)
    if placement["status"] != "PLACED":
        raise ApiError("ERR_INVALID_STATE")
    gap = data["oxygen_gap_minutes"]
    tier = malfunction_severity_tier(data["symptom"], gap)
    contract = get_contract(placement["contract_id"])
    placement["last_symptom"] = data["symptom"]
    placement["last_severity_tier"] = tier
    placement["malfunction_count"] += 1
    contract["malfunction_count"] += 1
    contract["cumulative_oxygen_gap_minutes"] += gap
    if tier == "TIER_1":
        placement["status"] = "REMOVED"
        placement["removal_reason"] = "MALFUNCTION"
        placement["removed_at"] = now()
        unit = db.equipment_units.get(placement["equipment_unit_id"])
        if unit is not None and unit["status"] == "DEPLOYED":
            unit["status"] = "IN_QUARANTINE"
            unit["quarantine_reason"] = "MALFUNCTION"
            touch(unit)
        recompute_allowable(contract)
    touch(placement)
    touch(contract)
    patient = db.patients.get(contract["patient_id"])
    if patient is not None:
        apply_risk_variant(patient, "ONGOING_SURVEILLANCE")
    return respond(placement_out(placement))
