"""HousekeepingProgram and HousekeepingAudit endpoints."""
from datetime import timedelta

from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_AUDIT_NOT_DUE,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_SOD_VIOLATION,
)
from middleware import require_roles
from response import success_object
from services import calculations as calc
from services.common import (
    auto_create_finding,
    get_flat_or_404,
    get_site_or_404,
    init_common,
    paginate,
    parse_body,
    parse_iso,
    require_fields,
    serialize,
    touch,
    validate_int,
    validate_number,
    validate_str,
)

bp = Blueprint("housekeeping", __name__)

READ_ROLES = ("ComplianceEngineer", "ComplianceManager", "HousekeepingAuditor", "InspectorUser")


def _get_program(site_id, program_id):
    site = get_site_or_404(site_id)
    program = db.housekeeping_programs.get(program_id)
    if program is None or program["site_id"] != site["id"]:
        raise ApiError(ERR_NOT_FOUND, f"HousekeepingProgram {program_id} not found", 404)
    return site, program


def _get_audit(site_id, program_id, audit_id):
    site, program = _get_program(site_id, program_id)
    audit = db.housekeeping_audits.get(audit_id)
    if audit is None or audit["program_id"] != program["id"]:
        raise ApiError(ERR_NOT_FOUND, f"HousekeepingAudit {audit_id} not found", 404)
    return site, program, audit


@bp.route("/api/sites/<id>/housekeeping-programs", methods=["POST"])
def create_program(id):
    user_id, _ = require_roles("ComplianceEngineer", "ComplianceManager")
    site = get_site_or_404(id)
    body = parse_body()
    require_fields(body, ["name", "target_accumulation_g_per_m2", "frequency_hours"])
    validate_str(body, "name")
    validate_number(body, "target_accumulation_g_per_m2", gt=0)
    validate_int(body, "frequency_hours", gt=0)

    program = {
        "site_id": site["id"],
        "name": body["name"],
        "target_accumulation_g_per_m2": body["target_accumulation_g_per_m2"],
        "frequency_hours": body["frequency_hours"],
        "last_audit_at": None,
        "last_audit_at_dt": None,
        "next_due_at": None,
        "next_due_at_dt": None,
        "current_posture": "CURRENT",
        "created_by": user_id,
    }
    init_common(program)
    calc.housekeeping_schedule(program)
    db.housekeeping_programs[program["id"]] = program
    return success_object(serialize(program), 201)


@bp.route("/api/sites/<id>/housekeeping-programs", methods=["GET"])
def list_programs(id):
    require_roles(*READ_ROLES)
    site = get_site_or_404(id)
    items = [p for p in db.housekeeping_programs.values() if p["site_id"] == site["id"]]
    filters = {}
    if request.args.get("current_posture") is not None:
        filters["current_posture"] = "current_posture"
    return paginate(items, filters)


@bp.route("/api/sites/<id>/housekeeping-programs/<program_id>", methods=["GET"])
def get_program(id, program_id):
    require_roles(*READ_ROLES)
    _, program = _get_program(id, program_id)
    return success_object(serialize(program), 200)


@bp.route("/api/sites/<id>/housekeeping-programs/<program_id>/audits", methods=["POST"])
def create_audit(id, program_id):
    require_roles("HousekeepingAuditor")
    site, program = _get_program(id, program_id)
    body = parse_body()
    require_fields(body, ["auditor_id", "measured_accumulation_g_per_m2", "scheduled_for"])
    validate_str(body, "auditor_id")
    validate_number(body, "measured_accumulation_g_per_m2", ge=0)
    scheduled = parse_iso(body["scheduled_for"], "scheduled_for")

    audit = {
        "program_id": program["id"],
        "auditor_id": body["auditor_id"],
        "measured_accumulation_g_per_m2": body["measured_accumulation_g_per_m2"],
        "pass_threshold_g_per_m2": program["target_accumulation_g_per_m2"],
        "pass": None,
        "scheduled_for": db.iso(scheduled),
        "scheduled_for_dt": scheduled,
        "executed_at": None,
        "executed_at_dt": None,
        "status": "SCHEDULED",
    }
    init_common(audit)
    db.housekeeping_audits[audit["id"]] = audit
    return success_object(serialize(audit), 201)


