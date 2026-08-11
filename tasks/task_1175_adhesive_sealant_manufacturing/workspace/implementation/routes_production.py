"""ProductionBatch, PackagingRun, MoistureExposureEvent endpoints."""
import uuid
from datetime import timedelta

from flask import Blueprint, request

from db import store
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_FORMULATION_NOT_EFFECTIVE,
    ERR_VESSEL_TIME_OVERLAP, ERR_VESSEL_CAPACITY_EXCEEDED,
    ERR_DRY_ROOM_CAPACITY_EXCEEDED, ERR_MOISTURE_PROTOCOL_VIOLATION,
    ERR_PACK_FORMAT_MISMATCH, ERR_BATCH_INVALID_STATE, ERR_POT_LIFE_EXCEEDED,
    ERR_RUN_INVALID_STATE, ERR_INSUFFICIENT_BATCH_VOLUME, not_found,
)
from helpers import (
    ALL_ROLES, require_roles, body_json, ok, ok_list, pagination_params,
    f_str, f_int, f_enum, f_dt, now_iso,
)
from services import (
    new_entity, touch, get_batch, get_run, get_event, get_dry_room,
    ser_batch, ser_run, ser_event, sorted_rows, add_months,
    fire_batch_expiry, fire_batch_void, pack_fill, runs_of_batch,
    lot_of_batch, BATCH_INFLIGHT,
)

bp = Blueprint("production", __name__)

PACK_FORMATS = ["CARTRIDGE", "PAIL", "DRUM"]
HOLD_OUTCOMES = ["RELEASE", "CONDEMN"]


# ---------------------------------------------------------------------------
# ProductionBatch
# ---------------------------------------------------------------------------

@bp.post("/api/batches")
@require_roles("BatchOperator")
def create_batch():
    # schema (priority 3) before existence (priority 4)
    b = body_json()
    formulation_id = f_str(b, "formulation_id")
    vessel_id = f_str(b, "vessel_id")
    mix_start = f_dt(b, "mix_start_at")
    mix_end = f_dt(b, "mix_end_at")
    if not (mix_end > mix_start):
        raise ApiError(ERR_INVALID_REQUEST, "mix_end_at must be strictly after mix_start_at", 400)
    volume = f_int(b, "batch_volume_ml", lo=1)
    # existence
    formulation = store.formulations.get(formulation_id)
    if formulation is None:
        raise not_found("Formulation")
    vessel = store.vessels.get(vessel_id)
    if vessel is None:
        raise not_found("MixingVessel")
    # state gate: formulation must be EFFECTIVE
    if formulation["status"] != "EFFECTIVE":
        raise ApiError(ERR_FORMULATION_NOT_EFFECTIVE, "Formulation is not EFFECTIVE", 409)
    # constraint: half-open vessel window overlap
    for other in store.batches.values():
        if other["vessel_id"] != vessel_id or other["status"] not in BATCH_INFLIGHT:
            continue
        if mix_start < other["mix_end_at"] and other["mix_start_at"] < mix_end:
            raise ApiError(
                ERR_VESSEL_TIME_OVERLAP,
                "Mix window overlaps another non-terminal batch on the vessel",
                409,
            )
    # constraint: vessel capacity (ml)
    if volume > vessel["capacity_liters"] * 1000:
        raise ApiError(
            ERR_VESSEL_CAPACITY_EXCEEDED,
            "batch_volume_ml exceeds vessel capacity",
            422,
        )
    batch = new_entity()
    batch.update({
        "formulation_id": formulation_id,
        "vessel_id": vessel_id,
        "mix_start_at": mix_start,
        "mix_end_at": mix_end,
        "batch_volume_ml": volume,
        "mixed_at": None,
        "pot_life_deadline": None,
        "remaining_bulk_volume_ml": volume,
        "written_off_volume_ml": 0,
        "production_lot_id": None,
        "status": "MIXING",
    })
    # atomic 1:1 lot creation
    store.lot_seq += 1
    lot = new_entity()
    lot.update({
        "batch_id": batch["id"],
        "formulation_id": formulation_id,
        "lot_number": f"LOT-{store.lot_seq:06d}",
        "manufacture_date": None,
        "expiry_date": None,
        "pack_format": None,
        "unit_volume_ml": None,
        "units_filled": 0,
        "units_quarantined": 0,
        "units_condemned": 0,
        "units_shipped": 0,
        "retest_count": 0,
        "released_by": None,
        "qa_status": "AWAITING_TEST",
        "hold_status": "CLEAR",
    })
    store.lots[lot["id"]] = lot
    batch["production_lot_id"] = lot["id"]
    store.batches[batch["id"]] = batch
    return ok(ser_batch(batch), 201)


