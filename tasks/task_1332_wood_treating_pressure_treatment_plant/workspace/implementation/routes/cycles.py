"""TreatmentCycle endpoints (PRD section 3.6)."""

from flask import Blueprint

import calc
from db import store, new_entity, touch, public
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_PLANT_NOT_LICENSED,
    ERR_INVALID_STATE,
    ERR_CYLINDER_NOT_LOADED,
    ERR_CYCLE_NOT_RUNNING,
    ERR_CYCLE_NOT_DRAINING,
    ERR_ASSAY_BELOW_WORKING_MINIMUM,
    ERR_PRESERVATIVE_QUARANTINED,
    ERR_PRESERVATIVE_NOT_FOUND,
)
from middleware import authenticate, authorize
from response import success
from util import (
    body_json, req_field, as_str, as_number, as_int, as_enum,
    resolve_plant, resolve_cylinder, resolve_cycle, paginate, query_filter,
)

bp = Blueprint("cycles", __name__)

PROCESS_TYPES = {"FULL_CELL", "LOWRY", "RUEPING", "SAP_DISPLACEMENT"}
CYCLE_READ_ROLES = ["PlantOperator", "LabTechnician", "QualityManager", "ComplianceOfficer"]


def _find_charge_for_cycle(plant, cyl):
    """Identify the charge a new cycle should run against.

    LOADED cylinder -> the physically present IN_CYLINDER charge.
    IDLE cylinder -> a RE_TREAT_PENDING charge with a TREATMENT slot booked on
    this cylinder (the re-treat path), or an IN_CYLINDER charge left in place
    by an aborted cycle.
    """
    if cyl["status"] == "LOADED":
        present = [
            c for c in store.charges.values()
            if c["cylinder_id"] == cyl["id"] and c["status"] == "IN_CYLINDER"
        ]
        if not present:
            raise ApiError(ERR_INVALID_STATE, 409, "Cylinder is LOADED but holds no IN_CYLINDER charge")
        return sorted(present, key=lambda c: (c["created_at"], c["_seq"]))[0], False
    if cyl["status"] == "IDLE":
        retreat = [
            c for c in store.charges.values()
            if c["plant_id"] == plant["id"]
            and c["status"] == "RE_TREAT_PENDING"
            and any(
                s for s in store.slots.values()
                if s["cylinder_id"] == cyl["id"] and s["slot_kind"] == "TREATMENT" and s["charge_id"] == c["id"]
            )
        ]
        if retreat:
            return sorted(retreat, key=lambda c: (c["created_at"], c["_seq"]))[0], True
        residual = [
            c for c in store.charges.values()
            if c["cylinder_id"] == cyl["id"] and c["status"] == "IN_CYLINDER"
        ]
        if residual:
            return sorted(residual, key=lambda c: (c["created_at"], c["_seq"]))[0], True
        raise ApiError(ERR_CYLINDER_NOT_LOADED, 409, "Cycle scheduling requires a loaded charge or a re-treat slot")
    raise ApiError(ERR_CYLINDER_NOT_LOADED, 409, "Cycle scheduling requires cylinder status LOADED")


@bp.route("/treatment-plants/<plantId>/cylinders/<cylinderId>/cycles", methods=["POST"])
def create_cycle(plantId, cylinderId):
    body = body_json()
    process_type = as_enum(req_field(body, "process_type"), "process_type", PROCESS_TYPES)
    preservative_id = as_str(req_field(body, "preservative_id"), "preservative_id")
    vacuum_inhg = as_number(req_field(body, "vacuum_inhg"), "vacuum_inhg")
    pressure_psi = as_number(req_field(body, "pressure_psi"), "pressure_psi")
    pressure_minutes = as_int(req_field(body, "pressure_minutes"), "pressure_minutes")
    _, role = authenticate()
    authorize(role, ["PlantOperator"])
    plant = resolve_plant(plantId)
    cyl = resolve_cylinder(cylinderId, plant)
    # Priority 4: plant licensing.
    if plant["status"] != "LICENSED":
        raise ApiError(ERR_PLANT_NOT_LICENSED, 409, "Cycle scheduling requires plant status LICENSED")
    pres = store.preservatives.get(preservative_id)
    if pres is None or pres["plant_id"] != plant["id"]:
        raise ApiError(ERR_PRESERVATIVE_NOT_FOUND, 404, "PreservativeConcentrate not found: " + str(preservative_id))
    charge, needs_load = _find_charge_for_cycle(plant, cyl)
    if needs_load:
        # RE_TREAT_PENDING -> IN_CYLINDER (or post-abort reload); cylinder -> LOADED.
        charge["status"] = "IN_CYLINDER"
        charge["cylinder_id"] = cyl["id"]
        touch(charge)
        cyl["status"] = "LOADED"
        touch(cyl)
    cycle_number = max(
        [c["cycle_number"] for c in store.cycles.values() if c["charge_id"] == charge["id"]],
        default=0,
    ) + 1
    cycle = new_entity()
    cycle.update({
        "charge_id": charge["id"],
        "cylinder_id": cyl["id"],
        "plant_id": plant["id"],
        "cycle_number": cycle_number,
        "process_type": process_type,
        "preservative_id": pres["id"],
        "vacuum_inhg": vacuum_inhg,
        "pressure_psi": pressure_psi,
        "pressure_minutes": pressure_minutes,
        "solution_assay_at_start_pct": None,
        "gross_absorption_pcf": 0,
        "abort_reason": None,
        "status": "SCHEDULED",
    })
    store.cycles[cycle["id"]] = cycle
    return success(public(cycle), status=201)


