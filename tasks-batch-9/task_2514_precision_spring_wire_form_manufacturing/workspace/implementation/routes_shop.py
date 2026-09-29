"""Wire lots, coilers, setup windows and stress-relief ovens."""

from datetime import timedelta

from flask import Blueprint

import auth
import calc
import cascades
import envelope
import find
import store
import validate
from auth import (DESIGN_ENGINEER, ENGINEERING_MANAGER, PLANT_ADMIN,
                  PROCESS_TECHNICIAN, PROGRAM_MANAGER, QUALITY_INSPECTOR)
from errors import ApiError

bp = Blueprint("shop", __name__)

WIRE_READERS = (QUALITY_INSPECTOR, PROCESS_TECHNICIAN, DESIGN_ENGINEER,
                ENGINEERING_MANAGER, PROGRAM_MANAGER, PLANT_ADMIN)
MACHINE_READERS = (PLANT_ADMIN, PROCESS_TECHNICIAN, DESIGN_ENGINEER,
                   ENGINEERING_MANAGER, QUALITY_INSPECTOR, PROGRAM_MANAGER)
SETUP_READERS = (PROCESS_TECHNICIAN, PLANT_ADMIN, DESIGN_ENGINEER,
                 ENGINEERING_MANAGER, QUALITY_INSPECTOR, PROGRAM_MANAGER)
OVEN_READERS = (PLANT_ADMIN, PROCESS_TECHNICIAN, QUALITY_INSPECTOR,
                ENGINEERING_MANAGER, DESIGN_ENGINEER, PROGRAM_MANAGER)

RELEASED_STATES = ("PROTOTYPE_RELEASED", "PRODUCTION_RELEASED")


# ---------------------------------------------------------------------------
# WireLot
# ---------------------------------------------------------------------------
@bp.post("/wire-lots")
def create_wire_lot():
    auth.guard(QUALITY_INSPECTOR)
    body = validate.body()
    material_spec_id = validate.req_id(body, "material_spec_id")
    heat_number = validate.req_string(body, "heat_number")
    received_kg = validate.req_number(body, "received_kg", gt=0)

    spec = find.material_spec(material_spec_id)
    find.unique_code(store.wire_lots, "heat_number", heat_number)

    received = calc.kg(received_kg)
    row = store.base_row()
    row.update({
        "material_spec_id": spec["id"],
        "heat_number": heat_number,
        "received_kg": received,
        "tensile_test_mpa": None,
        "certified_by_user_id": None,
        "certification_status": "UNCERTIFIED",
        "on_hand_kg": received,
        "reserved_kg": 0.0,
        "consumed_kg": 0.0,
    })
    store.wire_lots[row["id"]] = row
    return envelope.created(store.public(row))


@bp.get("/wire-lots/<lot_id>")
def read_wire_lot(lot_id):
    auth.guard(*WIRE_READERS)
    return envelope.ok(store.public(find.wire_lot(lot_id)))


@bp.get("/wire-lots")
def list_wire_lots():
    auth.guard(*WIRE_READERS)
    material_spec_id = validate.query_str("material_spec_id")
    status = validate.query_enum("certification_status", calc.CERTIFICATION_STATUSES)
    limit, offset = envelope.pagination()
    rows = store.by_seq(store.wire_lots.values())
    if material_spec_id is not None:
        rows = [r for r in rows if r["material_spec_id"] == material_spec_id]
    if status is not None:
        rows = [r for r in rows if r["certification_status"] == status]
    return envelope.listed(rows, limit, offset)


@bp.post("/wire-lots/<lot_id>/certify")
def certify_wire_lot(lot_id):
    actor = auth.guard(QUALITY_INSPECTOR)
    body = validate.body()
    tensile = validate.req_number(body, "tensile_test_mpa", gt=0)
    lot = find.wire_lot(lot_id)
    if lot["certification_status"] != "UNCERTIFIED":
        raise ApiError("ERR_WIRE_LOT_ALREADY_DECIDED",
                       "This heat has already been decided.")
    spec = store.material_specs[lot["material_spec_id"]]
    lot["tensile_test_mpa"] = tensile
    lot["certified_by_user_id"] = actor.user_id
    lot["certification_status"] = ("CERTIFIED"
                                  if tensile >= spec["tensile_grade_mpa"]
                                  else "REJECTED")
    store.touch(lot)
    return envelope.ok(store.public(lot))