@bp.get("/api/batches")
@require_roles(*ALL_ROLES)
def list_batches():
    limit, offset = pagination_params()
    rows = list(store.batches.values())
    fid = request.args.get("formulation_id")
    vid = request.args.get("vessel_id")
    if fid is not None:
        rows = [b for b in rows if b["formulation_id"] == fid]
    if vid is not None:
        rows = [b for b in rows if b["vessel_id"] == vid]
    return ok_list([ser_batch(b) for b in sorted_rows(rows)], limit, offset)


@bp.get("/api/batches/<bid>")
@require_roles(*ALL_ROLES)
def get_one_batch(bid):
    return ok(ser_batch(get_batch(bid)), 200)


@bp.post("/api/batches/<bid>/complete-mix")
@require_roles("BatchOperator")
def complete_mix(bid):
    batch = get_batch(bid)
    if batch["status"] != "MIXING":
        raise ApiError(ERR_BATCH_INVALID_STATE, "complete-mix requires MIXING", 409)
    formulation = store.formulations[batch["formulation_id"]]
    now = store.clock
    batch["mixed_at"] = now
    batch["pot_life_deadline"] = now + timedelta(minutes=formulation["pot_life_minutes"])
    batch["status"] = "MIXED"
    touch(batch)
    lot = lot_of_batch(batch)
    if lot is not None:
        manufacture = now.date()
        lot["manufacture_date"] = manufacture
        lot["expiry_date"] = add_months(manufacture, formulation["shelf_life_months"])
        touch(lot)
    return ok(ser_batch(batch), 200)


@bp.post("/api/batches/<bid>/void")
@require_roles("BatchOperator")
def void_batch(bid):
    body_json()  # optional reason accepted and not persisted
    batch = get_batch(bid)
    if batch["status"] not in ("MIXING", "MIXED"):
        raise ApiError(ERR_BATCH_INVALID_STATE, "void requires MIXING or MIXED", 409)
    # lazy pot-life touch on a MIXED batch
    if (batch["status"] == "MIXED" and batch["pot_life_deadline"] is not None
            and store.clock > batch["pot_life_deadline"]):
        fire_batch_expiry(batch)
        raise ApiError(ERR_POT_LIFE_EXCEEDED, "Pot life deadline has passed", 422)
    fire_batch_void(batch)
    return ok(ser_batch(batch), 200)


# ---------------------------------------------------------------------------
# PackagingRun
# ---------------------------------------------------------------------------

