"""Line runs: queue, start, set-speed, complete, list."""

from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_LINE_TYPE_MISMATCH,
    ERR_LOT_SHIFT_MISMATCH,
    ERR_LINE_SPEED_NOT_AUTHORIZED,
    ERR_SHIFT_NOT_RUNNING,
    ERR_SHIFT_TERMINAL,
    ERR_RUN_NOT_STARTABLE,
    ERR_PREOP_NOT_PASSED,
    ERR_SANITATION_NOT_VERIFIED,
    ERR_INVALID_STATE_TRANSITION,
    ERR_CONDEMNATION_COUNT_EXCEEDS_HUNG,
)
from middleware import (
    require_roles,
    get_json_body,
    check_required,
    check_no_unknown,
    check_int,
    check_number,
    check_string,
    parse_pagination,
)
from response import success_object, success_list
from services.core import (
    new_entity,
    _touch,
    lazy_line,
    lazy_lot,
    effective_max_line_speed,
    recompute_lot_aggregates,
    recompute_shift_aggregates,
    maybe_reconcile_run,
)
from services.serializers import serialize_line_run, serialize_condemnation

bp = Blueprint("line_runs", __name__)

ALL_ROLES = (
    "PlantManager", "ShiftSupervisor", "ReceivingClerk", "LineOperator",
    "QATechnician", "SanitationLead", "USDAInspector", "OrderPlanner",
)


@bp.route("/poultry/line-runs", methods=["POST"])
def create_line_run():
    require_roles("ShiftSupervisor")
    body = get_json_body()
    check_no_unknown(body, {"shift_id", "line_id", "flock_lot_id", "planned_speed_bpm"})
    check_required(body, ["shift_id", "line_id", "flock_lot_id", "planned_speed_bpm"])
    check_string(body["shift_id"], "shift_id")
    check_string(body["line_id"], "line_id")
    check_string(body["flock_lot_id"], "flock_lot_id")
    check_int(body["planned_speed_bpm"], "planned_speed_bpm", min_value=1)

    # Existence left-to-right: shift, line, lot
    shift = db.shifts.get(body["shift_id"])
    if not shift:
        raise ApiError(ERR_NOT_FOUND, "Shift not found", 404)
    line = db.lines.get(body["line_id"])
    if not line:
        raise ApiError(ERR_NOT_FOUND, "Line not found", 404)
    lot = db.flock_lots.get(body["flock_lot_id"])
    if not lot:
        raise ApiError(ERR_NOT_FOUND, "Flock lot not found", 404)

    if shift["status"] == "CLOSED":
        raise ApiError(ERR_SHIFT_TERMINAL, "Mutation attempted on a CLOSED shift", 409)

    # Referential gates
    if line["line_type"] != "EVISCERATION":
        raise ApiError(
            ERR_LINE_TYPE_MISMATCH, "LineRun requires an EVISCERATION line", 422
        )
    if lot["receiving_shift_id"] != shift["id"]:
        raise ApiError(
            ERR_LOT_SHIFT_MISMATCH,
            "Run's flock lot is booked into a different shift than the run",
            422,
        )

    # Planned speed within the effective cap at creation
    lazy_line(line["id"])
    cap = effective_max_line_speed(line, shift)
    if body["planned_speed_bpm"] > cap:
        raise ApiError(
            ERR_LINE_SPEED_NOT_AUTHORIZED,
            "Planned speed exceeds effective_max_line_speed",
            403,
        )

    run = new_entity()
    run.update({
        "shift_id": shift["id"],
        "line_id": line["id"],
        "flock_lot_id": lot["id"],
        "planned_speed_bpm": body["planned_speed_bpm"],
        "current_speed_bpm": None,
        "speed_clamped": False,
        "status": "QUEUED",
        "birds_hung": None,
        "carcass_weight_lb": None,
        "auto_paused": False,
        "started_at": None,
        "completed_at": None,
    })
    db.line_runs[run["id"]] = run
    return success_object(serialize_line_run(run), 201)


