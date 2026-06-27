"""MaintenancePlan + MaintenanceVisit routes."""
from datetime import timedelta

from flask import Blueprint, request

import calc
import db
import posture
from auth import get_principal, require_roles
from clock import get_now
from errors import err
from response import success
from serialize import out
from timeutil import parse
from validate import get_body, opt_number, opt_str, require_enum, require_str
from routes.common import customer_owns, find_or_404, render_list

bp = Blueprint("maintenance", __name__)


# ---- Plan create -----------------------------------------------------------
@bp.route("/units/<unit_id>/maintenance-plans", methods=["POST"])
def create_plan(unit_id):
    principal = get_principal()
    require_roles(principal, {"Customer", "ServiceManager"})
    unit = find_or_404(db.units, unit_id)
    body = get_body()
    frequency = require_enum(body, "frequency", {"ANNUAL", "SEMI_ANNUAL"})
    monitoring_bundled = bool_opt(body, "monitoring_bundled")

    # Ownership (priority 6) after body well-formedness.
    customer_owns(principal, unit["customer_id"])

    # NON_COMPLIANT gate (priority 9)
    if unit["operating_status"] == "NON_COMPLIANT":
        raise err("ERR_UNIT_NON_COMPLIANT", "Unit is NON_COMPLIANT")

    annual_price, visits_per_year = calc.run_plan_price(unit["rated_kw"], frequency, monitoring_bundled)

    rec = db.base_record(full_common=True)
    rec.update({
        "unit_id": unit_id,
        "frequency": frequency,
        "monitoring_bundled": monitoring_bundled,
        "status": "ACTIVE",
        "annual_price_cents": annual_price,
        "visits_per_year": visits_per_year,
        "visits_completed_ytd": 0,
        "next_due_at": None,
    })
    db.maintenance_plans[rec["id"]] = rec
    posture.recompute_plan_due(rec)
    posture.recompute_unit_posture(unit)
    return success(out(rec), status=201)


def bool_opt(body, field, default=False):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, bool):
        raise err("ERR_INVALID_REQUEST", f"{field} must be a boolean")
    return v


@bp.route("/maintenance-plans", methods=["GET"])
def list_plans():
    principal = get_principal()
    require_roles(principal, {"Customer", "ServiceManager", "ComplianceOfficer"})
    records = list(db.maintenance_plans.values())
    if "unit_id" in request.args:
        records = [r for r in records if r["unit_id"] == request.args.get("unit_id")]
    return render_list(records)


@bp.route("/maintenance-plans/<plan_id>", methods=["GET"])
def get_plan(plan_id):
    principal = get_principal()
    require_roles(principal, {"Customer", "Technician", "ServiceManager", "ComplianceOfficer"})
    rec = find_or_404(db.maintenance_plans, plan_id)
    return success(out(rec), status=200)


# ---- Plan suspend/resume/cancel -------------------------------------------
@bp.route("/maintenance-plans/<plan_id>/suspend", methods=["POST"])
def suspend_plan(plan_id):
    principal = get_principal()
    require_roles(principal, {"Customer", "ServiceManager"})
    plan = find_or_404(db.maintenance_plans, plan_id)
    unit = db.units.get(plan["unit_id"])
    customer_owns(principal, unit["customer_id"])
    if plan["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Plan must be ACTIVE to suspend")
    plan["status"] = "SUSPENDED"  # next_due_at frozen
    db.touch(plan)
    posture.recompute_unit_posture(unit)
    return success(out(plan), status=200)


@bp.route("/maintenance-plans/<plan_id>/resume", methods=["POST"])
def resume_plan(plan_id):
    principal = get_principal()
    require_roles(principal, {"Customer", "ServiceManager"})
    plan = find_or_404(db.maintenance_plans, plan_id)
    unit = db.units.get(plan["unit_id"])
    customer_owns(principal, unit["customer_id"])
    if plan["status"] != "SUSPENDED":
        raise err("ERR_INVALID_STATE", "Plan must be SUSPENDED to resume")
    if unit["operating_status"] == "DECOMMISSIONED":
        raise err("ERR_INVALID_STATE", "Owning unit is decommissioned")
    plan["status"] = "ACTIVE"
    posture.recompute_plan_due(plan)
    db.touch(plan)
    posture.recompute_unit_posture(unit)
    return success(out(plan), status=200)


@bp.route("/maintenance-plans/<plan_id>/cancel", methods=["POST"])
def cancel_plan(plan_id):
    principal = get_principal()
    require_roles(principal, {"Customer", "ServiceManager"})
    plan = find_or_404(db.maintenance_plans, plan_id)
    unit = db.units.get(plan["unit_id"])
    customer_owns(principal, unit["customer_id"])
    if plan["status"] == "CANCELLED":
        raise err("ERR_INVALID_STATE", "Plan already cancelled")
    plan["status"] = "CANCELLED"
    for visit in db.maintenance_visits.values():
        if visit["plan_id"] == plan_id and visit["status"] == "SCHEDULED":
            visit["status"] = "CANCELLED"
            db.touch(visit)
    db.touch(plan)
    posture.recompute_unit_posture(unit)
    return success(out(plan), status=200)


