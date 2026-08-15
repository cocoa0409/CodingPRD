"""Sanitation runs and pre-op inspections."""

from flask import Blueprint

import db
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE_TRANSITION,
    ERR_SANITATION_NOT_VERIFIED,
    ERR_SOD_PREOP_SANITATION,
    ERR_INSUFFICIENT_PERMISSIONS,
)
from middleware import (
    require_roles,
    get_json_body,
    check_required,
    check_no_unknown,
    check_enum,
    check_string,
    parse_iso8601,
)
from response import success_object
from services.core import new_entity, _touch
from services.serializers import serialize_sanitation_run, serialize_preop

bp = Blueprint("sanitation", __name__)

ALL_ROLES = (
    "PlantManager", "ShiftSupervisor", "ReceivingClerk", "LineOperator",
    "QATechnician", "SanitationLead", "USDAInspector", "OrderPlanner",
)

# --------------------------- Sanitation runs ---------------------------

@bp.route("/poultry/sanitation-runs", methods=["POST"])
def create_sanitation_run():
    require_roles("SanitationLead")
    body = get_json_body()
    check_no_unknown(body, {"shift_id", "line_id", "window_start", "window_end"})
    check_required(body, ["shift_id", "line_id", "window_start", "window_end"])
    check_string(body["shift_id"], "shift_id")
    check_string(body["line_id"], "line_id")
    window_start = parse_iso8601(body["window_start"], "window_start")
    window_end = parse_iso8601(body["window_end"], "window_end")
    if window_start >= window_end:
        raise ApiError(
            ERR_INVALID_REQUEST, "window_start must be strictly earlier than window_end", 400
        )

    # Existence left-to-right
    shift = db.shifts.get(body["shift_id"])
    if not shift:
        raise ApiError(ERR_NOT_FOUND, "Shift not found", 404)
    line = db.lines.get(body["line_id"])
    if not line:
        raise ApiError(ERR_NOT_FOUND, "Line not found", 404)

    run = new_entity()
    run.update({
        "shift_id": shift["id"],
        "line_id": line["id"],
        "window_start": window_start,
        "window_end": window_end,
        "status": "SCHEDULED",
        "completer_user_id": None,
        "verifier_user_id": None,
    })
    db.sanitation_runs[run["id"]] = run
    return success_object(serialize_sanitation_run(run), 201)


@bp.route("/poultry/sanitation-runs/<run_id>", methods=["GET"])
def get_sanitation_run(run_id):
    require_roles(*ALL_ROLES)
    run = db.sanitation_runs.get(run_id)
    if not run:
        raise ApiError(ERR_NOT_FOUND, "Sanitation run not found", 404)
    return success_object(serialize_sanitation_run(run))


@bp.route("/poultry/sanitation-runs/<run_id>/advance", methods=["POST"])
def advance_sanitation_run(run_id):
    user_id, role = require_roles("SanitationLead", "QATechnician")
    run = db.sanitation_runs.get(run_id)
    if not run:
        raise ApiError(ERR_NOT_FOUND, "Sanitation run not found", 404)
    body = get_json_body()
    check_no_unknown(body, {"to_status"})
    check_required(body, ["to_status"])
    check_enum(
        body["to_status"],
        ("IN_PROGRESS", "COMPLETED", "VERIFIED", "FAILED_RECHECK"),
        "to_status",
    )
    to_status = body["to_status"]

    # Per-action role split
    if to_status in ("IN_PROGRESS", "COMPLETED") and role != "SanitationLead":
        raise ApiError(ERR_INSUFFICIENT_PERMISSIONS, "Role not permitted for this action", 403)
    if to_status in ("VERIFIED", "FAILED_RECHECK") and role != "QATechnician":
        raise ApiError(ERR_INSUFFICIENT_PERMISSIONS, "Role not permitted for this action", 403)

    if to_status == "IN_PROGRESS":
        if run["status"] == "SCHEDULED":
            _start_wash(run)
        elif run["status"] == "FAILED_RECHECK":
            _rewash(run)
        else:
            raise ApiError(
                ERR_INVALID_STATE_TRANSITION,
                "IN_PROGRESS not reachable from current state",
                409,
            )
    elif to_status == "COMPLETED":
        if run["status"] != "IN_PROGRESS":
            raise ApiError(
                ERR_INVALID_STATE_TRANSITION,
                "COMPLETED not reachable from current state",
                409,
            )
        run["status"] = "COMPLETED"
        run["completer_user_id"] = user_id
        _touch(run)
    elif to_status == "VERIFIED":
        if run["status"] != "COMPLETED":
            raise ApiError(
                ERR_INVALID_STATE_TRANSITION, "VERIFIED permitted only from COMPLETED", 409
            )
        run["status"] = "VERIFIED"
        run["verifier_user_id"] = user_id
        _touch(run)
    elif to_status == "FAILED_RECHECK":
        if run["status"] != "COMPLETED":
            raise ApiError(
                ERR_INVALID_STATE_TRANSITION,
                "FAILED_RECHECK permitted only from COMPLETED",
                409,
            )
        run["status"] = "FAILED_RECHECK"
        run["verifier_user_id"] = user_id
        _touch(run)

    return success_object(serialize_sanitation_run(run))


def _start_wash(run):
    """SCHEDULED -> IN_PROGRESS gate: shift SCHEDULED|SUSPENDED; no RUNNING line run."""
    shift = db.shifts.get(run["shift_id"])
    if not shift or shift["status"] not in ("SCHEDULED", "SUSPENDED"):
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            "Sanitation work may not begin during RUNNING production",
            409,
        )
    running = any(
        r for r in db.line_runs.values()
        if r["shift_id"] == run["shift_id"] and r["line_id"] == run["line_id"]
        and r["status"] == "RUNNING"
    )
    if running:
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            "A line run of this shift+line is RUNNING",
            409,
        )
    run["status"] = "IN_PROGRESS"
    _touch(run)


