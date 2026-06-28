"""Unit routes: get/list/patch/decommission + exercise logs + child lists."""
from flask import Blueprint, request

import calc
import db
import posture
from auth import get_principal, require_roles
from clock import get_now, parse_iso8601
from errors import err
from response import success
from serialize import out
from validate import get_body, opt_bool, opt_int, require_enum, require_str
from routes.common import customer_owns, find_or_404, render_list

bp = Blueprint("units", __name__)


@bp.route("/units", methods=["GET"])
def list_units():
    principal = get_principal()
    require_roles(principal, {"Customer", "ServiceManager", "ComplianceOfficer"})
    records = list(db.units.values())
    for f in ("customer_id", "model_id", "project_id"):
        if f in request.args:
            val = request.args.get(f)
            records = [r for r in records if r.get(f) == val]
    return render_list(records)


@bp.route("/units/<unit_id>", methods=["GET"])
def get_unit(unit_id):
    principal = get_principal()
    require_roles(principal, {"Customer", "Technician", "ServiceManager", "ComplianceOfficer"})
    rec = find_or_404(db.units, unit_id)
    return success(out(rec), status=200)


@bp.route("/units/<unit_id>", methods=["PATCH"])
def patch_unit(unit_id):
    principal = get_principal()
    require_roles(principal, {"Customer", "ServiceManager"})
    unit = find_or_404(db.units, unit_id)
    body = get_body()

    register = opt_bool(body, "register", default=False)
    has_monitoring = "monitoring_enabled" in body and body["monitoring_enabled"] is not None
    monitoring_enabled = opt_bool(body, "monitoring_enabled", default=unit["monitoring_enabled"])

    # Ownership (priority 6) after body well-formedness.
    customer_owns(principal, unit["customer_id"])

    if has_monitoring:
        unit["monitoring_enabled"] = monitoring_enabled
    if register:
        if unit["registration_status"] != "REGISTERED":
            unit["registration_status"] = "REGISTERED"
            unit["warranty_total_months"] += calc.REGISTRATION_BONUS_MONTHS

    # Recompute monitoring_health (and warranty/posture) then bump version.
    # Recompute alone may or may not change derived state, but a PATCH always
    # bumps version per the endpoint contract.
    _recompute_inline(unit)
    db.touch(unit)
    return success(out(unit), status=200)


def _recompute_inline(unit):
    """Recompute derived fields without an extra version bump (caller bumps)."""
    if unit["operating_status"] == "DECOMMISSIONED":
        unit["monitoring_health"] = "OFFLINE"
        return
    posture.recompute_compliance(unit)
    if posture.unit_has_overdue_mandatory(unit["id"]):
        unit["operating_status"] = "NON_COMPLIANT"
        unit["warranty_status"] = "VOID"
        unit["monitoring_health"] = "OFFLINE"
    else:
        unit["warranty_status"] = "ACTIVE" if posture.within_warranty_window(unit) else "LAPSED"
        unit["operating_status"] = "SERVICE_DUE" if posture.has_due_active_plan(unit["id"]) else "OPERATIONAL"
        posture.recompute_monitoring(unit)


@bp.route("/units/<unit_id>/decommission", methods=["POST"])
def decommission_unit(unit_id):
    principal = get_principal()
    require_roles(principal, {"ServiceManager"})
    unit = find_or_404(db.units, unit_id)

    if unit["operating_status"] == "DECOMMISSIONED":
        raise err("ERR_INVALID_STATE", "Unit already decommissioned")

    # blocking in-flight dispatch
    for d in db.repair_dispatches.values():
        if d["unit_id"] == unit_id and d["status"] in ("DISPATCHED", "IN_PROGRESS"):
            raise err("ERR_DISPATCH_IN_PROGRESS", "An in-flight dispatch blocks decommission")

    # cascade: ACTIVE/SUSPENDED plans -> CANCELLED, their SCHEDULED visits -> CANCELLED
    for plan in db.maintenance_plans.values():
        if plan["unit_id"] != unit_id:
            continue
        if plan["status"] in ("ACTIVE", "SUSPENDED"):
            plan["status"] = "CANCELLED"
            db.touch(plan)
    for visit in db.maintenance_visits.values():
        if visit["unit_id"] == unit_id and visit["status"] == "SCHEDULED":
            visit["status"] = "CANCELLED"
            db.touch(visit)

    unit["operating_status"] = "DECOMMISSIONED"
    unit["monitoring_enabled"] = False
    unit["monitoring_health"] = "OFFLINE"
    db.touch(unit)
    return success(out(unit), status=200)


# ---- Exercise logs ---------------------------------------------------------
@bp.route("/units/<unit_id>/exercise-logs", methods=["POST"])
def create_exercise_log(unit_id):
    principal = get_principal()
    require_roles(principal, {"Customer", "ServiceManager"})
    unit = find_or_404(db.units, unit_id)
    body = get_body()

    occurred_at = require_str(body, "occurred_at")
    try:
        parse_iso8601(occurred_at)
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST", "occurred_at is not a valid ISO8601 instant")
    result = require_enum(body, "result", {"SUCCESS", "FAULT"})
    runtime_minutes = opt_int(body, "runtime_minutes", default=12, minimum=0)

    # Ownership (priority 6) after body well-formedness.
    customer_owns(principal, unit["customer_id"])

    rec = db.base_record(full_common=False)
    rec.update({
        "unit_id": unit_id,
        "occurred_at": occurred_at,
        "result": result,
        "runtime_minutes": runtime_minutes,
    })
    db.exercise_logs[rec["id"]] = rec

    # recompute compliance then monitoring & operating status
    posture.recompute_unit_posture(unit)
    return success(out(rec), status=201)


@bp.route("/units/<unit_id>/exercise-logs", methods=["GET"])
def list_exercise_logs(unit_id):
    principal = get_principal()
    require_roles(principal, {"Customer", "ServiceManager", "ComplianceOfficer"})
    find_or_404(db.units, unit_id)
    records = [e for e in db.exercise_logs.values() if e["unit_id"] == unit_id]
    return render_list(records)


# ---- Unit-scoped child collection lists ------------------------------------
@bp.route("/units/<unit_id>/maintenance-plans", methods=["GET"])
def list_unit_plans(unit_id):
    principal = get_principal()
    require_roles(principal, {"Customer", "ServiceManager", "ComplianceOfficer"})
    find_or_404(db.units, unit_id)
    records = [p for p in db.maintenance_plans.values() if p["unit_id"] == unit_id]
    return render_list(records)


@bp.route("/units/<unit_id>/warranty-claims", methods=["GET"])
def list_unit_claims(unit_id):
    principal = get_principal()
    require_roles(principal, {"Customer", "ServiceManager", "ComplianceOfficer"})
    find_or_404(db.units, unit_id)
    records = [c for c in db.warranty_claims.values() if c["unit_id"] == unit_id]
    return render_list(records)


@bp.route("/units/<unit_id>/repair-dispatches", methods=["GET"])
def list_unit_dispatches(unit_id):
    principal = get_principal()
    require_roles(principal, {"Customer", "Technician", "ServiceManager", "ComplianceOfficer"})
    find_or_404(db.units, unit_id)
    records = [d for d in db.repair_dispatches.values() if d["unit_id"] == unit_id]
    return render_list(records)


@bp.route("/units/<unit_id>/remediations", methods=["GET"])
def list_unit_remediations(unit_id):
    principal = get_principal()
    require_roles(principal, {"ServiceManager", "ComplianceOfficer"})
    find_or_404(db.units, unit_id)
    records = [r for r in db.recall_remediations.values() if r["unit_id"] == unit_id]
    return render_list(records)