@bp.post("/api/packaging-runs")
@require_roles("BatchOperator")
def create_run():
    # schema
    b = body_json()
    batch_id = f_str(b, "batch_id")
    pack_format = f_enum(b, "pack_format", PACK_FORMATS)
    unit_volume = f_int(b, "unit_volume_ml", lo=1)
    planned_units = f_int(b, "planned_units", lo=1)
    start = f_dt(b, "planned_start_at")
    end = f_dt(b, "planned_end_at")
    if end < start:
        raise ApiError(ERR_INVALID_REQUEST, "planned_end_at must be at or after planned_start_at", 400)
    dry_room_id = b.get("dry_room_id")
    if dry_room_id is not None and (not isinstance(dry_room_id, str) or dry_room_id == ""):
        raise ApiError(ERR_INVALID_REQUEST, "Field dry_room_id must be a non-empty string", 400)
    # existence
    batch = store.batches.get(batch_id)
    if batch is None:
        raise not_found("ProductionBatch")
    room = None
    if dry_room_id is not None:
        room = store.dry_rooms.get(dry_room_id)
        if room is None:
            raise not_found("DryRoom")
    # state: batch must be MIXED or PACKING
    if batch["status"] not in ("MIXED", "PACKING"):
        raise ApiError(ERR_BATCH_INVALID_STATE, "Batch must be MIXED or PACKING", 409)
    formulation = store.formulations[batch["formulation_id"]]
    # safety: moisture protocol
    if formulation["moisture_sensitive"] and dry_room_id is None:
        raise ApiError(
            ERR_MOISTURE_PROTOCOL_VIOLATION,
            "Moisture-sensitive formulation requires a dry_room_id",
            422,
        )
    # temporal: lazy pot-life check
    if (batch["pot_life_deadline"] is not None
            and store.clock > batch["pot_life_deadline"]):
        fire_batch_expiry(batch)
        raise ApiError(ERR_POT_LIFE_EXCEEDED, "Pot life deadline has passed", 422)
    # constraint: dry-room aggregate capacity (closed interval semantics)
    if room is not None:
        count = 0
        for r in store.runs.values():
            if r["dry_room_id"] != room["id"] or r["status"] not in ("OPEN", "HOLD"):
                continue
            if r["planned_start_at"] <= end and start <= r["planned_end_at"]:
                count += 1
        if count >= room["max_concurrent_runs"]:
            raise ApiError(
                ERR_DRY_ROOM_CAPACITY_EXCEEDED,
                "Dry room capacity reached for the overlapping window",
                409,
            )
    # constraint: pack format / unit volume consistency within the batch
    lot = lot_of_batch(batch)
    if lot is not None and lot["pack_format"] is not None:
        if lot["pack_format"] != pack_format or lot["unit_volume_ml"] != unit_volume:
            raise ApiError(
                ERR_PACK_FORMAT_MISMATCH,
                "pack_format and unit_volume_ml must match the batch's established configuration",
                409,
            )
    run = new_entity()
    run.update({
        "batch_id": batch_id,
        "dry_room_id": dry_room_id,
        "pack_format": pack_format,
        "unit_volume_ml": unit_volume,
        "planned_units": planned_units,
        "planned_start_at": start,
        "planned_end_at": end,
        "per_unit_fill_ml": None,
        "units_produced": None,
        "total_filled_ml": None,
        "held_from": None,
        "status": "OPEN",
    })
    store.runs[run["id"]] = run
    # first run moves the batch to PACKING and pins the lot configuration
    if batch["status"] == "MIXED":
        batch["status"] = "PACKING"
        touch(batch)
    if lot is not None and lot["pack_format"] is None:
        lot["pack_format"] = pack_format
        lot["unit_volume_ml"] = unit_volume
        touch(lot)
    return ok(ser_run(run), 201)


@bp.get("/api/packaging-runs")
@require_roles(*ALL_ROLES)
def list_runs():
    limit, offset = pagination_params()
    rows = list(store.runs.values())
    bid = request.args.get("batch_id")
    did = request.args.get("dry_room_id")
    if bid is not None:
        rows = [r for r in rows if r["batch_id"] == bid]
    if did is not None:
        rows = [r for r in rows if r["dry_room_id"] == did]
    return ok_list([ser_run(r) for r in sorted_rows(rows)], limit, offset)


@bp.get("/api/packaging-runs/<rid>")
@require_roles(*ALL_ROLES)
def get_one_run(rid):
    return ok(ser_run(get_run(rid)), 200)


@bp.post("/api/packaging-runs/<rid>/complete")
@require_roles("BatchOperator")
def complete_run(rid):
    body_json()
    run = get_run(rid)
    if run["status"] != "OPEN":
        raise ApiError(ERR_RUN_INVALID_STATE, "complete requires OPEN", 409)
    batch = store.batches[run["batch_id"]]
    # temporal: lazy pot-life check
    if (batch["pot_life_deadline"] is not None
            and store.clock > batch["pot_life_deadline"]):
        fire_batch_expiry(batch)
        raise ApiError(ERR_POT_LIFE_EXCEEDED, "Pot life deadline has passed", 422)
    # fill allocation: round per unit first, then multiply by units
    per_unit, units, total = pack_fill(
        run["unit_volume_ml"], run["pack_format"],
        run["planned_units"], batch["remaining_bulk_volume_ml"],
    )
    if units == 0:
        raise ApiError(ERR_INSUFFICIENT_BATCH_VOLUME, "Allocation yields 0 units", 422)
    run["per_unit_fill_ml"] = per_unit
    run["units_produced"] = units
    run["total_filled_ml"] = total
    run["status"] = "SEALED"
    touch(run)
    batch["remaining_bulk_volume_ml"] -= total
    if batch["remaining_bulk_volume_ml"] == 0 and batch["status"] == "PACKING":
        batch["status"] = "PACKED"
    touch(batch)
    lot = lot_of_batch(batch)
    if lot is not None:
        lot["units_filled"] += units
        touch(lot)
    return ok(ser_run(run), 200)


# ---------------------------------------------------------------------------
# MoistureExposureEvent
# ---------------------------------------------------------------------------