@bp.route("/poultry/line-runs", methods=["GET"])
def list_line_runs():
    require_roles(*ALL_ROLES)
    items = list(db.line_runs.values())
    shift_id = request.args.get("shift_id")
    line_id = request.args.get("line_id")
    flock_lot_id = request.args.get("flock_lot_id")
    if shift_id is not None:
        items = [r for r in items if r["shift_id"] == shift_id]
    if line_id is not None:
        items = [r for r in items if r["line_id"] == line_id]
    if flock_lot_id is not None:
        items = [r for r in items if r["flock_lot_id"] == flock_lot_id]
    items.sort(key=lambda r: r["created_at"])
    limit, offset = parse_pagination()
    page = items[offset:offset + limit]
    return success_list([serialize_line_run(r) for r in page], limit, offset, len(items))


@bp.route("/poultry/line-runs/<run_id>", methods=["GET"])
def get_line_run(run_id):
    require_roles(*ALL_ROLES)
    run = db.line_runs.get(run_id)
    if not run:
        raise ApiError(ERR_NOT_FOUND, "Line run not found", 404)
    lazy_line(run["line_id"])
    return success_object(serialize_line_run(run))


@bp.route("/poultry/line-runs/<run_id>/set-speed", methods=["POST"])
def set_speed(run_id):
    require_roles("LineOperator")
    run = db.line_runs.get(run_id)
    if not run:
        raise ApiError(ERR_NOT_FOUND, "Line run not found", 404)
    body = get_json_body()
    check_no_unknown(body, {"new_speed_bpm"})
    check_required(body, ["new_speed_bpm"])
    check_int(body["new_speed_bpm"], "new_speed_bpm", min_value=1)

    shift = db.shifts.get(run["shift_id"])
    if not shift:
        raise ApiError(ERR_NOT_FOUND, "Shift not found", 404)
    if shift["status"] == "CLOSED":
        raise ApiError(ERR_SHIFT_TERMINAL, "Mutation attempted on a CLOSED shift", 409)
    # PRD 2.6 rung 4 names the shift-RUNNING guard for speed changes before the
    # generic from-state fallback.
    if shift["status"] != "RUNNING":
        raise ApiError(
            ERR_SHIFT_NOT_RUNNING, "set-speed requires the enclosing shift in RUNNING", 409
        )
    if run["status"] != "RUNNING":
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION, "set-speed requires the run in RUNNING", 409
        )

    line = db.lines.get(run["line_id"])
    lazy_line(line["id"])
    cap = effective_max_line_speed(line, shift)
    if body["new_speed_bpm"] > cap:
        raise ApiError(
            ERR_LINE_SPEED_NOT_AUTHORIZED,
            "Requested speed exceeds effective_max_line_speed",
            403,
        )

    run["current_speed_bpm"] = body["new_speed_bpm"]
    run["speed_clamped"] = False
    _touch(run)
    return success_object(serialize_line_run(run))


@bp.route("/poultry/line-runs/<run_id>/advance", methods=["POST"])
def advance_line_run(run_id):
    user_id, role = require_roles("LineOperator")
    run = db.line_runs.get(run_id)
    if not run:
        raise ApiError(ERR_NOT_FOUND, "Line run not found", 404)
    body = get_json_body()
    check_no_unknown(body, {"to_status", "birds_hung", "carcass_weight_lb"})
    check_required(body, ["to_status"])
    from middleware import check_enum
    check_enum(body["to_status"], ("RUNNING", "COMPLETED"), "to_status")
    to_status = body["to_status"]

    if to_status == "RUNNING":
        return _start_run(run)
    return _complete_run(run, body)