def _rewash(run):
    """FAILED_RECHECK -> IN_PROGRESS: shift must be SCHEDULED|SUSPENDED."""
    shift = db.shifts.get(run["shift_id"])
    if not shift or shift["status"] not in ("SCHEDULED", "SUSPENDED"):
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            "Re-wash may not begin during RUNNING production",
            409,
        )
    run["status"] = "IN_PROGRESS"
    _touch(run)


# --------------------------- Pre-op inspections ---------------------------

@bp.route("/poultry/pre-op-inspections", methods=["POST"])
def create_preop():
    require_roles("QATechnician")
    body = get_json_body()
    check_no_unknown(body, {"shift_id", "line_id"})
    check_required(body, ["shift_id", "line_id"])
    check_string(body["shift_id"], "shift_id")
    check_string(body["line_id"], "line_id")

    shift = db.shifts.get(body["shift_id"])
    if not shift:
        raise ApiError(ERR_NOT_FOUND, "Shift not found", 404)
    line = db.lines.get(body["line_id"])
    if not line:
        raise ApiError(ERR_NOT_FOUND, "Line not found", 404)

    insp = new_entity()
    insp.update({
        "shift_id": shift["id"],
        "line_id": line["id"],
        "status": "PENDING",
        "findings": None,
        "inspector_user_id": None,
        "cycle_count": 0,
    })
    db.preop_inspections[insp["id"]] = insp
    return success_object(serialize_preop(insp), 201)


@bp.route("/poultry/pre-op-inspections/<insp_id>", methods=["GET"])
def get_preop(insp_id):
    require_roles(*ALL_ROLES)
    insp = db.preop_inspections.get(insp_id)
    if not insp:
        raise ApiError(ERR_NOT_FOUND, "Pre-op inspection not found", 404)
    return success_object(serialize_preop(insp))


@bp.route("/poultry/pre-op-inspections/<insp_id>/advance", methods=["POST"])
def advance_preop(insp_id):
    user_id, role = require_roles("QATechnician", "SanitationLead")
    insp = db.preop_inspections.get(insp_id)
    if not insp:
        raise ApiError(ERR_NOT_FOUND, "Pre-op inspection not found", 404)
    body = get_json_body()
    check_no_unknown(body, {"to_status", "findings"})
    check_required(body, ["to_status"])
    check_enum(body["to_status"], ("PASSED", "FAILED", "CORRECTING", "PENDING"), "to_status")
    to_status = body["to_status"]

    # Per-action role split
    if to_status in ("PASSED", "FAILED", "PENDING") and role != "QATechnician":
        raise ApiError(ERR_INSUFFICIENT_PERMISSIONS, "Role not permitted for this action", 403)
    if to_status == "CORRECTING" and role not in ("SanitationLead", "QATechnician"):
        raise ApiError(ERR_INSUFFICIENT_PERMISSIONS, "Role not permitted for this action", 403)

    if to_status == "PASSED":
        if insp["status"] != "PENDING":
            raise ApiError(
                ERR_INVALID_STATE_TRANSITION, "PASSED permitted only from PENDING", 409
            )
        # Gate 1: a VERIFIED sanitation run must exist for (shift,line)
        verified = any(
            s for s in db.sanitation_runs.values()
            if s["shift_id"] == insp["shift_id"] and s["line_id"] == insp["line_id"]
            and s["status"] == "VERIFIED"
        )
        if not verified:
            raise ApiError(
                ERR_SANITATION_NOT_VERIFIED,
                "No VERIFIED sanitation run for (shift,line)",
                409,
            )
        # Gate 2: segregation of duties vs every COMPLETED-or-later sanitation run
        for s in db.sanitation_runs.values():
            if s["shift_id"] != insp["shift_id"] or s["line_id"] != insp["line_id"]:
                continue
            if s["status"] in ("COMPLETED", "VERIFIED", "FAILED_RECHECK"):
                if s.get("completer_user_id") and s["completer_user_id"] == user_id:
                    raise ApiError(
                        ERR_SOD_PREOP_SANITATION,
                        "Pre-op PASSED by the same user that completed sanitation",
                        403,
                    )
        insp["status"] = "PASSED"
        insp["inspector_user_id"] = user_id
        _touch(insp)
    elif to_status == "FAILED":
        if insp["status"] != "PENDING":
            raise ApiError(
                ERR_INVALID_STATE_TRANSITION, "FAILED permitted only from PENDING", 409
            )
        findings = body.get("findings")
        if not isinstance(findings, str) or not findings:
            raise ApiError(ERR_INVALID_REQUEST, "findings is required when failing", 400)
        insp["status"] = "FAILED"
        insp["findings"] = findings
        insp["inspector_user_id"] = user_id
        _touch(insp)
    elif to_status == "CORRECTING":
        if insp["status"] != "FAILED":
            raise ApiError(
                ERR_INVALID_STATE_TRANSITION, "CORRECTING permitted only from FAILED", 409
            )
        insp["status"] = "CORRECTING"
        _touch(insp)
    elif to_status == "PENDING":
        if insp["status"] != "CORRECTING":
            raise ApiError(
                ERR_INVALID_STATE_TRANSITION, "PENDING permitted only from CORRECTING", 409
            )
        insp["status"] = "PENDING"
        insp["cycle_count"] += 1
        _touch(insp)

    return success_object(serialize_preop(insp))
