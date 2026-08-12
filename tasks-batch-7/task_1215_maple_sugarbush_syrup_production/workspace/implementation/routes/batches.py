"""EvaporatorBatch and BatchIntake endpoints."""

from decimal import Decimal

from flask import Blueprint, request

import db
from middleware import authenticate, require_role, enforce_entity_identity
from response import success_object, success_list
from util import (body_json, check_unknown_fields, require_fields, as_int, as_str,
                  as_number, d, round2, parse_pagination, paginate)
from errors import (raise_err, ERR_NOT_FOUND, ERR_VALIDATION, ERR_INVALID_STATE,
                    ERR_BATCH_EMPTY, ERR_EVAPORATOR_BUSY, ERR_BRIX_BELOW_LEGAL,
                    ERR_DRAW_EXCEEDS_REMAINING, ERR_NO_SAP_AVAILABLE,
                    ERR_CREW_NOT_ACTIVE)
from services import core

bp = Blueprint("batches", __name__)

ALL_ROLES = {"SugarhouseManager", "FieldCrew", "SugarMaker", "CertInspector"}
BOILERS = {"SugarhouseManager", "SugarMaker"}


def get_batch_or_404(bid):
    b = db.batches.get(bid)
    if not b:
        raise_err(ERR_NOT_FOUND, f"batch {bid} not found")
    return b


@bp.post("/sugarhouse/batches")
def create_batch():
    caller = authenticate()
    require_role(caller, BOILERS)
    data = body_json()
    allowed = {"season_id", "boiled_by", "evaporator_capacity_gal"}
    check_unknown_fields(data, allowed)
    require_fields(data, ["season_id", "boiled_by", "evaporator_capacity_gal"])
    season_id = as_str(data["season_id"], "season_id")
    boiled_by = as_str(data["boiled_by"], "boiled_by")
    evaporator_capacity_gal = as_int(data["evaporator_capacity_gal"],
                                     "evaporator_capacity_gal", minimum=1)
    # Priority 2: entity-backed identity (SugarMaker boiled_by == X-User-ID)
    enforce_entity_identity(caller, boiled_by, "boiled_by")
    # Priority 3: FK existence
    if season_id not in db.seasons:
        raise_err(ERR_NOT_FOUND, f"season {season_id} not found")
    crew = db.crew_members.get(boiled_by)
    if not crew:
        raise_err(ERR_NOT_FOUND, f"crew member {boiled_by} not found")
    # Priority 5: state gates
    if crew["status"] != "ACTIVE":
        raise_err(ERR_CREW_NOT_ACTIVE, f"crew member is {crew['status']}, expected ACTIVE")
    b = core.new_batch(season_id, boiled_by, evaporator_capacity_gal)
    db.batches[b["id"]] = b
    return success_object(core.ser_batch(b), status=201)


@bp.get("/sugarhouse/batches/<bid>")
def get_batch(bid):
    caller = authenticate()
    require_role(caller, ALL_ROLES)
    b = get_batch_or_404(bid)
    return success_object(core.ser_batch(b))


@bp.get("/sugarhouse/batches")
def list_batches():
    caller = authenticate()
    require_role(caller, ALL_ROLES)
    limit, offset = parse_pagination(request.args)
    season_id = request.args.get("season_id")
    boiled_by = request.args.get("boiled_by")
    status = request.args.get("status")
    rows = list(db.batches.values())
    if season_id is not None:
        rows = [r for r in rows if r["season_id"] == season_id]
    if boiled_by is not None:
        rows = [r for r in rows if r["boiled_by"] == boiled_by]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    page, total = paginate(rows, limit, offset)
    return success_list([core.ser_batch(r) for r in page], limit, offset, total)


def _next_draw_sequence(batch_id):
    existing = [i["draw_sequence"] for i in db.batch_intakes.values()
                if i["batch_id"] == batch_id]
    return (max(existing) + 1) if existing else 1