# ---------------------------------------------------------------------------
# CoilingMachine
# ---------------------------------------------------------------------------
@bp.post("/coiling-machines")
def create_machine():
    auth.guard(PLANT_ADMIN)
    body = validate.body()
    machine_code = validate.req_string(body, "machine_code")
    max_diameter = validate.req_number(body, "max_wire_diameter_mm", gt=0)
    buffer_minutes = validate.req_int(body, "changeover_buffer_minutes", minimum=0)

    find.unique_code(store.machines, "machine_code", machine_code)

    row = store.base_row()
    row.update({
        "machine_code": machine_code,
        "max_wire_diameter_mm": max_diameter,
        "changeover_buffer_minutes": buffer_minutes,
        "machine_state": "IDLE",
        "active_setup_id": None,
    })
    store.machines[row["id"]] = row
    return envelope.created(store.public(row))


@bp.get("/coiling-machines/<machine_id>")
def read_machine(machine_id):
    auth.guard(*MACHINE_READERS)
    return envelope.ok(store.public(find.machine(machine_id)))


@bp.get("/coiling-machines")
def list_machines():
    auth.guard(*MACHINE_READERS)
    state = validate.query_enum("machine_state", calc.MACHINE_STATES)
    limit, offset = envelope.pagination()
    rows = store.by_seq(store.machines.values())
    if state is not None:
        rows = [r for r in rows if r["machine_state"] == state]
    return envelope.listed(rows, limit, offset)


# ---------------------------------------------------------------------------
# MachineSetup
# ---------------------------------------------------------------------------
@bp.post("/machine-setups")
def create_setup():
    actor = auth.guard(PROCESS_TECHNICIAN)
    body = validate.body()
    machine_id = validate.req_id(body, "machine_id")
    design_id = validate.req_id(body, "design_id")
    tooling_asset_id = validate.req_id(body, "tooling_asset_id")
    window_start, raw_start = validate.req_datetime(body, "window_start")
    window_end, raw_end = validate.req_datetime(body, "window_end")
    expected_version = validate.req_int(body, "expected_machine_version")

    design = find.design(design_id)
    tooling = find.tooling(tooling_asset_id)
    machine = find.machine(machine_id)

    if expected_version != machine["version"]:
        raise ApiError("ERR_STALE_MACHINE_VERSION",
                       "expected_machine_version does not match the coiler.")
    if design["release_status"] not in RELEASED_STATES:
        raise ApiError("ERR_PPAP_NOT_APPROVED",
                       "The design has not reached a released state.")
    if tooling["design_id"] != design["id"]:
        raise ApiError("ERR_TOOLING_DESIGN_MISMATCH",
                       "The tooling asset belongs to a different design.")
    if design["wire_diameter_mm"] > machine["max_wire_diameter_mm"]:
        raise ApiError("ERR_WIRE_DIAMETER_EXCEEDS_MACHINE",
                       "The design's wire diameter exceeds the coiler's ceiling.")
    if not window_end > window_start:
        raise ApiError("ERR_WINDOW_INVALID",
                       "window_end must be strictly after window_start.")
    if window_start < store.clock_now():
        raise ApiError("ERR_WINDOW_IN_PAST",
                       "window_start is earlier than the logical clock.")

    buffer_ = timedelta(minutes=machine["changeover_buffer_minutes"])
    for existing in store.setups.values():
        if existing["machine_id"] != machine["id"]:
            continue
        if existing["setup_status"] not in ("SCHEDULED", "ACTIVE"):
            continue
        if window_start < existing["_window_end"] + buffer_ and \
                existing["_window_start"] < window_end + buffer_:
            raise ApiError("ERR_SETUP_WINDOW_CONFLICT",
                           "The window conflicts with an existing setup on "
                           "this coiler.")

    row = store.base_row()
    row.update({
        "machine_id": machine["id"],
        "design_id": design["id"],
        "tooling_asset_id": tooling["id"],
        "window_start": raw_start,
        "window_end": raw_end,
        "set_by_user_id": actor.user_id,
        "setup_status": "SCHEDULED",
        "superseded_by_setup_id": None,
        "_window_start": window_start,
        "_window_end": window_end,
    })
    store.setups[row["id"]] = row

    for other in cascades.rows(store.setups, machine_id=machine["id"],
                               design_id=design["id"]):
        if other["id"] == row["id"] or other["setup_status"] != "SCHEDULED":
            continue
        other["setup_status"] = "SUPERSEDED"
        other["superseded_by_setup_id"] = row["id"]
        store.touch(other)

    store.touch(machine)
    return envelope.created(store.public(row))


