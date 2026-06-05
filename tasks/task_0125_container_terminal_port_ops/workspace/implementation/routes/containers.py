"""Container endpoints, grounding, customs-clear, and read-only sub-resources
(PRD §3.3, §3.6, §3.7, §3.8)."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import (
    APIError,
    ERR_CROSS_ENTITY_STATE,
    ERR_DUPLICATE,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_SLOT_OCCUPIED,
    ERR_STACKING_VIOLATION,
    ERR_STALE_VERSION,
)
from middleware import require
from response import ok_array, ok_object
from services import demurrage, metrics, serialize
from services.common import (
    get_body,
    optional_bool,
    paginate,
    parse_dt,
    require_enum,
    require_number,
    require_present,
    require_str,
    stamp_create,
    touch,
)
from services.lookups import (
    fk_slot,
    fk_vessel,
    fk_window,
    path_container,
)

bp = Blueprint("containers", __name__)


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------
@bp.post("/containers")
@require("YardPlanner", "TerminalAdmin")
def create_container():
    body = get_body()
    # FK existence (priority 4): vessel_id, berth_window_id
    vessel_id = require_present(body, "vessel_id")
    if not isinstance(vessel_id, str):
        raise APIError(ERR_INVALID_REQUEST, 422, "vessel_id must be a string")
    fk_vessel(vessel_id)
    window_id = require_present(body, "berth_window_id")
    if not isinstance(window_id, str):
        raise APIError(ERR_INVALID_REQUEST, 422, "berth_window_id must be a string")
    fk_window(window_id)
    # shape (priority 5)
    container_number = require_str(body, "container_number", non_empty=True)
    is_reefer = optional_bool(body, "is_reefer", default=False)
    setpoint_c = body.get("setpoint_c")
    if is_reefer:
        if setpoint_c is None:
            raise APIError(ERR_INVALID_REQUEST, 422, "setpoint_c is required when is_reefer is true")
        if isinstance(setpoint_c, bool) or not isinstance(setpoint_c, (int, float)):
            raise APIError(ERR_INVALID_REQUEST, 422, "setpoint_c must be a number")
        setpoint_c = float(setpoint_c)
    else:
        if setpoint_c is not None:
            raise APIError(ERR_INVALID_REQUEST, 422, "setpoint_c must be null/omitted when is_reefer is false")
    # uniqueness (priority 6)
    if any(c["container_number"] == container_number for c in db.containers.values()):
        raise APIError(ERR_DUPLICATE, 409, f"container_number already exists: {container_number}")

    rec = stamp_create({
        "container_number": container_number,
        "vessel_id": vessel_id,
        "berth_window_id": window_id,
        "is_reefer": is_reefer,
        "setpoint_c": setpoint_c,
        "yard_slot_id": None,
        "customs_status": "PENDING",
        "handling_status": "ON_VESSEL",
        "free_time_expires_at": None,
        "demurrage_due_cents": 0,
    })
    db.containers[rec["id"]] = rec
    return ok_object(serialize.container(rec), 201)


@bp.get("/containers/<cid>")
@require("TerminalAdmin", "YardPlanner", "GateOperator", "CustomsOfficer", "ReeferTechnician")
def get_container(cid):
    rec = path_container(cid)
    return ok_object(serialize.container(rec))


@bp.get("/containers")
@require("TerminalAdmin", "YardPlanner", "GateOperator", "CustomsOfficer")
def list_containers():
    window_id = request.args.get("berth_window_id")
    vessel_id = request.args.get("vessel_id")
    slot_id = request.args.get("yard_slot_id")
    rows = list(db.containers.values())
    if window_id is not None:
        rows = [c for c in rows if c["berth_window_id"] == window_id]
    if vessel_id is not None:
        rows = [c for c in rows if c["vessel_id"] == vessel_id]
    if slot_id is not None:
        rows = [c for c in rows if c["yard_slot_id"] == slot_id]
    items, limit, offset, total = paginate(rows, serialize.container)
    return ok_array(items, limit, offset, total)


# ---------------------------------------------------------------------------
# ground (ON_VESSEL -> GROUNDED)
# ---------------------------------------------------------------------------
@bp.post("/containers/<cid>/ground")
@require("YardPlanner")
def ground_container(cid):
    container = path_container(cid)
    body = get_body()
    # FK existence (priority 4): yard_slot_id
    slot_id = require_present(body, "yard_slot_id")
    if not isinstance(slot_id, str):
        raise APIError(ERR_INVALID_REQUEST, 422, "yard_slot_id must be a string")
    slot = fk_slot(slot_id)
    # shape (priority 5): condition
    condition = require_enum(body, "condition", {"SOUND", "DAMAGED"})
    damage_note = body.get("damage_note")
    if condition == "DAMAGED":
        if not isinstance(damage_note, str) or damage_note.strip() == "":
            raise APIError(ERR_INVALID_REQUEST, 422, "damage_note required when condition is DAMAGED")
    else:
        if damage_note is not None:
            raise APIError(ERR_INVALID_REQUEST, 422, "damage_note must be null/omitted when condition is SOUND")

    # state (priority 7)
    if container["handling_status"] != "ON_VESSEL":
        raise APIError(ERR_INVALID_STATE, 409, "container is not ON_VESSEL")
    # cross-entity: discharge window must be BERTHED (priority 8)
    window = db.berth_windows.get(container["berth_window_id"])
    if window is None or window["status"] != "BERTHED":
        raise APIError(ERR_CROSS_ENTITY_STATE, 409, "discharge berth window is not BERTHED")
    # slot occupancy: target must be EMPTY (PRD §3.3 prose: checked before stacking)
    if slot["status"] != "EMPTY":
        raise APIError(ERR_SLOT_OCCUPIED, 409, "target yard slot is OCCUPIED")
    # stacking safety (ERR_STACKING_VIOLATION)
    if container["is_reefer"] and not slot["is_reefer_rack"]:
        raise APIError(ERR_STACKING_VIOLATION, 409, "reefer container into non-reefer-rack slot")
    if slot["tier"] != 1:
        below = db.yard_slots.get(slot["below_slot_id"]) if slot["below_slot_id"] else None
        if below is None or below["status"] != "OCCUPIED":
            raise APIError(ERR_STACKING_VIOLATION, 409, "floating stack: supporting slot not OCCUPIED")

    # side effects
    container["yard_slot_id"] = slot_id
    container["handling_status"] = "GROUNDED"
    slot["occupied_by_container_id"] = cid
    slot["status"] = "OCCUPIED"
    touch(slot)
    touch(container)
    # GATE_IN EIR (append-only)
    eir = stamp_create({
        "container_id": cid,
        "gate_appointment_id": None,
        "direction": "GATE_IN",
        "condition": condition,
        "damage_note": damage_note,
        "recorded_at": db.clock_now(),
    }, versioned=False)
    db.eirs[eir["id"]] = eir
    return ok_object(serialize.container(container))


# ---------------------------------------------------------------------------
# customs-clear (PENDING -> CLEARED, OCC-guarded)
# ---------------------------------------------------------------------------
@bp.post("/containers/<cid>/customs-clear")
@require("CustomsOfficer")
def customs_clear(cid):
    container = path_container(cid)
    body = get_body()
    expected = require_present(body, "expected_container_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise APIError(ERR_INVALID_REQUEST, 422, "expected_container_version must be an integer")
    # state (priority 7): must be PENDING and not GATED_OUT
    if container["customs_status"] != "PENDING" or container["handling_status"] == "GATED_OUT":
        raise APIError(ERR_INVALID_STATE, 409, "container is not PENDING (or already gated out)")
    # OCC (priority 18)
    if expected != container["version"]:
        raise APIError(ERR_STALE_VERSION, 412, "container version is stale")
    container["customs_status"] = "CLEARED"
    touch(container)
    return ok_object(serialize.container(container))


# ---------------------------------------------------------------------------
# computed reads
# ---------------------------------------------------------------------------
@bp.get("/containers/<cid>/demurrage-quote")
@require("TerminalAdmin", "GateOperator", "YardPlanner")
def demurrage_quote(cid):
    container = path_container(cid)
    chargeable_days, due = demurrage.compute(container)
    container["demurrage_due_cents"] = due
    return ok_object({
        "container_id": cid,
        "chargeable_days": chargeable_days,
        "demurrage_due_cents": due,
    })


@bp.get("/containers/<cid>/dwell")
@require("TerminalAdmin", "YardPlanner", "GateOperator")
def dwell(cid):
    path_container(cid)
    hours = metrics.dwell_hours(cid)
    return ok_object({"container_id": cid, "dwell_hours": hours})


@bp.get("/containers/<cid>/reefer-summary")
@require("TerminalAdmin", "ReeferTechnician")
def reefer_summary(cid):
    container = path_container(cid)
    count, max_dev = metrics.reefer_summary(container)
    return ok_object({
        "container_id": cid,
        "excursion_count": count,
        "max_deviation_c": max_dev,
    })


# ---------------------------------------------------------------------------
# reverse-reachability list reads
# ---------------------------------------------------------------------------
@bp.get("/containers/<cid>/eirs")
@require("TerminalAdmin", "GateOperator", "YardPlanner")
def list_eirs(cid):
    path_container(cid)
    rows = [e for e in db.eirs.values() if e["container_id"] == cid]
    items, limit, offset, total = paginate(rows, serialize.eir)
    return ok_array(items, limit, offset, total)


@bp.get("/containers/<cid>/customs-holds")
@require("TerminalAdmin", "CustomsOfficer")
def list_customs_holds(cid):
    path_container(cid)
    rows = [h for h in db.customs_holds.values() if h["container_id"] == cid]
    items, limit, offset, total = paginate(rows, serialize.customs_hold)
    return ok_array(items, limit, offset, total)


@bp.get("/containers/<cid>/reefer-readings")
@require("TerminalAdmin", "ReeferTechnician")
def list_reefer_readings(cid):
    path_container(cid)
    rows = [r for r in db.reefer_readings.values() if r["container_id"] == cid]
    items, limit, offset, total = paginate(rows, serialize.reefer_reading)
    return ok_array(items, limit, offset, total)


@bp.get("/containers/<cid>/demurrage-invoices")
@require("TerminalAdmin", "GateOperator")
def list_demurrage_invoices(cid):
    path_container(cid)
    rows = [i for i in db.demurrage_invoices.values() if i["container_id"] == cid]
    items, limit, offset, total = paginate(rows, serialize.demurrage_invoice)
    return ok_array(items, limit, offset, total)


# ---------------------------------------------------------------------------
# reefer readings (append-only)
# ---------------------------------------------------------------------------
@bp.post("/containers/<cid>/reefer-readings")
@require("ReeferTechnician")
def record_reefer_reading(cid):
    container = path_container(cid)
    body = get_body()
    # shape (priority 5)
    recorded_at = require_present(body, "recorded_at")
    parse_dt(recorded_at)
    temperature_c = require_number(body, "temperature_c")
    setpoint = container.get("setpoint_c")
    is_excursion = False
    if setpoint is not None:
        is_excursion = metrics.excursion_flag(temperature_c, setpoint)

    rec = stamp_create({
        "container_id": cid,
        "recorded_at": recorded_at,
        "temperature_c": temperature_c,
        "is_excursion": is_excursion,
    }, versioned=False)
    db.reefer_readings[rec["id"]] = rec
    return ok_object(serialize.reefer_reading(rec), 201)