@bp.route("/treatment-plants/<plantId>/cylinders/<cylinderId>/cycles", methods=["GET"])
def list_cylinder_cycles(plantId, cylinderId):
    _, role = authenticate()
    authorize(role, CYCLE_READ_ROLES)
    plant = resolve_plant(plantId)
    cyl = resolve_cylinder(cylinderId, plant)
    items = [c for c in store.cycles.values() if c["cylinder_id"] == cyl["id"]]
    status = query_filter("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    page, meta = paginate(items)
    return success(page, response_type="array", pagination=meta)


@bp.route("/treatment-plants/<plantId>/cylinders/<cylinderId>/cycles/<cycleId>", methods=["GET"])
def get_cycle(plantId, cylinderId, cycleId):
    _, role = authenticate()
    authorize(role, CYCLE_READ_ROLES)
    plant = resolve_plant(plantId)
    cyl = resolve_cylinder(cylinderId, plant)
    return success(public(resolve_cycle(cycleId, cylinder=cyl)))


@bp.route("/treatment-plants/<plantId>/charges/<chargeId>/cycles", methods=["GET"])
def list_charge_cycles(plantId, chargeId):
    _, role = authenticate()
    authorize(role, CYCLE_READ_ROLES)
    plant = resolve_plant(plantId)
    from util import resolve_charge
    charge = resolve_charge(chargeId, plant)
    items = [c for c in store.cycles.values() if c["charge_id"] == charge["id"]]
    status = query_filter("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    page, meta = paginate(items)
    return success(page, response_type="array", pagination=meta)


@bp.route("/treatment-plants/<plantId>/cylinders/<cylinderId>/cycles/<cycleId>/start", methods=["POST"])
def start_cycle(plantId, cylinderId, cycleId):
    _, role = authenticate()
    authorize(role, ["PlantOperator"])
    plant = resolve_plant(plantId)
    cyl = resolve_cylinder(cylinderId, plant)
    cycle = resolve_cycle(cycleId, cylinder=cyl)
    # Priority 4: plant licensing (a SUSPENDED plant freezes new cycle starts).
    if plant["status"] != "LICENSED":
        raise ApiError(ERR_PLANT_NOT_LICENSED, 409, "Cycle start requires plant status LICENSED")
    # Priority 5: resource states.
    if cycle["status"] != "SCHEDULED":
        raise ApiError(ERR_INVALID_STATE, 409, "Cycle start requires cycle status SCHEDULED")
    if cyl["status"] != "LOADED":
        raise ApiError(ERR_CYLINDER_NOT_LOADED, 409, "Cycle start requires cylinder status LOADED")
    pres = store.preservatives.get(cycle["preservative_id"])
    if pres is None:
        raise ApiError(ERR_PRESERVATIVE_NOT_FOUND, 404, "PreservativeConcentrate not found: " + str(cycle["preservative_id"]))
    # Priority 8: working-solution assay minimum.
    if pres["concentrate_assay_pct"] < pres["min_working_assay_pct"]:
        raise ApiError(ERR_ASSAY_BELOW_WORKING_MINIMUM, 422, "concentrate_assay_pct is below min_working_assay_pct")
    # Priority 9: quarantine.
    if pres["status"] == "QUARANTINED":
        raise ApiError(ERR_PRESERVATIVE_QUARANTINED, 422, "PreservativeConcentrate is QUARANTINED")
    if pres["status"] != "IN_STOCK":
        raise ApiError(ERR_INVALID_STATE, 409, "PreservativeConcentrate must be IN_STOCK to start a cycle")

    cycle["solution_assay_at_start_pct"] = pres["concentrate_assay_pct"]
    charge = store.charges.get(cycle["charge_id"])
    consumption = (charge["volume_mbf"] if charge else 0) * calc.CONSUMPTION_GALLONS_PER_MBF
    pres["inventory_gallons"] = max(0, pres["inventory_gallons"] - consumption)
    calc.refresh_stock_status(pres)
    touch(pres)
    cycle["status"] = "RUNNING"
    touch(cycle)
    cyl["status"] = "CYCLE_RUNNING"
    touch(cyl)
    return success(public(cycle))


@bp.route("/treatment-plants/<plantId>/cylinders/<cylinderId>/cycles/<cycleId>/begin-drain", methods=["POST"])
def begin_drain(plantId, cylinderId, cycleId):
    _, role = authenticate()
    authorize(role, ["PlantOperator"])
    plant = resolve_plant(plantId)
    cyl = resolve_cylinder(cylinderId, plant)
    cycle = resolve_cycle(cycleId, cylinder=cyl)
    if cycle["status"] != "RUNNING":
        raise ApiError(ERR_CYCLE_NOT_RUNNING, 409, "begin-drain requires cycle status RUNNING")
    cycle["status"] = "DRAINING"
    touch(cycle)
    cyl["status"] = "DRAINING"
    touch(cyl)
    return success(public(cycle))


@bp.route("/treatment-plants/<plantId>/cylinders/<cylinderId>/cycles/<cycleId>/complete", methods=["POST"])
def complete_cycle(plantId, cylinderId, cycleId):
    body = body_json()
    gross_absorption = as_number(req_field(body, "gross_absorption_pcf"), "gross_absorption_pcf")
    _, role = authenticate()
    authorize(role, ["PlantOperator"])
    plant = resolve_plant(plantId)
    cyl = resolve_cylinder(cylinderId, plant)
    cycle = resolve_cycle(cycleId, cylinder=cyl)
    if cycle["status"] != "DRAINING":
        raise ApiError(ERR_CYCLE_NOT_DRAINING, 409, "complete requires cycle status DRAINING")
    cycle["gross_absorption_pcf"] = gross_absorption
    cycle["status"] = "COMPLETE"
    touch(cycle)
    cyl["status"] = "NEEDS_CLEANING"
    touch(cyl)
    charge = store.charges.get(cycle["charge_id"])
    if charge is not None and charge["status"] == "IN_CYLINDER":
        pieces = [p for p in store.pieces.values() if p["charge_id"] == charge["id"]]
        charge["provisional_retention_pcf"] = calc.provisional_retention(
            charge, pieces, gross_absorption, cycle["solution_assay_at_start_pct"]
        )
        charge["status"] = "CYCLE_COMPLETE"
        touch(charge)
        for piece in pieces:
            if piece["status"] in ("RAW", "INCISED"):
                piece["status"] = "TREATED"
                touch(piece)
    return success(public(cycle))


@bp.route("/treatment-plants/<plantId>/cylinders/<cylinderId>/cycles/<cycleId>/abort", methods=["POST"])
def abort_cycle(plantId, cylinderId, cycleId):
    body = body_json()
    reason = req_field(body, "abort_reason")
    if not isinstance(reason, str) or not reason.strip():
        raise ApiError(ERR_INVALID_REQUEST, 400, "Field abort_reason must be a non-empty string")
    _, role = authenticate()
    authorize(role, ["PlantOperator"])
    plant = resolve_plant(plantId)
    cyl = resolve_cylinder(cylinderId, plant)
    cycle = resolve_cycle(cycleId, cylinder=cyl)
    if cycle["status"] != "RUNNING":
        raise ApiError(ERR_CYCLE_NOT_RUNNING, 409, "abort requires cycle status RUNNING")
    cycle["abort_reason"] = reason
    cycle["status"] = "ABORTED"
    touch(cycle)
    cyl["status"] = "NEEDS_CLEANING"
    touch(cyl)
    # Parent charge remains IN_CYLINDER; consumed preservative is NOT refunded.
    return success(public(cycle))
