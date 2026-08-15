"""Production shifts: create/get/staffing/transition + scoped lists."""

from flask import Blueprint

import db
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_STALE_SHIFT_VERSION,
    ERR_SHIFT_NOT_OPENABLE,
    ERR_SHIFT_NOT_RUNNING,
    ERR_SHIFT_NOT_SUSPENDED,
    ERR_SHIFT_TERMINAL,
    ERR_RUNS_NOT_TERMINAL,
    ERR_NO_RUNS_QUEUED,
    ERR_SANITATION_NOT_VERIFIED,
    ERR_PREOP_NOT_PASSED,
    ERR_INVALID_STATE_TRANSITION,
    ERR_INSUFFICIENT_PERMISSIONS,
)
from middleware import (
    require_roles,
    get_json_body,
    check_required,
    check_no_unknown,
    check_enum,
    check_int,
    check_number,
    check_string,
    parse_pagination,
)
from response import success_object, success_list
from services.core import (
    new_entity,
    _touch,
    recompute_shift_aggregates,
    clamp_runs_for_shift,
    now_iso,
)
from services.serializers import (
    serialize_shift,
    serialize_sanitation_run,
    serialize_preop,
    serialize_flock_lot,
    serialize_utility_reading,
)

bp = Blueprint("shifts", __name__)

ALL_ROLES = (
    "PlantManager", "ShiftSupervisor", "ReceivingClerk", "LineOperator",
    "QATechnician", "SanitationLead", "USDAInspector", "OrderPlanner",
)
SHIFT_CODES = ("DAY_A", "DAY_B", "NIGHT")


@bp.route("/poultry/shifts", methods=["POST"])
def create_shift():
    require_roles("PlantManager")
    body = get_json_body()
    check_no_unknown(
        body,
        {"shift_date", "shift_code", "shackle_capacity_birds", "labor_hours_budget"},
    )
    check_required(
        body, ["shift_date", "shift_code", "shackle_capacity_birds", "labor_hours_budget"]
    )
    check_string(body["shift_date"], "shift_date")
    check_enum(body["shift_code"], SHIFT_CODES, "shift_code")
    check_int(body["shackle_capacity_birds"], "shackle_capacity_birds", min_value=1)
    check_number(body["labor_hours_budget"], "labor_hours_budget", min_value=0)

    shift = new_entity()
    shift.update({
        "shift_date": body["shift_date"],
        "shift_code": body["shift_code"],
        "shackle_capacity_birds": body["shackle_capacity_birds"],
        "labor_hours_budget": body["labor_hours_budget"],
        "shacklers_present": 0,
        "eviscerators_present": 0,
        "deboners_present": 0,
        "qa_techs_present": 0,
        "status": "SCHEDULED",
        "suspend_reason": "NONE",
        "process_water_gallons": 0,
        "chiller_water_gallons": 0,
        "birds_processed": 0,
        "chilled_weight_lb": 0,
        "water_rate_birds_basis": None,
        "water_rate_weight_basis": None,
        "water_breach_active": False,
        "chiller_limit_breached": False,
        "labor_hours_remaining": body["labor_hours_budget"],
        "started_at": None,
        "closed_at": None,
    })
    db.shifts[shift["id"]] = shift
    return success_object(serialize_shift(shift), 201)


@bp.route("/poultry/shifts/<shift_id>", methods=["GET"])
def get_shift(shift_id):
    require_roles(*ALL_ROLES)
    shift = db.shifts.get(shift_id)
    if not shift:
        raise ApiError(ERR_NOT_FOUND, "Shift not found", 404)
    # Breach flags evaluated lazily on reads
    recompute_shift_aggregates(shift)
    return success_object(serialize_shift(shift))


