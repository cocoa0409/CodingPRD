"""Production runs, inspection records and heat-treat batches."""

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

bp = Blueprint("runs", __name__)

RUN_READERS = (PROCESS_TECHNICIAN, QUALITY_INSPECTOR, ENGINEERING_MANAGER,
               DESIGN_ENGINEER, PROGRAM_MANAGER, PLANT_ADMIN)
RECORD_READERS = (QUALITY_INSPECTOR, PROCESS_TECHNICIAN, ENGINEERING_MANAGER,
                  DESIGN_ENGINEER, PROGRAM_MANAGER, PLANT_ADMIN)
BATCH_READERS = (PROCESS_TECHNICIAN, QUALITY_INSPECTOR, ENGINEERING_MANAGER,
                 DESIGN_ENGINEER, PROGRAM_MANAGER, PLANT_ADMIN)

RELEASED_STATES = ("PROTOTYPE_RELEASED", "PRODUCTION_RELEASED")


def _refresh_heat_treat(run):
    run["heat_treat_state"] = cascades.derive_heat_treat_state(run["id"])


# ---------------------------------------------------------------------------
# ProductionRun
# ---------------------------------------------------------------------------
@bp.post("/production-runs")
def create_run():
    auth.guard(PROCESS_TECHNICIAN)
    body = validate.body()
    setup_id = validate.req_id(body, "setup_id")
    wire_lot_id = validate.req_id(body, "wire_lot_id")
    design_id = validate.req_id(body, "design_id")
    planned_pieces = validate.req_int(body, "planned_pieces", gt=0)

    design = find.design(design_id)
    lot = find.wire_lot(wire_lot_id)
    setup = find.setup(setup_id)

    if setup["setup_status"] != "ACTIVE":
        raise ApiError("ERR_SETUP_NOT_ACTIVE", "The named setup is not ACTIVE.")
    if lot["certification_status"] != "CERTIFIED":
        raise ApiError("ERR_WIRE_LOT_NOT_CERTIFIED",
                       "The named heat is not CERTIFIED.")
    if design["release_status"] not in RELEASED_STATES:
        raise ApiError("ERR_PPAP_NOT_APPROVED",
                       "The design has not reached a released state.")
    if setup["design_id"] != design["id"]:
        raise ApiError("ERR_SETUP_DESIGN_MISMATCH",
                       "The setup was tooled for a different design.")
    if lot["material_spec_id"] != design["material_spec_id"]:
        raise ApiError("ERR_MATERIAL_MISMATCH",
                       "The heat's grade differs from the design's material spec.")

    required = calc.wire_mass_required(design["wire_mass_per_piece_kg"],
                                       planned_pieces)
    if required > lot["on_hand_kg"]:
        raise ApiError("ERR_INSUFFICIENT_WIRE",
                       "The heat holds %.3f kg on hand but %.3f kg are required."
                       % (lot["on_hand_kg"], required))

    row = store.base_row()
    row.update({
        "setup_id": setup["id"],
        "wire_lot_id": lot["id"],
        "design_id": design["id"],
        "planned_pieces": planned_pieces,
        "produced_pieces": 0,
        "scrapped_pieces": 0,
        "wire_reserved_kg": required,
        "wire_consumed_kg": 0.0,
        "process_status": "FAI_PENDING",
        "quality_status": "OPEN",
        "fai_disposition": "PENDING",
        "min_cpk_observed": None,
        "min_ppk_observed": None,
        "heat_treat_state": "NOT_STARTED",
        "peening_verified": False,
    })
    store.runs[row["id"]] = row

    cascades.reserve_wire(lot, required)

    machine = store.machines.get(setup["machine_id"])
    if machine is not None:
        machine["machine_state"] = "PRODUCTION"
        store.touch(machine)
    return envelope.created(store.public(row))


@bp.get("/production-runs/<run_id>")
def read_run(run_id):
    auth.guard(*RUN_READERS)
    return envelope.ok(store.public(find.run(run_id)))