@bp.route("/api/sites/<id>/housekeeping-programs/<program_id>/audits", methods=["GET"])
def list_audits(id, program_id):
    require_roles(*READ_ROLES)
    site, program = _get_program(id, program_id)
    items = [a for a in db.housekeeping_audits.values() if a["program_id"] == program["id"]]
    filters = {}
    if request.args.get("status") is not None:
        filters["status"] = "status"
    return paginate(items, filters)


@bp.route("/api/sites/<id>/housekeeping-programs/<program_id>/audits/<audit_id>", methods=["GET"])
def get_audit(id, program_id, audit_id):
    require_roles(*READ_ROLES)
    _, _, audit = _get_audit(id, program_id, audit_id)
    return success_object(serialize(audit), 200)


def _record_common(site, program, audit):
    """Apply the RECORDED side-effects shared by SCHEDULED->RECORDED and
    OVERDUE->RECORDED."""
    now = db.now_dt()
    audit["executed_at_dt"] = now
    audit["executed_at"] = db.iso(now)
    audit["pass"] = bool(
        float(audit["measured_accumulation_g_per_m2"]) <= float(audit["pass_threshold_g_per_m2"])
    )
    audit["status"] = "RECORDED"
    touch(audit)

    program["last_audit_at_dt"] = now
    program["last_audit_at"] = db.iso(now)
    program["next_due_at_dt"] = now + timedelta(hours=program["frequency_hours"])
    program["next_due_at"] = db.iso(program["next_due_at_dt"])
    calc.housekeeping_schedule(program)
    touch(program)

    if audit["pass"] is False:
        auto_create_finding(site, "MAJOR", None, "Housekeeping audit failed")

    calc.site_posture_derivation(site)
    touch(site)


@bp.route("/api/sites/<id>/housekeeping-programs/<program_id>/audits/<audit_id>/record", methods=["POST"])
def record_audit(id, program_id, audit_id):
    user_id, _ = require_roles("HousekeepingAuditor")
    site, program, audit = _get_audit(id, program_id, audit_id)

    if audit["status"] not in ("SCHEDULED", "OVERDUE"):
        raise ApiError(ERR_INVALID_STATE, "Audit cannot be recorded from its current state", 409)
    if audit["auditor_id"] != user_id:
        raise ApiError(ERR_SOD_VIOLATION, "Only the assigned auditor may record this audit", 422)

    if audit["status"] == "SCHEDULED":
        sched = audit.get("scheduled_for_dt")
        if sched is not None and sched > db.now_dt():
            raise ApiError(ERR_AUDIT_NOT_DUE, "Audit is not yet due", 422)

    was_overdue = audit["status"] == "OVERDUE"
    _record_common(site, program, audit)
    if was_overdue:
        calc.recompute_open_overdue_housekeeping(site)
        calc.site_posture_derivation(site)
        touch(site)
    return success_object(serialize(audit), 200)


@bp.route("/api/sites/<id>/housekeeping-programs/<program_id>/audits/<audit_id>/skip", methods=["POST"])
def skip_audit(id, program_id, audit_id):
    user_id, _ = require_roles("HousekeepingAuditor")
    site, program, audit = _get_audit(id, program_id, audit_id)
    if audit["status"] != "SCHEDULED":
        raise ApiError(ERR_INVALID_STATE, "Only SCHEDULED audits can be skipped", 409)
    if audit["auditor_id"] != user_id:
        raise ApiError(ERR_SOD_VIOLATION, "Only the assigned auditor may skip this audit", 422)
    audit["status"] = "SKIPPED"
    touch(audit)
    return success_object(serialize(audit), 200)


# ----- Flat endpoints -----
@bp.route("/api/housekeeping-programs/<id>", methods=["GET"])
def get_program_flat(id):
    require_roles(*READ_ROLES)
    program = get_flat_or_404(db.housekeeping_programs, id, "HousekeepingProgram")
    return success_object(serialize(program), 200)


@bp.route("/api/housekeeping-programs/<id>/audits", methods=["GET"])
def list_program_audits_flat(id):
    require_roles(*READ_ROLES)
    program = get_flat_or_404(db.housekeeping_programs, id, "HousekeepingProgram")
    items = [a for a in db.housekeeping_audits.values() if a["program_id"] == program["id"]]
    return paginate(items)