@bp.route("/poultry/shifts/<shift_id>/staffing", methods=["POST"])
def set_staffing(shift_id):
    require_roles("ShiftSupervisor")
    shift = db.shifts.get(shift_id)
    if not shift:
        raise ApiError(ERR_NOT_FOUND, "Shift not found", 404)
    body = get_json_body()
    check_no_unknown(
        body,
        {
            "shacklers_present", "eviscerators_present", "deboners_present",
            "qa_techs_present", "expected_shift_version",
        },
    )
    check_required(
        body,
        {
            "shacklers_present", "eviscerators_present", "deboners_present",
            "qa_techs_present", "expected_shift_version",
        },
    )
    for f in ("shacklers_present", "eviscerators_present", "deboners_present", "qa_techs_present"):
        check_int(body[f], f, min_value=0)
    check_int(body["expected_shift_version"], "expected_shift_version")

    # OCC first (priority 3.5)
    if body["expected_shift_version"] != shift["version"]:
        raise ApiError(
            ERR_STALE_SHIFT_VERSION,
            "expected_shift_version does not match the shift's current version",
            412,
        )

    if shift["status"] == "CLOSED":
        raise ApiError(ERR_SHIFT_TERMINAL, "Mutation attempted on a CLOSED shift", 409)

    shift["shacklers_present"] = body["shacklers_present"]
    shift["eviscerators_present"] = body["eviscerators_present"]
    shift["deboners_present"] = body["deboners_present"]
    shift["qa_techs_present"] = body["qa_techs_present"]
    _touch(shift)

    # Clamp running runs whose speed exceeds the new cap
    clamp_runs_for_shift(shift)

    return success_object(serialize_shift(shift))


@bp.route("/poultry/shifts/<shift_id>/transition", methods=["POST"])
def transition_shift(shift_id):
    user_id, role = require_roles("ShiftSupervisor", "QATechnician", "USDAInspector")
    shift = db.shifts.get(shift_id)
    if not shift:
        raise ApiError(ERR_NOT_FOUND, "Shift not found", 404)
    body = get_json_body()
    check_no_unknown(body, {"to_status", "reason_code", "resolution_note"})
    check_required(body, ["to_status"])
    check_enum(body["to_status"], ("RUNNING", "SUSPENDED", "CLOSED"), "to_status")
    to_status = body["to_status"]

    if shift["status"] == "CLOSED":
        raise ApiError(ERR_SHIFT_TERMINAL, "Mutation attempted on a CLOSED shift", 409)

    if to_status == "RUNNING":
        # Ambiguity pin: from a state that is neither SCHEDULED nor SUSPENDED,
        # resolution_note => resume attempt, else open attempt.
        if shift["status"] == "SCHEDULED":
            return _open_shift(shift, role)
        if shift["status"] == "SUSPENDED":
            return _resume_shift(shift, body, role)
        # Neither SCHEDULED nor SUSPENDED
        if "resolution_note" in body and body["resolution_note"] is not None:
            raise ApiError(
                ERR_SHIFT_NOT_SUSPENDED, "Resume attempted on a shift not in SUSPENDED", 409
            )
        raise ApiError(
            ERR_SHIFT_NOT_OPENABLE, "Open-production attempted on a shift not in SCHEDULED", 409
        )

    if to_status == "SUSPENDED":
        return _suspend_shift(shift, body, role)

    if to_status == "CLOSED":
        return _close_shift(shift, role)

    raise ApiError(ERR_INVALID_REQUEST, "Unsupported to_status", 400)