@bp.get("/production-runs")
def list_runs():
    auth.guard(*RUN_READERS)
    setup_id = validate.query_str("setup_id")
    wire_lot_id = validate.query_str("wire_lot_id")
    design_id = validate.query_str("design_id")
    process_status = validate.query_enum("process_status", calc.PROCESS_STATUSES)
    quality_status = validate.query_enum("quality_status", calc.QUALITY_STATUSES)
    limit, offset = envelope.pagination()
    rows = store.by_seq(store.runs.values())
    if setup_id is not None:
        rows = [r for r in rows if r["setup_id"] == setup_id]
    if wire_lot_id is not None:
        rows = [r for r in rows if r["wire_lot_id"] == wire_lot_id]
    if design_id is not None:
        rows = [r for r in rows if r["design_id"] == design_id]
    if process_status is not None:
        rows = [r for r in rows if r["process_status"] == process_status]
    if quality_status is not None:
        rows = [r for r in rows if r["quality_status"] == quality_status]
    return envelope.listed(rows, limit, offset)


def _subgroup(run, body, kind):
    """Shared body handling for the two measurement endpoints."""
    characteristic_id = validate.req_id(body, "characteristic_id")
    measurements = validate.req_measurements(body, "measurements")
    characteristic = find.characteristic(characteristic_id)
    return characteristic, measurements


def _record_row(run, characteristic, measurements, kind, actor):
    pooled = None
    if kind == "SPC":
        pooled = []
        for other in cascades.records_of_run(run["id"]):
            if other["record_kind"] == "SPC" and \
                    other["characteristic_id"] == characteristic["id"]:
                pooled.extend(other["measurements"])
        pooled = pooled + list(measurements)
    stats = calc.capability(measurements, characteristic, pooled)
    row = store.base_row(with_common=False)
    row.update({
        "run_id": run["id"],
        "characteristic_id": characteristic["id"],
        "record_kind": kind,
        "measurements": list(measurements),
        "inspected_by_user_id": actor.user_id,
    })
    row.update(stats)
    store.inspection_records[row["id"]] = row
    return row


@bp.post("/production-runs/<run_id>/fai")
def record_fai(run_id):
    actor = auth.guard(QUALITY_INSPECTOR)
    body = validate.body()
    run = find.run(run_id)
    characteristic, measurements = _subgroup(run, body, "FAI")

    if run["process_status"] != "FAI_PENDING":
        raise ApiError("ERR_RUN_INVALID_STATE",
                       "First-article subgroups require a FAI_PENDING run.")
    if characteristic["design_id"] != run["design_id"]:
        raise ApiError("ERR_CHARACTERISTIC_DESIGN_MISMATCH",
                       "The characteristic belongs to a different design.")
    if len(measurements) < calc.SPC_MIN_SUBGROUP_SIZE:
        raise ApiError("ERR_INVALID_SUBGROUP_SIZE",
                       "A subgroup needs at least %d measurements."
                       % calc.SPC_MIN_SUBGROUP_SIZE)

    row = _record_row(run, characteristic, measurements, "FAI", actor)
    cascades.refresh_run_capability(run)
    store.touch(run)
    return envelope.created(store.public(row))


@bp.post("/production-runs/<run_id>/fai-disposition")
def dispose_fai(run_id):
    actor = auth.guard(QUALITY_INSPECTOR)
    body = validate.body()
    decision = validate.req_enum(body, "decision", ("ACCEPT", "REJECT"))
    run = find.run(run_id)

    if run["process_status"] != "FAI_PENDING":
        raise ApiError("ERR_RUN_INVALID_STATE",
                       "The first article closes out only from FAI_PENDING.")
    if run["fai_disposition"] != "PENDING":
        raise ApiError("ERR_FAI_ALREADY_DISPOSITIONED",
                       "The first article has already been dispositioned.")
    fai_records = [r for r in cascades.records_of_run(run["id"])
                   if r["record_kind"] == "FAI"]
    if any(r["inspected_by_user_id"] == actor.user_id for r in fai_records):
        raise ApiError("ERR_SELF_DISPOSITION_FORBIDDEN",
                       "Whoever measured the first article may not judge it.")
    characteristics = cascades.characteristics_of(run["design_id"])
    if not characteristics:
        raise ApiError("ERR_CHARACTERISTIC_SET_EMPTY",
                       "The design has no critical characteristics on file.")
    covered = set(r["characteristic_id"] for r in fai_records)
    if any(c["id"] not in covered for c in characteristics):
        raise ApiError("ERR_INCOMPLETE_FAI_COVERAGE",
                       "Every critical characteristic needs a first-article "
                       "subgroup on this run.")

    if decision == "ACCEPT":
        run["fai_disposition"] = "ACCEPTED"
        run["process_status"] = "RUNNING"
        store.touch(run)
    else:
        run["fai_disposition"] = "REJECTED"
        cascades.cancel_run(run)
    return envelope.ok(store.public(run))


