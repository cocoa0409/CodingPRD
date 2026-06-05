"""Instrument and InstrumentRun routes."""
from __future__ import annotations

from datetime import timedelta

from flask import Blueprint, request

import db
from errors import (
    APIError, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
    ERR_DUPLICATE_IDENTIFIER, ERR_INSTRUMENT_SLOT_CONFLICT,
)
from middleware import require_auth, get_json_body
from response import ok_object, ok_array, paginate_params, slice_page
from services.validation import (
    require_fields, require_string, require_enum, require_int, require_list,
    lookup_or_404,
)


bp = Blueprint("instruments", __name__)

PANEL_CODES = {"CMP", "CBC", "TROP", "GLUC"}
RUN_STATUSES = {"SCHEDULED", "IN_PROGRESS", "COMPLETED", "FAILED"}


# ---------- POST /instruments ---------------------------------------------

@bp.post("/instruments")
def create_instrument():
    require_auth(["LabDirector"])()
    body = get_json_body()
    require_fields(body, ["instrument_code", "analyte_panels_supported"])
    code = body["instrument_code"]
    panels = body["analyte_panels_supported"]
    qc_buffer = body.get("qc_buffer_minutes", 5)

    require_string(code, "instrument_code")
    require_list(panels, "analyte_panels_supported")
    for p in panels:
        require_enum(p, PANEL_CODES, "analyte_panels_supported[*]")
    require_int(qc_buffer, "qc_buffer_minutes", min_v=0, max_v=60)

    for inst in db.instruments.values():
        if inst.get("instrument_code") == code:
            raise APIError(ERR_DUPLICATE_IDENTIFIER, 409,
                           f"Instrument with instrument_code '{code}' already exists")

    inst = {
        "instrument_code": code,
        "analyte_panels_supported": list(panels),
        "qc_buffer_minutes": qc_buffer,
    }
    db.stamp_common(inst)
    db.instruments[inst["id"]] = inst
    return ok_object(inst, http_status=201)


@bp.get("/instruments/<iid>")
def get_instrument(iid):
    require_auth(["LabTech", "LabDirector"])()
    inst = lookup_or_404(db.instruments, iid, "Instrument")
    return ok_object(inst)


@bp.get("/instruments")
def list_instruments():
    require_auth(["LabTech", "LabDirector"])()
    limit, offset = paginate_params(request.args)
    items = list(db.instruments.values())
    items.sort(key=lambda x: x["created_at"])
    page, total = slice_page(items, limit, offset)
    return ok_array(page, limit, offset, total)


# ---------- POST /instrument-runs -----------------------------------------

@bp.post("/instrument-runs")
def create_instrument_run():
    require_auth(["LabTech"])()
    body = get_json_body()
    require_fields(body, ["instrument_id", "specimen_id", "scheduled_start", "scheduled_end"])
    inst_id = body["instrument_id"]
    spec_id = body["specimen_id"]
    sched_start = body["scheduled_start"]
    sched_end = body["scheduled_end"]

    require_string(inst_id, "instrument_id")
    require_string(spec_id, "specimen_id")
    require_string(sched_start, "scheduled_start")
    require_string(sched_end, "scheduled_end")

    inst = lookup_or_404(db.instruments, inst_id, "Instrument")
    spec = lookup_or_404(db.specimens, spec_id, "Specimen")

    if spec.get("status") != "ACCESSIONED":
        raise APIError(ERR_INVALID_STATE, 409,
                       "Specimen must be ACCESSIONED to schedule a run")

    try:
        start_dt = db.parse_iso_dt(sched_start)
        end_dt = db.parse_iso_dt(sched_end)
    except Exception:
        raise APIError(ERR_INVALID_REQUEST, 400,
                       "scheduled_start and scheduled_end must be ISO 8601 datetimes")
    if start_dt is None or end_dt is None:
        raise APIError(ERR_INVALID_REQUEST, 400,
                       "scheduled_start and scheduled_end must be ISO 8601 datetimes")
    if end_dt <= start_dt:
        raise APIError(ERR_INVALID_REQUEST, 400,
                       "scheduled_end must be strictly greater than scheduled_start")

    # Slot-conflict check: against every existing run on the same instrument
    # with status in {SCHEDULED, IN_PROGRESS, COMPLETED}, treat that run's
    # interval [A, B) as [A - buf, B + buf) (buf = qc_buffer_minutes) and the
    # proposed [start_dt, end_dt) must be disjoint from every such buffered
    # window.
    buf = timedelta(minutes=int(inst.get("qc_buffer_minutes", 5)))
    for run in db.instrument_runs.values():
        if run.get("instrument_id") != inst_id:
            continue
        if run.get("status") not in ("SCHEDULED", "IN_PROGRESS", "COMPLETED"):
            continue
        a = db.parse_iso_dt(run["scheduled_start"])
        b = db.parse_iso_dt(run["scheduled_end"])
        if a is None or b is None:
            continue
        widened_start = a - buf
        widened_end = b + buf
        # Half-open intervals: [start_dt, end_dt) overlaps [widened_start, widened_end)
        # iff start_dt < widened_end AND widened_start < end_dt.
        if start_dt < widened_end and widened_start < end_dt:
            raise APIError(ERR_INSTRUMENT_SLOT_CONFLICT, 409,
                           "Proposed run conflicts with an existing run "
                           "after applying the qc_buffer_minutes window")

    run = {
        "instrument_id": inst_id,
        "specimen_id": spec_id,
        "scheduled_start": sched_start,
        "scheduled_end": sched_end,
        "status": "SCHEDULED",
    }
    db.stamp_common(run)
    db.instrument_runs[run["id"]] = run
    return ok_object(run, http_status=201)


@bp.get("/instrument-runs/<rid>")
def get_instrument_run(rid):
    require_auth(["LabTech", "LabDirector"])()
    run = lookup_or_404(db.instrument_runs, rid, "InstrumentRun")
    return ok_object(run)


@bp.get("/instrument-runs")
def list_instrument_runs():
    require_auth(["LabTech", "LabDirector"])()
    limit, offset = paginate_params(request.args)
    inst_filter = request.args.get("instrument_id")
    spec_filter = request.args.get("specimen_id")
    status_filter = request.args.get("status")
    items = list(db.instrument_runs.values())
    if inst_filter is not None:
        items = [r for r in items if r.get("instrument_id") == inst_filter]
    if spec_filter is not None:
        items = [r for r in items if r.get("specimen_id") == spec_filter]
    if status_filter is not None:
        items = [r for r in items if r.get("status") == status_filter]
    items.sort(key=lambda x: x["created_at"])
    page, total = slice_page(items, limit, offset)
    return ok_array(page, limit, offset, total)


@bp.post("/instrument-runs/<rid>/complete")
def complete_instrument_run(rid):
    require_auth(["LabTech"])()
    run = lookup_or_404(db.instrument_runs, rid, "InstrumentRun")
    if run.get("status") not in ("SCHEDULED", "IN_PROGRESS"):
        raise APIError(ERR_INVALID_STATE, 409,
                       f"InstrumentRun.status '{run.get('status')}' cannot complete")
    run["status"] = "COMPLETED"
    db.bump(run)
    return ok_object(run)
