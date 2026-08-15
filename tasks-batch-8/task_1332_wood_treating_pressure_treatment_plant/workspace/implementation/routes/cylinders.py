"""TreatmentCylinder and CylinderScheduleSlot endpoints (PRD section 3.2)."""

from datetime import timedelta

from flask import Blueprint

from db import store, new_entity, touch, public, fmt_ts
from errors import (
    ApiError,
    ERR_INVALID_STATE,
    ERR_INVALID_TIME_RANGE,
    ERR_CYLINDER_SLOT_CONFLICT,
    ERR_SLOT_CHARGE_INVALID,
    ERR_CHARGE_NOT_FOUND,
    ERR_SLOT_IN_PAST,
)
from middleware import authenticate, authorize
from response import success
from util import (
    body_json, req_field, as_str, as_number, as_list, as_enum, as_int, parse_ts,
    resolve_plant, resolve_cylinder, resolve_slot, paginate, query_filter,
    parse_query_ts,
)

bp = Blueprint("cylinders", __name__)

PROCESS_TYPES = {"FULL_CELL", "LOWRY", "RUEPING", "SAP_DISPLACEMENT"}
SLOT_KINDS = {"TREATMENT", "CLEANING", "MAINTENANCE"}

CYL_READ_ROLES = ["PlantOperator", "LabTechnician", "QualityManager", "QualityAgencyInspector", "ComplianceOfficer"]
SLOT_READ_ROLES = ["PlantOperator", "QualityManager", "ComplianceOfficer"]


@bp.route("/treatment-plants/<plantId>/cylinders", methods=["POST"])
def create_cylinder(plantId):
    body = body_json()
    cylinder_code = as_str(req_field(body, "cylinder_code"), "cylinder_code")
    max_volume_mbf = as_number(req_field(body, "max_volume_mbf"), "max_volume_mbf")
    supported = as_list(req_field(body, "supported_process_types"), "supported_process_types")
    for pt in supported:
        as_enum(pt, "supported_process_types", PROCESS_TYPES)
    _, role = authenticate()
    authorize(role, ["PlantOperator"])
    plant = resolve_plant(plantId)
    cyl = new_entity()
    cyl.update({
        "plant_id": plant["id"],
        "cylinder_code": cylinder_code,
        "max_volume_mbf": max_volume_mbf,
        "supported_process_types": supported,
        "status": "IDLE",
    })
    store.cylinders[cyl["id"]] = cyl
    return success(public(cyl), status=201)


@bp.route("/treatment-plants/<plantId>/cylinders/<cylinderId>", methods=["GET"])
def get_cylinder(plantId, cylinderId):
    _, role = authenticate()
    authorize(role, CYL_READ_ROLES)
    plant = resolve_plant(plantId)
    return success(public(resolve_cylinder(cylinderId, plant)))


@bp.route("/treatment-plants/<plantId>/cylinders/<cylinderId>/mark-cleaned", methods=["POST"])
def mark_cleaned(plantId, cylinderId):
    _, role = authenticate()
    authorize(role, ["PlantOperator"])
    plant = resolve_plant(plantId)
    cyl = resolve_cylinder(cylinderId, plant)
    if cyl["status"] != "NEEDS_CLEANING":
        raise ApiError(ERR_INVALID_STATE, 409, "mark-cleaned requires cylinder status NEEDS_CLEANING")
    cyl["status"] = "IDLE"
    touch(cyl)
    # Close the cylinder's CLEANING slot(s).
    now = store.clock
    for slot in list(store.slots.values()):
        if slot["cylinder_id"] == cyl["id"] and slot["slot_kind"] == "CLEANING" and slot["_end_dt"] > now:
            del store.slots[slot["id"]]
    return success(public(cyl))


@bp.route("/treatment-plants/<plantId>/cylinders/<cylinderId>/decommission", methods=["POST"])
def decommission(plantId, cylinderId):
    _, role = authenticate()
    authorize(role, ["PlantOperator"])
    plant = resolve_plant(plantId)
    cyl = resolve_cylinder(cylinderId, plant)
    if cyl["status"] != "IDLE":
        raise ApiError(ERR_INVALID_STATE, 409, "Decommission requires cylinder status IDLE")
    now = store.clock
    future_slots = [s for s in store.slots.values() if s["cylinder_id"] == cyl["id"] and s["_end_dt"] > now]
    if future_slots:
        raise ApiError(ERR_INVALID_STATE, 409, "Decommission requires no future CylinderScheduleSlot")
    cyl["status"] = "DECOMMISSIONED"
    touch(cyl)
    return success(public(cyl))