@bp.post("/production-runs/<run_id>/inspections")
def record_inspection(run_id):
    actor = auth.guard(QUALITY_INSPECTOR)
    body = validate.body()
    run = find.run(run_id)
    characteristic, measurements = _subgroup(run, body, "SPC")

    if run["process_status"] not in ("RUNNING", "COMPLETE"):
        raise ApiError("ERR_RUN_INVALID_STATE",
                       "In-process subgroups require a RUNNING or COMPLETE run.")
    if characteristic["design_id"] != run["design_id"]:
        raise ApiError("ERR_CHARACTERISTIC_DESIGN_MISMATCH",
                       "The characteristic belongs to a different design.")
    if len(measurements) < calc.SPC_MIN_SUBGROUP_SIZE:
        raise ApiError("ERR_INVALID_SUBGROUP_SIZE",
                       "A subgroup needs at least %d measurements."
                       % calc.SPC_MIN_SUBGROUP_SIZE)

    row = _record_row(run, characteristic, measurements, "SPC", actor)
    cascades.refresh_run_capability(run)
    escalate = (row["control_state"] == "OUT_OF_CONTROL"
                and characteristic["is_safety_critical"]
                and run["quality_status"] == "OPEN")
    if escalate:
        run["quality_status"] = "SPC_HOLD"
    store.touch(run)
    if escalate:
        cascades.quarantine_lots_of_run(run)
        cascades.refresh_posture(cascades.program_of_run(run))
    return envelope.created(store.public(row))


def _newest_out_of_control(run):
    """True when some safety-critical characteristic of the run's design has an
    OUT_OF_CONTROL newest record (by created_at) on this run."""
    for characteristic in cascades.characteristics_of(run["design_id"]):
        if not characteristic["is_safety_critical"]:
            continue
        newest = store.newest([r for r in store.inspection_records.values()
                               if r["run_id"] == run["id"]
                               and r["characteristic_id"] == characteristic["id"]])
        if newest is not None and newest["control_state"] == "OUT_OF_CONTROL":
            return True
    return False


@bp.post("/production-runs/<run_id>/quality-disposition")
def dispose_quality(run_id):
    auth.guard(QUALITY_INSPECTOR)
    body = validate.body()
    decision = validate.req_enum(body, "decision",
                                 ("RELEASE", "ACCEPT_AS_IS", "SCRAP"))
    run = find.run(run_id)
    if run["quality_status"] != "SPC_HOLD":
        raise ApiError("ERR_RUN_NOT_ON_HOLD", "The run is not on an SPC hold.")

    if decision in ("RELEASE", "ACCEPT_AS_IS"):
        if _newest_out_of_control(run):
            raise ApiError("ERR_RUN_INVALID_STATE",
                           "A safety-critical characteristic is still "
                           "OUT_OF_CONTROL on its newest record.")
        run["quality_status"] = "OPEN" if decision == "RELEASE" \
            else "DISPOSITIONED_ACCEPT"
        store.touch(run)
        cascades.refresh_posture_for_lots_of_run(run)
        return envelope.ok(store.public(run))

    run["quality_status"] = "SCRAPPED"
    if run["process_status"] in ("FAI_PENDING", "RUNNING"):
        cascades.cancel_run(run)
    else:
        store.touch(run)
        cascades.quarantine_lots_of_run(run)
        cascades.refresh_posture(cascades.program_of_run(run))
    return envelope.ok(store.public(run))


@bp.post("/production-runs/<run_id>/complete")
def complete_run(run_id):
    auth.guard(PROCESS_TECHNICIAN)
    body = validate.body()
    produced = validate.req_int(body, "produced_pieces", minimum=0)
    scrapped = validate.req_int(body, "scrapped_pieces", minimum=0)
    run = find.run(run_id)

    if produced + scrapped > run["planned_pieces"]:
        validate.bad("produced_pieces plus scrapped_pieces exceeds "
                     "planned_pieces.")
    if run["quality_status"] == "SPC_HOLD":
        raise ApiError("ERR_RUN_ON_SPC_HOLD",
                       "A run on an SPC hold cannot be closed out.")
    if run["process_status"] != "RUNNING":
        raise ApiError("ERR_RUN_INVALID_STATE",
                       "Only a RUNNING run may be completed.")

    design = store.designs.get(run["design_id"])
    consumed = calc.wire_consumed(design["wire_mass_per_piece_kg"],
                                  produced + scrapped)
    run["produced_pieces"] = produced
    run["scrapped_pieces"] = scrapped
    run["wire_consumed_kg"] = consumed
    run["process_status"] = "COMPLETE"
    store.touch(run)

    cascades.settle_consumption(run, consumed)

    setup = store.setups.get(run["setup_id"])
    if setup is not None and setup["setup_status"] == "ACTIVE":
        cascades.release_setup(setup)
    return envelope.ok(store.public(run))


