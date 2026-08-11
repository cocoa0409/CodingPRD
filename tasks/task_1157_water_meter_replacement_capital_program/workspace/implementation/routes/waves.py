"""Wave endpoints (PRD 3.3)."""
import db
from db import base_resource, touch
from errors import raise_err
from middleware import ALL_ROLES, require_roles
from response import ok_object
from services.core import get_or_404, list_page, program_derived, ser_wave
from flask import Blueprint, request
from validate import body, req_dt, req_int, req_str

bp = Blueprint("waves", __name__)


@bp.post("/api/waves")
@require_roles("ProgramManager")
def create_wave():
    b = body()
    program_id = b.get("program_id")
    program = None
    if isinstance(program_id, str):
        program = get_or_404(db.programs, program_id, "Program")
    program_id = req_str(b, "program_id")
    if program is None:
        program = get_or_404(db.programs, program_id, "Program")
    wave_number = req_int(b, "wave_number")
    window_start = req_dt(b, "window_start")
    window_end = req_dt(b, "window_end")
    capacity = req_int(b, "capacity", min=1)
    # Uniqueness: wave_number per program -> ERR_VALIDATION (PRD 2.7 stage 6).
    for w in db.waves.values():
        if w["program_id"] == program["id"] and w["wave_number"] == wave_number:
            raise_err("ERR_VALIDATION",
                      "wave_number already used within this program")
    w = base_resource()
    w.update({
        "program_id": program["id"],
        "wave_number": wave_number,
        "window_start": window_start,
        "window_end": window_end,
        "capacity": capacity,
        "status": "DRAFT",
    })
    db.waves[w["id"]] = w
    return ok_object(ser_wave(w), 201)


@bp.get("/api/waves")
@require_roles(*ALL_ROLES)
def list_waves():
    filters = {}
    for k in ("program_id", "status"):
        if request.args.get(k) is not None:
            filters[k] = request.args[k]
    return list_page(db.waves.values(), filters, ser_wave)


@bp.get("/api/waves/<waveId>")
@require_roles(*ALL_ROLES)
def get_wave(waveId):
    return ok_object(ser_wave(get_or_404(db.waves, waveId, "Wave")))


@bp.post("/api/waves/<waveId>/open")
@require_roles("ProgramManager")
def open_wave(waveId):
    w = get_or_404(db.waves, waveId, "Wave")
    if w["status"] != "DRAFT":
        raise_err("ERR_INVALID_STATE", "Wave is not in DRAFT")
    program = get_or_404(db.programs, w["program_id"], "Program")
    if program["status"] != "ACTIVE":
        raise_err("ERR_PROGRAM_NOT_ACTIVE", "Wave opening requires an ACTIVE program")
    # Half-open [start, end) overlap against other OPEN/LOCKED waves of the
    # same program; adjacency is allowed (PRD 3.3).
    for other in db.waves.values():
        if (
            other["id"] != w["id"]
            and other["program_id"] == w["program_id"]
            and other["status"] in ("OPEN", "LOCKED")
            and w["window_start"] < other["window_end"]
            and other["window_start"] < w["window_end"]
        ):
            raise_err("ERR_WAVE_WINDOW_OVERLAP",
                      "Wave window intersects another OPEN/LOCKED wave")
    w["status"] = "OPEN"
    touch(w)
    return ok_object(ser_wave(w))


@bp.post("/api/waves/<waveId>/lock")
@require_roles("ProgramManager")
def lock_wave(waveId):
    w = get_or_404(db.waves, waveId, "Wave")
    if w["status"] != "OPEN":
        raise_err("ERR_INVALID_STATE", "Wave is not in OPEN")
    program = get_or_404(db.programs, w["program_id"], "Program")
    committed, _, _, _, _ = program_derived(program)
    # Program-wide commitment check, equality allowed (PRD 3.3).
    if committed > program["budget_total_cents"]:
        raise_err("ERR_BUDGET_COMMITMENT_EXCEEDED",
                  "Committed budget exceeds program budget_total_cents")
    w["status"] = "LOCKED"
    touch(w)
    return ok_object(ser_wave(w))


@bp.post("/api/waves/<waveId>/complete")
@require_roles("ProgramManager")
def complete_wave(waveId):
    w = get_or_404(db.waves, waveId, "Wave")
    if w["status"] != "LOCKED":
        raise_err("ERR_INVALID_STATE", "Wave is not in LOCKED")
    for wo in db.work_orders.values():
        if wo["wave_id"] == w["id"] and wo["lifecycle_status"] not in ("CLOSED", "CANCELLED"):
            raise_err("ERR_INVALID_STATE",
                      "Every work order must be CLOSED or CANCELLED")
    w["status"] = "COMPLETE"
    touch(w)
    return ok_object(ser_wave(w))


@bp.post("/api/waves/<waveId>/cancel")
@require_roles("ProgramManager")
def cancel_wave(waveId):
    w = get_or_404(db.waves, waveId, "Wave")
    if w["status"] not in ("DRAFT", "OPEN"):
        raise_err("ERR_INVALID_STATE", "Wave cannot be cancelled from this state")
    for wo in db.work_orders.values():
        if wo["wave_id"] == w["id"] and wo["lifecycle_status"] != "CANCELLED":
            raise_err("ERR_INVALID_STATE",
                      "Wave still has non-cancelled work orders")
    w["status"] = "CANCELLED"
    touch(w)
    return ok_object(ser_wave(w))