def _open_shift(shift, role):
    # Open requires ShiftSupervisor
    if role != "ShiftSupervisor":
        raise ApiError(ERR_INSUFFICIENT_PERMISSIONS, "Role not permitted to open a shift", 403)
    # Gate 1: from-state
    if shift["status"] != "SCHEDULED":
        raise ApiError(
            ERR_SHIFT_NOT_OPENABLE, "Open-production attempted on a shift not in SCHEDULED", 409
        )
    # Gate 2: at least one QUEUED run (checked FIRST among the gates)
    queued = [
        r for r in db.line_runs.values()
        if r["shift_id"] == shift["id"] and r["status"] == "QUEUED"
    ]
    if not queued:
        raise ApiError(ERR_NO_RUNS_QUEUED, "No QUEUED runs for this shift", 409)
    # Gate 3: every line referenced by a QUEUED run needs a VERIFIED sanitation run
    lines_needed = {r["line_id"] for r in queued}
    for line_id in lines_needed:
        verified = any(
            s for s in db.sanitation_runs.values()
            if s["shift_id"] == shift["id"] and s["line_id"] == line_id and s["status"] == "VERIFIED"
        )
        if not verified:
            raise ApiError(
                ERR_SANITATION_NOT_VERIFIED,
                "No VERIFIED sanitation run for (shift,line)",
                409,
            )
    # Gate 4: every such line needs a PASSED pre-op
    for line_id in lines_needed:
        passed = any(
            p for p in db.preop_inspections.values()
            if p["shift_id"] == shift["id"] and p["line_id"] == line_id and p["status"] == "PASSED"
        )
        if not passed:
            raise ApiError(
                ERR_PREOP_NOT_PASSED, "No PASSED pre-op inspection for (shift,line)", 409
            )

    shift["status"] = "RUNNING"
    shift["started_at"] = db.clock_now()
    _touch(shift)
    return success_object(serialize_shift(shift))


def _suspend_shift(shift, body, role):
    if role not in ("ShiftSupervisor", "QATechnician", "USDAInspector"):
        raise ApiError(ERR_INSUFFICIENT_PERMISSIONS, "Role not permitted to suspend", 403)
    if shift["status"] != "RUNNING":
        raise ApiError(
            ERR_SHIFT_NOT_RUNNING, "Suspension requires the shift in RUNNING", 409
        )
    reason_code = body.get("reason_code")
    if reason_code is None:
        raise ApiError(ERR_INVALID_REQUEST, "reason_code is required", 400)
    check_enum(reason_code, ("MANUAL", "REGULATORY_HOLD"), "reason_code")

    shift["status"] = "SUSPENDED"
    shift["suspend_reason"] = reason_code
    _touch(shift)

    # Cascade link 1: RUNNING runs -> PAUSED (auto_paused)
    for run in db.line_runs.values():
        if run["shift_id"] == shift["id"] and run["status"] == "RUNNING":
            run["status"] = "PAUSED"
            run["auto_paused"] = True
            _touch(run)
    # Cascade link 2: IN_PROGRESS batches -> ON_HOLD
    for b in db.deboning_batches.values():
        if b["shift_id"] == shift["id"] and b["status"] == "IN_PROGRESS":
            b["status"] = "ON_HOLD"
            _touch(b)

    return success_object(serialize_shift(shift))


def _resume_shift(shift, body, role):
    if role not in ("ShiftSupervisor", "QATechnician"):
        raise ApiError(ERR_INSUFFICIENT_PERMISSIONS, "Role not permitted to resume", 403)
    if shift["status"] != "SUSPENDED":
        raise ApiError(
            ERR_SHIFT_NOT_SUSPENDED, "Resume attempted on a shift not in SUSPENDED", 409
        )
    note = body.get("resolution_note")
    if not isinstance(note, str) or len(note) < 10:
        raise ApiError(
            ERR_INVALID_REQUEST, "resolution_note must be present and >= 10 chars", 400
        )
    if shift["suspend_reason"] == "WATER_LIMIT_BREACH" and role != "QATechnician":
        raise ApiError(
            ERR_INSUFFICIENT_PERMISSIONS,
            "Only a QATechnician may clear a water-limit breach",
            403,
        )

    shift["status"] = "RUNNING"
    shift["suspend_reason"] = "NONE"
    _touch(shift)

    for run in db.line_runs.values():
        if run["shift_id"] == shift["id"] and run["status"] == "PAUSED" and run["auto_paused"]:
            run["status"] = "RUNNING"
            run["auto_paused"] = False
            _touch(run)
    # ON_HOLD batches stay ON_HOLD by design.

    return success_object(serialize_shift(shift))