@bp.post("/production-runs/<run_id>/cancel")
def cancel_run_endpoint(run_id):
    auth.guard(PROCESS_TECHNICIAN)
    validate.body()
    run = find.run(run_id)
    if run["process_status"] not in ("FAI_PENDING", "RUNNING"):
        raise ApiError("ERR_RUN_INVALID_STATE",
                       "Only a FAI_PENDING or RUNNING run may be abandoned.")
    cascades.cancel_run(run)
    return envelope.ok(store.public(run))


# ---------------------------------------------------------------------------
# InspectionRecord reads
# ---------------------------------------------------------------------------
@bp.get("/inspection-records/<record_id>")
def read_record(record_id):
    auth.guard(*RECORD_READERS)
    return envelope.ok(store.public(find.inspection_record(record_id)))


@bp.get("/inspection-records")
def list_records():
    auth.guard(*RECORD_READERS)
    run_id = validate.query_str("run_id")
    characteristic_id = validate.query_str("characteristic_id")
    record_kind = validate.query_enum("record_kind", calc.RECORD_KINDS)
    control_state = validate.query_enum("control_state", calc.CONTROL_STATES)
    limit, offset = envelope.pagination()
    rows = store.by_seq(store.inspection_records.values())
    if run_id is not None:
        rows = [r for r in rows if r["run_id"] == run_id]
    if characteristic_id is not None:
        rows = [r for r in rows if r["characteristic_id"] == characteristic_id]
    if record_kind is not None:
        rows = [r for r in rows if r["record_kind"] == record_kind]
    if control_state is not None:
        rows = [r for r in rows if r["control_state"] == control_state]
    return envelope.listed(rows, limit, offset)


# ---------------------------------------------------------------------------
# HeatTreatBatch
# ---------------------------------------------------------------------------
@bp.post("/heat-treat-batches")
def create_batch():
    auth.guard(PROCESS_TECHNICIAN)
    body = validate.body()
    oven_id = validate.req_id(body, "oven_id")
    run_id = validate.req_id(body, "run_id")
    window_start, raw_start = validate.req_datetime(body, "window_start")
    window_end, raw_end = validate.req_datetime(body, "window_end")
    load_kg = validate.req_number(body, "load_kg", gt=0)
    target_temp = validate.req_number(body, "target_temp_c", gt=0)
    peening_requested = validate.opt_bool(body, "peening_requested", False)

    run = find.run(run_id)
    oven = find.oven(oven_id)

    if run["quality_status"] == "SPC_HOLD":
        raise ApiError("ERR_RUN_ON_SPC_HOLD",
                       "A run on an SPC hold may not be charged.")
    if run["process_status"] not in ("RUNNING", "COMPLETE"):
        raise ApiError("ERR_RUN_INVALID_STATE",
                       "Only a RUNNING or COMPLETE run may be stress relieved.")
    if target_temp > oven["max_temp_c"]:
        raise ApiError("ERR_TEMP_EXCEEDS_OVEN",
                       "The requested soak exceeds the oven's ceiling.")
    if not window_end > window_start:
        raise ApiError("ERR_WINDOW_INVALID",
                       "window_end must be strictly after window_start.")
    if window_start < store.clock_now():
        raise ApiError("ERR_WINDOW_IN_PAST",
                       "window_start is earlier than the logical clock.")

    load = calc.kg(load_kg)
    occupied = []
    for existing in store.batches.values():
        if existing["oven_id"] != oven["id"]:
            continue
        if existing["batch_status"] not in ("SCHEDULED", "RUNNING"):
            continue
        if window_start <= existing["_window_end"] and \
                existing["_window_start"] <= window_end:
            occupied.append(existing["load_kg"])
    total = calc.kg_sum(*(occupied + [load]))
    if total > oven["capacity_kg"]:
        raise ApiError("ERR_OVEN_CAPACITY_EXCEEDED",
                       "The oven would hold %.3f kg against a capacity of %.3f kg."
                       % (total, oven["capacity_kg"]))

    row = store.base_row()
    row.update({
        "oven_id": oven["id"],
        "run_id": run["id"],
        "window_start": raw_start,
        "window_end": raw_end,
        "load_kg": load,
        "target_temp_c": target_temp,
        "peening_requested": peening_requested,
        "peening_performed": None,
        "batch_status": "SCHEDULED",
        "_window_start": window_start,
        "_window_end": window_end,
    })
    store.batches[row["id"]] = row
    cascades.refresh_oven_load(oven)
    return envelope.created(store.public(row))