@bp.get("/machine-setups/<setup_id>")
def read_setup(setup_id):
    auth.guard(*SETUP_READERS)
    return envelope.ok(store.public(find.setup(setup_id)))


@bp.get("/machine-setups")
def list_setups():
    auth.guard(*SETUP_READERS)
    machine_id = validate.query_str("machine_id")
    design_id = validate.query_str("design_id")
    tooling_asset_id = validate.query_str("tooling_asset_id")
    status = validate.query_enum("setup_status", calc.SETUP_STATUSES)
    limit, offset = envelope.pagination()
    rows = store.by_seq(store.setups.values())
    if machine_id is not None:
        rows = [r for r in rows if r["machine_id"] == machine_id]
    if design_id is not None:
        rows = [r for r in rows if r["design_id"] == design_id]
    if tooling_asset_id is not None:
        rows = [r for r in rows if r["tooling_asset_id"] == tooling_asset_id]
    if status is not None:
        rows = [r for r in rows if r["setup_status"] == status]
    return envelope.listed(rows, limit, offset)


@bp.post("/machine-setups/<setup_id>/activate")
def activate_setup(setup_id):
    auth.guard(PROCESS_TECHNICIAN)
    validate.body()
    setup = find.setup(setup_id)
    if setup["setup_status"] != "SCHEDULED":
        raise ApiError("ERR_SETUP_INVALID_STATE",
                       "Only a SCHEDULED setup may be activated.")
    machine = store.machines[setup["machine_id"]]
    if machine["machine_state"] != "IDLE":
        raise ApiError("ERR_MACHINE_NOT_IDLE", "The coiler is not IDLE.")
    now = store.clock_now()
    if now < setup["_window_start"] or now >= setup["_window_end"]:
        raise ApiError("ERR_OUTSIDE_SETUP_WINDOW",
                       "The logical clock is outside the booked window.")
    setup["setup_status"] = "ACTIVE"
    store.touch(setup)
    machine["machine_state"] = "SETUP"
    machine["active_setup_id"] = setup["id"]
    store.touch(machine)
    return envelope.ok(store.public(setup))


@bp.post("/machine-setups/<setup_id>/abort")
def abort_setup(setup_id):
    auth.guard(PROCESS_TECHNICIAN)
    validate.body()
    setup = find.setup(setup_id)
    if setup["setup_status"] not in ("SCHEDULED", "ACTIVE"):
        raise ApiError("ERR_SETUP_INVALID_STATE",
                       "Only a SCHEDULED or ACTIVE setup may be aborted.")
    cascades.abort_setup(setup)
    for run in cascades.rows(store.runs, setup_id=setup["id"]):
        if run["process_status"] in ("FAI_PENDING", "RUNNING"):
            cascades.cancel_run(run)
    return envelope.ok(store.public(setup))


# ---------------------------------------------------------------------------
# StressReliefOven
# ---------------------------------------------------------------------------
@bp.post("/stress-relief-ovens")
def create_oven():
    auth.guard(PLANT_ADMIN)
    body = validate.body()
    oven_code = validate.req_string(body, "oven_code")
    capacity = validate.req_number(body, "capacity_kg", gt=0)
    max_temp = validate.req_number(body, "max_temp_c", gt=0)

    find.unique_code(store.ovens, "oven_code", oven_code)

    row = store.base_row()
    row.update({
        "oven_code": oven_code,
        "capacity_kg": capacity,
        "max_temp_c": max_temp,
        "scheduled_load_kg": 0.0,
    })
    store.ovens[row["id"]] = row
    return envelope.created(store.public(row))


@bp.get("/stress-relief-ovens/<oven_id>")
def read_oven(oven_id):
    auth.guard(*OVEN_READERS)
    return envelope.ok(store.public(find.oven(oven_id)))