def _do_draw(batch, run, gallons_drawn):
    """Shared intake-creation path. Assumes caller validated run/batch state and
    0 < gallons_drawn <= run.gallons_remaining."""
    gallons_drawn = round2(d(gallons_drawn))
    intake = core.new_batch_intake(
        batch_id=batch["id"],
        sap_run_id=run["id"],
        gallons_drawn=gallons_drawn,
        draw_sequence=_next_draw_sequence(batch["id"]),
    )
    db.batch_intakes[intake["id"]] = intake
    run["gallons_remaining"] = round2(d(run["gallons_remaining"]) - gallons_drawn)
    core.touch(run)
    batch["sap_gallons_in"] = round2(d(batch["sap_gallons_in"]) + gallons_drawn)
    core.touch(batch)
    return intake


@bp.post("/sugarhouse/batches/<bid>/intakes")
def add_intake(bid):
    caller = authenticate()
    require_role(caller, BOILERS)
    batch = get_batch_or_404(bid)
    data = body_json()
    check_unknown_fields(data, {"sap_run_id", "gallons_drawn"})
    require_fields(data, ["sap_run_id", "gallons_drawn"])
    sap_run_id = as_str(data["sap_run_id"], "sap_run_id")
    # For SugarMaker acting on batches, X-User-ID must match batch.boiled_by.
    enforce_entity_identity(caller, batch["boiled_by"], "boiled_by")
    gallons_drawn = as_number(data["gallons_drawn"], "gallons_drawn")
    run = db.sap_runs.get(sap_run_id)
    if not run:
        raise_err(ERR_NOT_FOUND, f"sap run {sap_run_id} not found")
    # Priority 5: batch state and run state
    if batch["status"] != "FILLING":
        raise_err(ERR_INVALID_STATE, f"batch is {batch['status']}, expected FILLING")
    if run["status"] != "CONFIRMED":
        raise_err(ERR_INVALID_STATE, f"sap run is {run['status']}, expected CONFIRMED")
    # Priority 10: quantity sufficiency
    if gallons_drawn <= 0 or gallons_drawn > d(run["gallons_remaining"]):
        raise_err(ERR_DRAW_EXCEEDS_REMAINING,
                  "gallons_drawn must be > 0 and <= run.gallons_remaining")
    intake = _do_draw(batch, run, gallons_drawn)
    return success_object(core.ser_batch_intake(intake), status=201)


@bp.post("/sugarhouse/batches/<bid>/auto-fill")
def auto_fill(bid):
    caller = authenticate()
    require_role(caller, BOILERS)
    batch = get_batch_or_404(bid)
    data = body_json()
    check_unknown_fields(data, {"target_gallons"})
    require_fields(data, ["target_gallons"])
    target_gallons = as_number(data["target_gallons"], "target_gallons",
                               minimum=0, exclusive_min=True)
    enforce_entity_identity(caller, batch["boiled_by"], "boiled_by")
    if batch["status"] != "FILLING":
        raise_err(ERR_INVALID_STATE, f"batch is {batch['status']}, expected FILLING")

    # FIFO candidates: CONFIRMED, season match, gallons_remaining > 0, ordered
    # collected_at ASC, tie-break created_at ASC.
    candidates = []
    for r in db.sap_runs.values():
        bush = db.sugarbushes.get(r["sugarbush_id"])
        if not bush or bush["season_id"] != batch["season_id"]:
            continue
        if r["status"] != "CONFIRMED":
            continue
        if d(r["gallons_remaining"]) <= 0:
            continue
        candidates.append(r)
    candidates.sort(key=lambda r: (r["collected_at"], r["created_at"]))
    total_available = sum((d(r["gallons_remaining"]) for r in candidates), Decimal("0"))
    if total_available == 0:
        raise_err(ERR_NO_SAP_AVAILABLE, "no CONFIRMED runs with gallons_remaining > 0")

    remaining_need = d(target_gallons)
    for run in candidates:
        if remaining_need <= 0:
            break
        draw = min(d(run["gallons_remaining"]), remaining_need)
        if draw > 0:
            _do_draw(batch, run, draw)
            remaining_need -= draw
    core.touch(batch)
    return success_object(core.ser_batch(batch))


@bp.get("/sugarhouse/batches/<bid>/intakes")
def list_batch_intakes(bid):
    caller = authenticate()
    require_role(caller, ALL_ROLES)
    batch = get_batch_or_404(bid)
    limit, offset = parse_pagination(request.args)
    rows = [i for i in db.batch_intakes.values() if i["batch_id"] == batch["id"]]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    page, total = paginate(rows, limit, offset)
    return success_list([core.ser_batch_intake(r) for r in page], limit, offset, total)