@bp.post("/api/packaging-runs/<rid>/exposure-events")
@require_roles("BatchOperator")
def create_exposure_event(rid):
    b = body_json()
    minutes = f_int(b, "exposure_minutes", lo=0)
    occurred = f_dt(b, "occurred_at")
    note = b.get("note")
    if note is not None and not isinstance(note, str):
        raise ApiError(ERR_INVALID_REQUEST, "Field note must be a string", 400)
    run = get_run(rid)
    if run["status"] not in ("OPEN", "SEALED"):
        raise ApiError(ERR_RUN_INVALID_STATE, "Run must be OPEN or SEALED", 409)
    store.seq += 1
    event = {
        "id": str(uuid.uuid4()),
        "created_at": now_iso(),
        "_seq": store.seq,
        "packaging_run_id": rid,
        "exposure_minutes": minutes,
        "occurred_at": occurred,
        "note": note,
    }
    store.events[event["id"]] = event
    if minutes >= 30:
        _fire_hold_cascade(run)
    return ok(ser_event(event), 201)


def _fire_hold_cascade(run):
    """Run OPEN|SEALED -> HOLD; SEALED additionally quarantines the lot and
    forces PLANNED|CONFIRMED shipments containing the lot into EXCEPTION."""
    if run["status"] == "OPEN":
        run["held_from"] = "OPEN"
        run["status"] = "HOLD"
        touch(run)
        return
    # SEALED run: three-hop cascade
    run["held_from"] = "SEALED"
    run["status"] = "HOLD"
    touch(run)
    batch = store.batches[run["batch_id"]]
    lot = lot_of_batch(batch)
    if lot is not None:
        lot["units_quarantined"] += run["units_produced"] or 0
        lot["hold_status"] = "QUARANTINE_HOLD"
        touch(lot)
        for s in store.shipments.values():
            if s["status"] in ("PLANNED", "CONFIRMED") and any(
                ln["lot_id"] == lot["id"] for ln in s["lines"]
            ):
                s["status"] = "EXCEPTION"
                touch(s)


@bp.get("/api/exposure-events")
@require_roles(*ALL_ROLES)
def list_exposure_events():
    limit, offset = pagination_params()
    rows = list(store.events.values())
    rid = request.args.get("packaging_run_id")
    if rid is not None:
        rows = [e for e in rows if e["packaging_run_id"] == rid]
    return ok_list([ser_event(e) for e in sorted_rows(rows)], limit, offset)


@bp.get("/api/exposure-events/<eid>")
@require_roles(*ALL_ROLES)
def get_one_exposure_event(eid):
    return ok(ser_event(get_event(eid)), 200)


# ---------------------------------------------------------------------------
# Hold release
# ---------------------------------------------------------------------------

@bp.post("/api/packaging-runs/<rid>/hold-release")
@require_roles("QAManager")
def hold_release(rid):
    b = body_json()
    outcome = f_enum(b, "outcome", HOLD_OUTCOMES)
    run = get_run(rid)
    if run["status"] != "HOLD":
        raise ApiError(ERR_RUN_INVALID_STATE, "hold-release requires HOLD", 409)
    batch = store.batches[run["batch_id"]]
    lot = lot_of_batch(batch)
    held_from = run["held_from"]
    lot_changed = False
    if outcome == "RELEASE":
        run["status"] = held_from if held_from in ("OPEN", "SEALED") else "OPEN"
        run["held_from"] = None
        if held_from == "SEALED" and lot is not None:
            lot["units_quarantined"] -= run["units_produced"] or 0
            lot_changed = True
    else:  # CONDEMN
        run["status"] = "VOID"
        run["held_from"] = None
        if held_from == "SEALED" and lot is not None:
            lot["units_quarantined"] -= run["units_produced"] or 0
            lot["units_condemned"] += run["units_produced"] or 0
            batch["written_off_volume_ml"] += run["total_filled_ml"] or 0
            touch(batch)
            lot_changed = True
    touch(run)
    if lot is not None:
        before = lot["hold_status"]
        # recompute hold: CLEAR when no other HOLD runs reference this lot
        if not any(r["status"] == "HOLD" for r in runs_of_batch(batch["id"])):
            lot["hold_status"] = "CLEAR"
        lot_changed = lot_changed or lot["hold_status"] != before
        if lot_changed:
            touch(lot)
    return ok(ser_run(run), 200)