# ---- Visit scheduling ------------------------------------------------------
@bp.route("/maintenance-plans/<plan_id>/visits", methods=["POST"])
def schedule_visit(plan_id):
    principal = get_principal()
    require_roles(principal, {"Customer", "ServiceManager"})
    plan = find_or_404(db.maintenance_plans, plan_id)
    unit = db.units.get(plan["unit_id"])
    body = get_body()
    assigned_tech_id = opt_str(body, "assigned_tech_id", default=None)
    if assigned_tech_id is not None:
        # FK reference resolution (priority 4)
        if assigned_tech_id not in db.technicians:
            raise err("ERR_REFERENCE_NOT_FOUND", "assigned_tech_id not found")
    scheduled_for = require_str(body, "scheduled_for")
    try:
        sched_dt = parse(scheduled_for)
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST", "scheduled_for is not a valid ISO8601 instant")

    # Ownership (priority 6) after body/FK checks.
    customer_owns(principal, unit["customer_id"])

    # Collision 1: unit same UTC calendar day (priority 18)
    sched_date = sched_dt.date()
    for v in db.maintenance_visits.values():
        if v["unit_id"] == plan["unit_id"] and v["status"] == "SCHEDULED":
            other = parse(v["scheduled_for"])
            if other is not None and other.date() == sched_date:
                raise err("ERR_UNIT_VISIT_COLLISION", "Unit already has a visit on this UTC day")

    # Collision 2: tech double-booked within 4h half-open window (priority 17)
    if assigned_tech_id is not None:
        buf = timedelta(hours=calc.VISIT_BUFFER_HOURS)
        for v in db.maintenance_visits.values():
            if v["status"] != "SCHEDULED" or v.get("assigned_tech_id") != assigned_tech_id:
                continue
            other = parse(v["scheduled_for"])
            if other is None:
                continue
            # reject if new lies in [other - 4h, other + 4h)
            if (other - buf) <= sched_dt < (other + buf):
                raise err("ERR_TECH_DOUBLE_BOOKED", "Technician double-booked within buffer")

    rec = db.base_record(full_common=True)
    rec.update({
        "plan_id": plan_id,
        "unit_id": plan["unit_id"],
        "scheduled_for": scheduled_for,
        "assigned_tech_id": assigned_tech_id,
        "status": "SCHEDULED",
        "performed_at": None,
        "runtime_added_hours": 0,
    })
    db.maintenance_visits[rec["id"]] = rec
    return success(out(rec), status=201)


@bp.route("/maintenance-plans/<plan_id>/visits", methods=["GET"])
def list_plan_visits(plan_id):
    principal = get_principal()
    require_roles(principal, {"Customer", "Technician", "ServiceManager", "ComplianceOfficer"})
    find_or_404(db.maintenance_plans, plan_id)
    records = [v for v in db.maintenance_visits.values() if v["plan_id"] == plan_id]
    return render_list(records)


@bp.route("/maintenance-visits", methods=["GET"])
def list_visits():
    principal = get_principal()
    require_roles(principal, {"Customer", "Technician", "ServiceManager", "ComplianceOfficer"})
    records = list(db.maintenance_visits.values())
    for f in ("plan_id", "unit_id", "assigned_tech_id"):
        if f in request.args:
            val = request.args.get(f)
            records = [r for r in records if r.get(f) == val]
    return render_list(records)


@bp.route("/maintenance-visits/<visit_id>", methods=["GET"])
def get_visit(visit_id):
    principal = get_principal()
    require_roles(principal, {"Customer", "Technician", "ServiceManager", "ComplianceOfficer"})
    rec = find_or_404(db.maintenance_visits, visit_id)
    return success(out(rec), status=200)


# ---- Visit complete / cancel ----------------------------------------------
@bp.route("/maintenance-visits/<visit_id>/complete", methods=["POST"])
def complete_visit(visit_id):
    principal = get_principal()
    require_roles(principal, {"Technician"})
    visit = find_or_404(db.maintenance_visits, visit_id)
    body = get_body()
    runtime_added_hours = opt_number(body, "runtime_added_hours", default=0, ge=0)

    # ownership: acting tech must be the assigned tech
    if principal.user_id != visit.get("assigned_tech_id"):
        raise err("ERR_NOT_ASSIGNED_TECH", "Acting technician is not assigned to this visit")

    if visit["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Visit must be SCHEDULED to complete")

    plan = db.maintenance_plans.get(visit["plan_id"])
    unit = db.units.get(visit["unit_id"])
    if plan["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Owning plan must be ACTIVE")
    if unit["operating_status"] == "DECOMMISSIONED":
        raise err("ERR_INVALID_STATE", "Owning unit is decommissioned")
    if unit["operating_status"] == "NON_COMPLIANT":
        raise err("ERR_UNIT_NON_COMPLIANT", "Unit is NON_COMPLIANT")

    visit["status"] = "COMPLETED"
    visit["performed_at"] = db.now_iso()
    visit["runtime_added_hours"] = runtime_added_hours
    db.touch(visit)

    unit["runtime_hours"] += runtime_added_hours
    plan["visits_completed_ytd"] += 1
    posture.recompute_plan_due(plan)
    db.touch(plan)
    posture.recompute_unit_posture(unit)
    return success(out(visit), status=200)


@bp.route("/maintenance-visits/<visit_id>/cancel", methods=["POST"])
def cancel_visit(visit_id):
    principal = get_principal()
    require_roles(principal, {"Customer", "ServiceManager"})
    visit = find_or_404(db.maintenance_visits, visit_id)
    unit = db.units.get(visit["unit_id"])
    customer_owns(principal, unit["customer_id"])
    if visit["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Visit must be SCHEDULED to cancel")
    visit["status"] = "CANCELLED"
    db.touch(visit)
    return success(out(visit), status=200)


def opt_number(body, field, default=None, ge=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err("ERR_INVALID_REQUEST", f"{field} must be a number")
    if ge is not None and not v >= ge:
        raise err("ERR_INVALID_REQUEST", f"{field} must be >= {ge}")
    return v