@bp.get("/heat-treat-batches/<batch_id>")
def read_batch(batch_id):
    auth.guard(*BATCH_READERS)
    return envelope.ok(store.public(find.batch(batch_id)))


@bp.get("/heat-treat-batches")
def list_batches():
    auth.guard(*BATCH_READERS)
    oven_id = validate.query_str("oven_id")
    run_id = validate.query_str("run_id")
    batch_status = validate.query_enum("batch_status", calc.BATCH_STATUSES)
    limit, offset = envelope.pagination()
    rows = store.by_seq(store.batches.values())
    if oven_id is not None:
        rows = [r for r in rows if r["oven_id"] == oven_id]
    if run_id is not None:
        rows = [r for r in rows if r["run_id"] == run_id]
    if batch_status is not None:
        rows = [r for r in rows if r["batch_status"] == batch_status]
    return envelope.listed(rows, limit, offset)


@bp.post("/heat-treat-batches/<batch_id>/start")
def start_batch(batch_id):
    auth.guard(PROCESS_TECHNICIAN)
    validate.body()
    batch = find.batch(batch_id)
    if batch["batch_status"] != "SCHEDULED":
        raise ApiError("ERR_BATCH_INVALID_STATE",
                       "Only a SCHEDULED batch may be charged.")
    if store.clock_now() < batch["_window_start"]:
        raise ApiError("ERR_BATCH_WINDOW_NOT_REACHED",
                       "The batch window has not been reached.")
    batch["batch_status"] = "RUNNING"
    store.touch(batch)
    run = store.runs.get(batch["run_id"])
    if run is not None:
        _refresh_heat_treat(run)
        store.touch(run)
    return envelope.ok(store.public(batch))


@bp.post("/heat-treat-batches/<batch_id>/complete")
def complete_batch(batch_id):
    auth.guard(PROCESS_TECHNICIAN)
    body = validate.body()
    peening_performed = validate.req_bool(body, "peening_performed")
    batch = find.batch(batch_id)
    if batch["batch_status"] != "RUNNING":
        raise ApiError("ERR_BATCH_INVALID_STATE",
                       "Only a RUNNING batch may be discharged.")
    batch["batch_status"] = "COMPLETE"
    batch["peening_performed"] = peening_performed
    store.touch(batch)

    oven = store.ovens.get(batch["oven_id"])
    if oven is not None:
        cascades.refresh_oven_load(oven)

    run = store.runs.get(batch["run_id"])
    if run is None:
        return envelope.ok(store.public(batch))

    design = store.designs.get(run["design_id"])
    _refresh_heat_treat(run)
    if peening_performed:
        run["peening_verified"] = True
    escalate = (design is not None and design.get("shot_peening_required")
                and not peening_performed
                and run["quality_status"] == "OPEN")
    if escalate:
        run["quality_status"] = "SPC_HOLD"
    store.touch(run)
    if escalate:
        cascades.quarantine_lots_of_run(run)
        cascades.refresh_posture(cascades.program_of_run(run))
    return envelope.ok(store.public(batch))


@bp.post("/heat-treat-batches/<batch_id>/cancel")
def cancel_batch(batch_id):
    auth.guard(PROCESS_TECHNICIAN)
    validate.body()
    batch = find.batch(batch_id)
    if batch["batch_status"] != "SCHEDULED":
        raise ApiError("ERR_BATCH_INVALID_STATE",
                       "Only a SCHEDULED batch may be cancelled.")
    batch["batch_status"] = "CANCELLED"
    store.touch(batch)
    oven = store.ovens.get(batch["oven_id"])
    if oven is not None:
        cascades.refresh_oven_load(oven)
    run = store.runs.get(batch["run_id"])
    if run is not None:
        state = cascades.derive_heat_treat_state(run["id"])
        if run["heat_treat_state"] != state:
            run["heat_treat_state"] = state
            store.touch(run)
    return envelope.ok(store.public(batch))