def _start_run(run):
    shift = db.shifts.get(run["shift_id"])
    if not shift:
        raise ApiError(ERR_NOT_FOUND, "Shift not found", 404)
    if shift["status"] == "CLOSED":
        raise ApiError(ERR_SHIFT_TERMINAL, "Mutation attempted on a CLOSED shift", 409)
    # PRD 2.6 rung 4 names the shift-RUNNING guard for run starts before the
    # generic from-state fallback.
    if shift["status"] != "RUNNING":
        raise ApiError(
            ERR_SHIFT_NOT_RUNNING, "Run start requires the enclosing shift in RUNNING", 409
        )
    if run["status"] != "QUEUED":
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION, "RUNNING permitted only from QUEUED", 409
        )
    lot = db.flock_lots.get(run["flock_lot_id"])
    if not lot:
        raise ApiError(ERR_NOT_FOUND, "Flock lot not found", 404)
    lazy_lot(lot)
    if lot["status"] not in ("RECEIVED", "ON_LINE"):
        raise ApiError(
            ERR_RUN_NOT_STARTABLE,
            "Run start attempted while flock lot not RECEIVED/ON_LINE",
            409,
        )
    line = db.lines.get(run["line_id"])
    lazy_line(line["id"])
    cap = effective_max_line_speed(line, shift)
    if run["planned_speed_bpm"] > cap:
        raise ApiError(
            ERR_LINE_SPEED_NOT_AUTHORIZED,
            "Planned speed exceeds effective_max_line_speed",
            403,
        )
    passed = any(
        p for p in db.preop_inspections.values()
        if p["shift_id"] == run["shift_id"] and p["line_id"] == run["line_id"]
        and p["status"] == "PASSED"
    )
    if not passed:
        raise ApiError(
            ERR_PREOP_NOT_PASSED, "No PASSED pre-op inspection for (shift,line)", 409
        )
    verified = any(
        s for s in db.sanitation_runs.values()
        if s["shift_id"] == run["shift_id"] and s["line_id"] == run["line_id"]
        and s["status"] == "VERIFIED"
    )
    if not verified:
        raise ApiError(
            ERR_SANITATION_NOT_VERIFIED, "No VERIFIED sanitation run for (shift,line)", 409
        )

    run["status"] = "RUNNING"
    run["current_speed_bpm"] = run["planned_speed_bpm"]
    run["started_at"] = db.clock_now()
    _touch(run)

    # First running run of the lot bubbles the lot RECEIVED -> ON_LINE
    if lot["status"] == "RECEIVED":
        lot["status"] = "ON_LINE"
        _touch(lot)

    return success_object(serialize_line_run(run))


def _complete_run(run, body):
    if run["status"] != "RUNNING":
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            "COMPLETED attempted from a state other than RUNNING",
            409,
        )
    if "birds_hung" not in body or body["birds_hung"] is None:
        raise ApiError(ERR_INVALID_REQUEST, "birds_hung is required", 400)
    if "carcass_weight_lb" not in body or body["carcass_weight_lb"] is None:
        raise ApiError(ERR_INVALID_REQUEST, "carcass_weight_lb is required", 400)
    check_int(body["birds_hung"], "birds_hung", min_value=1)
    check_number(
        body["carcass_weight_lb"], "carcass_weight_lb", min_value=0, exclusive_min=True
    )

    lot = db.flock_lots.get(run["flock_lot_id"])
    if not lot:
        raise ApiError(ERR_NOT_FOUND, "Flock lot not found", 404)

    # Bird accountability: birds_hung <= head_count_received - doa_count - birds_hung_total
    remaining = (
        (lot.get("head_count_received") or 0)
        - (lot.get("doa_count") or 0)
        - (lot.get("birds_hung_total") or 0)
    )
    if body["birds_hung"] > remaining:
        raise ApiError(
            ERR_CONDEMNATION_COUNT_EXCEEDS_HUNG,
            "birds_hung exceeds the lot's remaining hangable birds",
            422,
        )

    run["birds_hung"] = body["birds_hung"]
    run["carcass_weight_lb"] = body["carcass_weight_lb"]
    run["completed_at"] = db.clock_now()
    run["status"] = "COMPLETED"
    _touch(run)

    # A run with zero condemnation records is reconciled automatically at completion
    maybe_reconcile_run(run)

    # Roll up: lot aggregates + provisional yield; shift aggregates + water rates
    recompute_lot_aggregates(lot)
    _touch(lot)
    shift = db.shifts.get(run["shift_id"])
    if shift:
        recompute_shift_aggregates(shift)
        _touch(shift)

    return success_object(serialize_line_run(run))


@bp.route("/poultry/line-runs/<run_id>/condemnation-records", methods=["GET"])
def list_run_condemnations(run_id):
    require_roles(*ALL_ROLES)
    run = db.line_runs.get(run_id)
    if not run:
        raise ApiError(ERR_NOT_FOUND, "Line run not found", 404)
    items = [c for c in db.condemnation_records.values() if c["line_run_id"] == run_id]
    items.sort(key=lambda c: c["created_at"])
    limit, offset = parse_pagination()
    page = items[offset:offset + limit]
    return success_list([serialize_condemnation(c) for c in page], limit, offset, len(items))