def _close_shift(shift, role):
    if role != "ShiftSupervisor":
        raise ApiError(ERR_INSUFFICIENT_PERMISSIONS, "Role not permitted to close", 403)
    if shift["status"] not in ("RUNNING", "SUSPENDED"):
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            "Close attempted from a state other than RUNNING or SUSPENDED",
            409,
        )
    active = any(
        r for r in db.line_runs.values()
        if r["shift_id"] == shift["id"] and r["status"] in ("RUNNING", "PAUSED")
    )
    if active:
        raise ApiError(
            ERR_RUNS_NOT_TERMINAL, "Shift close attempted while runs are RUNNING or PAUSED", 409
        )

    for run in db.line_runs.values():
        if run["shift_id"] == shift["id"] and run["status"] == "QUEUED":
            run["status"] = "CANCELLED"
            _touch(run)

    shift["status"] = "CLOSED"
    shift["closed_at"] = db.clock_now()
    shift["suspend_reason"] = "NONE"
    recompute_shift_aggregates(shift)
    _touch(shift)
    return success_object(serialize_shift(shift))


# --- Scoped lists ---

@bp.route("/poultry/shifts/<shift_id>/sanitation-runs", methods=["GET"])
def list_shift_sanitation(shift_id):
    require_roles(*ALL_ROLES)
    shift = db.shifts.get(shift_id)
    if not shift:
        raise ApiError(ERR_NOT_FOUND, "Shift not found", 404)
    items = [r for r in db.sanitation_runs.values() if r["shift_id"] == shift_id]
    items.sort(key=lambda r: r["created_at"])
    limit, offset = parse_pagination()
    page = items[offset:offset + limit]
    return success_list([serialize_sanitation_run(r) for r in page], limit, offset, len(items))


@bp.route("/poultry/shifts/<shift_id>/pre-op-inspections", methods=["GET"])
def list_shift_preops(shift_id):
    require_roles(*ALL_ROLES)
    shift = db.shifts.get(shift_id)
    if not shift:
        raise ApiError(ERR_NOT_FOUND, "Shift not found", 404)
    items = [p for p in db.preop_inspections.values() if p["shift_id"] == shift_id]
    items.sort(key=lambda p: p["created_at"])
    limit, offset = parse_pagination()
    page = items[offset:offset + limit]
    return success_list([serialize_preop(p) for p in page], limit, offset, len(items))


@bp.route("/poultry/shifts/<shift_id>/flock-lots", methods=["GET"])
def list_shift_lots(shift_id):
    require_roles(*ALL_ROLES)
    shift = db.shifts.get(shift_id)
    if not shift:
        raise ApiError(ERR_NOT_FOUND, "Shift not found", 404)
    items = [l for l in db.flock_lots.values() if l["receiving_shift_id"] == shift_id]
    items.sort(key=lambda l: l["created_at"])
    limit, offset = parse_pagination()
    page = items[offset:offset + limit]
    return success_list([serialize_flock_lot(l) for l in page], limit, offset, len(items))


@bp.route("/poultry/shifts/<shift_id>/utility-readings", methods=["GET"])
def list_shift_readings(shift_id):
    require_roles(*ALL_ROLES)
    shift = db.shifts.get(shift_id)
    if not shift:
        raise ApiError(ERR_NOT_FOUND, "Shift not found", 404)
    items = [r for r in db.utility_readings.values() if r["shift_id"] == shift_id]
    meter_type = None
    from flask import request
    meter_type = request.args.get("meter_type")
    if meter_type is not None:
        items = [r for r in items if r["meter_type"] == meter_type]
    items.sort(key=lambda r: r["created_at"])
    limit, offset = parse_pagination()
    page = items[offset:offset + limit]
    return success_list([serialize_utility_reading(r) for r in page], limit, offset, len(items))