@bp.route("/treatment-plants/<plantId>/cylinders/<cylinderId>/charges", methods=["GET"])
def list_cylinder_charges(plantId, cylinderId):
    _, role = authenticate()
    authorize(role, CYL_READ_ROLES)
    plant = resolve_plant(plantId)
    cyl = resolve_cylinder(cylinderId, plant)
    items = [c for c in store.charges.values() if c["cylinder_id"] == cyl["id"]]
    status = query_filter("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    page, meta = paginate(items)
    return success(page, response_type="array", pagination=meta)


# --- CylinderScheduleSlot ---

def _slot_view(slot):
    out = public(slot)
    return out


@bp.route("/treatment-plants/<plantId>/cylinders/<cylinderId>/slots", methods=["POST"])
def create_slot(plantId, cylinderId):
    body = body_json()
    slot_start = parse_ts(req_field(body, "slot_start"), "slot_start")
    slot_end = parse_ts(req_field(body, "slot_end"), "slot_end")
    slot_kind = as_enum(req_field(body, "slot_kind"), "slot_kind", SLOT_KINDS)
    buffer_minutes = 30
    if "buffer_minutes" in body and body["buffer_minutes"] is not None:
        buffer_minutes = as_int(body["buffer_minutes"], "buffer_minutes")
    charge_id = body.get("charge_id")
    if charge_id is not None:
        as_str(charge_id, "charge_id")
    if slot_end <= slot_start:
        raise ApiError(ERR_INVALID_TIME_RANGE, 400, "slot_end must be > slot_start")
    _, role = authenticate()
    authorize(role, ["PlantOperator"])
    plant = resolve_plant(plantId)
    cyl = resolve_cylinder(cylinderId, plant)

    # Overlap check on effective half-open intervals [start, end + buffer);
    # only slots whose slot_end lies in the future participate. Adjacency
    # (new start == existing effective end) is allowed.
    now = store.clock
    new_eff_end = slot_end + timedelta(minutes=buffer_minutes)
    for existing in store.slots.values():
        if existing["cylinder_id"] != cyl["id"]:
            continue
        if existing["_end_dt"] <= now:
            continue
        existing_eff_end = existing["_end_dt"] + timedelta(minutes=existing["buffer_minutes"])
        if slot_start < existing_eff_end and existing["_start_dt"] < new_eff_end:
            raise ApiError(ERR_CYLINDER_SLOT_CONFLICT, 409, "Effective slot intersects another effective slot on this cylinder")

    # Slot-to-charge referential validity.
    if charge_id is not None:
        charge = store.charges.get(charge_id)
        if charge is None:
            raise ApiError(ERR_CHARGE_NOT_FOUND, 404, "Charge not found: " + str(charge_id))
        if charge["status"] not in ("STAGED", "RE_TREAT_PENDING"):
            raise ApiError(ERR_SLOT_CHARGE_INVALID, 422, "charge_id must reference a Charge in STAGED or RE_TREAT_PENDING")

    slot = new_entity(with_version=False)
    slot.update({
        "cylinder_id": cyl["id"],
        "charge_id": charge_id,
        "slot_start": fmt_ts(slot_start),
        "slot_end": fmt_ts(slot_end),
        "slot_kind": slot_kind,
        "buffer_minutes": buffer_minutes,
        "_start_dt": slot_start,
        "_end_dt": slot_end,
    })
    store.slots[slot["id"]] = slot
    return success(_slot_view(slot), status=201)


def _filter_slots(items):
    kind = query_filter("slot_kind")
    if kind is not None:
        items = [s for s in items if s["slot_kind"] == kind]
    charge_id = query_filter("charge_id")
    if charge_id is not None:
        items = [s for s in items if s["charge_id"] == charge_id]
    cylinder_id = query_filter("cylinder_id")
    if cylinder_id is not None:
        items = [s for s in items if s["cylinder_id"] == cylinder_id]
    from_dt = parse_query_ts(query_filter("from_iso"), "from_iso")
    to_dt = parse_query_ts(query_filter("to_iso"), "to_iso")
    if from_dt is not None:
        items = [s for s in items if s["_start_dt"] >= from_dt]
    if to_dt is not None:
        items = [s for s in items if s["_end_dt"] <= to_dt]
    return items


@bp.route("/treatment-plants/<plantId>/cylinders/<cylinderId>/slots", methods=["GET"])
def list_cylinder_slots(plantId, cylinderId):
    _, role = authenticate()
    authorize(role, SLOT_READ_ROLES)
    plant = resolve_plant(plantId)
    cyl = resolve_cylinder(cylinderId, plant)
    items = [s for s in store.slots.values() if s["cylinder_id"] == cyl["id"]]
    items = _filter_slots(items)
    page, meta = paginate(items)
    return success(page, response_type="array", pagination=meta)


@bp.route("/treatment-plants/<plantId>/cylinders/<cylinderId>/slots/<slotId>", methods=["GET"])
def get_slot(plantId, cylinderId, slotId):
    _, role = authenticate()
    authorize(role, SLOT_READ_ROLES)
    plant = resolve_plant(plantId)
    cyl = resolve_cylinder(cylinderId, plant)
    return success(_slot_view(resolve_slot(slotId, cyl)))


@bp.route("/treatment-plants/<plantId>/cylinders/<cylinderId>/slots/<slotId>", methods=["DELETE"])
def delete_slot(plantId, cylinderId, slotId):
    _, role = authenticate()
    authorize(role, ["PlantOperator"])
    plant = resolve_plant(plantId)
    cyl = resolve_cylinder(cylinderId, plant)
    slot = resolve_slot(slotId, cyl)
    if slot["_start_dt"] <= store.clock:
        raise ApiError(ERR_SLOT_IN_PAST, 409, "Only a slot whose slot_start lies in the future may be cancelled")
    del store.slots[slot["id"]]
    return success({}, status=204)