@bp.post("/sugarhouse/batches/<bid>/start-boil")
def start_boil(bid):
    caller = authenticate()
    require_role(caller, BOILERS)
    batch = get_batch_or_404(bid)
    enforce_entity_identity(caller, batch["boiled_by"], "boiled_by")
    if batch["status"] != "FILLING":
        raise_err(ERR_INVALID_STATE, f"batch is {batch['status']}, expected FILLING")
    if d(batch["sap_gallons_in"]) <= 0:
        raise_err(ERR_BATCH_EMPTY, "batch has no sap drawn")
    for other in db.batches.values():
        if (other["id"] != batch["id"]
                and other["season_id"] == batch["season_id"]
                and other["status"] == "BOILING"):
            raise_err(ERR_EVAPORATOR_BUSY, "another batch of this season is BOILING")
    batch["boil_started_at"] = core.clock_dt() and __import__("util").now_iso()
    core.compute_start_boil(batch)
    batch["status"] = "BOILING"
    core.bump(batch)
    return success_object(core.ser_batch(batch))


@bp.post("/sugarhouse/batches/<bid>/finish")
def finish_batch(bid):
    caller = authenticate()
    require_role(caller, BOILERS)
    batch = get_batch_or_404(bid)
    data = body_json()
    check_unknown_fields(data, {"finished_brix", "measured_syrup_gallons"})
    require_fields(data, ["finished_brix", "measured_syrup_gallons"])
    enforce_entity_identity(caller, batch["boiled_by"], "boiled_by")
    finished_brix = as_number(data["finished_brix"], "finished_brix")
    measured_syrup_gallons = as_number(data["measured_syrup_gallons"],
                                       "measured_syrup_gallons",
                                       minimum=0, exclusive_min=True)
    if batch["status"] != "BOILING":
        raise_err(ERR_INVALID_STATE, f"batch is {batch['status']}, expected BOILING")
    if finished_brix < core.LEGAL_BRIX_MIN:
        raise_err(ERR_BRIX_BELOW_LEGAL,
                  "finished_brix must be >= 66.0 (legal maple syrup minimum)")

    variance = core.compute_yield_variance(measured_syrup_gallons,
                                           batch["expected_syrup_gallons"])
    batch["finished_brix"] = finished_brix
    batch["measured_syrup_gallons"] = measured_syrup_gallons
    batch["yield_variance_pct"] = variance
    batch["status"] = "FINISHED"
    core.bump(batch)

    # HOP1: create SyrupLot
    held = abs(variance) >= core.VARIANCE_HOLD_PCT
    lot = core.new_syrup_lot(
        batch_id=batch["id"],
        season_id=batch["season_id"],
        measured_gallons=measured_syrup_gallons,
        finished_brix=finished_brix,
        held_auto=held,
    )
    db.syrup_lots[lot["id"]] = lot

    # HOP2: season total_syrup_gallons
    season = db.seasons.get(batch["season_id"])
    if season:
        core.recompute_season_syrup(season)

    # HOP2: provisional royalty accrual
    core.accrue_provisional_royalty(batch)

    return success_object(core.ser_batch(batch))


@bp.post("/sugarhouse/batches/<bid>/cancel")
def cancel_batch(bid):
    caller = authenticate()
    require_role(caller, BOILERS)
    batch = get_batch_or_404(bid)
    enforce_entity_identity(caller, batch["boiled_by"], "boiled_by")
    if batch["status"] != "FILLING":
        raise_err(ERR_INVALID_STATE,
                  f"batch is {batch['status']}; only FILLING can be cancelled")
    # Compensation: return drawn gallons to each run
    for intake in core.batch_intakes_of(batch["id"]):
        run = db.sap_runs.get(intake["sap_run_id"])
        if run:
            run["gallons_remaining"] = round2(d(run["gallons_remaining"])
                                              + d(intake["gallons_drawn"]))
            core.touch(run)
    batch["status"] = "CANCELLED"
    core.bump(batch)
    return success_object(core.ser_batch(batch))
