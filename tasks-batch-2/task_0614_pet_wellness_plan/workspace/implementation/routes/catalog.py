"""Plan / PlanService / Clinic catalogue endpoints (PRD §3.1)."""
from flask import Blueprint

from db import db
from errors import err, ERR_REFERENCE_NOT_FOUND, ERR_INVALID_STATE
from middleware import authenticate, require_role
from response import success, list_success
from common import (
    parse_pagination, paginate, sort_by_created, get_json, stamp_new, touch,
    public, require_str, require_int, require_number, require_enum,
)
from lookup import get_or_404
from flask import request

bp = Blueprint("catalog", __name__)

ALL_ROLES = {"PlanAdmin", "Member", "ClinicStaff", "BillingAdmin"}
PLAN_TIERS = {"ESSENTIAL", "PLUS", "PREMIUM"}
SERVICE_CODES = {"EXAM", "VACCINE", "DENTAL"}


# --------------------------------------------------------------------------
# Plans
# --------------------------------------------------------------------------
@bp.post("/wellness/plans")
def create_plan():
    _, role = authenticate()
    require_role(role, {"PlanAdmin"})
    body = get_json()
    tier = require_enum(body, "tier", PLAN_TIERS)
    name = require_str(body, "name")
    monthly_fee = require_int(body, "monthly_fee_cents", minimum=0)
    annual_value = require_int(body, "annual_value_cents", minimum=0)
    discount = require_number(body, "alacarte_discount_pct", ge=0.0, le=0.5,
                              required=False, default=0.0)
    enrollment_fee = require_int(body, "enrollment_fee_cents", minimum=0,
                                 required=False, default=0)
    plan = {
        "tier": tier,
        "name": name,
        "monthly_fee_cents": monthly_fee,
        "annual_value_cents": annual_value,
        "alacarte_discount_pct": discount,
        "enrollment_fee_cents": enrollment_fee,
        "status": "ACTIVE",
    }
    stamp_new(plan)
    db.plans[plan["id"]] = plan
    return success(public(plan), 201)


@bp.get("/wellness/plans")
def list_plans():
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    limit, offset = parse_pagination()
    rows = list(db.plans.values())
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    tier = request.args.get("tier")
    if tier is not None:
        rows = [r for r in rows if r["tier"] == tier]
    rows = sort_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return list_success([public(r) for r in page], limit, offset, total)


@bp.get("/wellness/plans/<pid>")
def get_plan(pid):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    plan = get_or_404(db.plans, pid)
    return success(public(plan))


@bp.post("/wellness/plans/<pid>/retire")
def retire_plan(pid):
    _, role = authenticate()
    require_role(role, {"PlanAdmin"})
    plan = get_or_404(db.plans, pid)
    if plan["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Plan is not ACTIVE")
    plan["status"] = "RETIRED"
    touch(plan)
    return success(public(plan))


# --------------------------------------------------------------------------
# PlanService inclusion lines
# --------------------------------------------------------------------------
@bp.post("/wellness/plan-services")
def create_plan_service():
    _, role = authenticate()
    require_role(role, {"PlanAdmin"})
    body = get_json()
    plan_id = require_str(body, "plan_id")
    service_code = require_enum(body, "service_code", SERVICE_CODES)
    included_quantity = require_int(body, "included_quantity", minimum=0)
    unit_value = require_int(body, "unit_value_cents", minimum=1)
    if plan_id not in db.plans:
        raise err(ERR_REFERENCE_NOT_FOUND, "Referenced plan does not exist")
    ps = {
        "plan_id": plan_id,
        "service_code": service_code,
        "included_quantity": included_quantity,
        "unit_value_cents": unit_value,
        "status": "ACTIVE",
    }
    stamp_new(ps)
    db.plan_services[ps["id"]] = ps
    return success(public(ps), 201)


@bp.get("/wellness/plan-services")
def list_plan_services():
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    limit, offset = parse_pagination()
    rows = list(db.plan_services.values())
    for f in ("plan_id", "service_code", "status"):
        v = request.args.get(f)
        if v is not None:
            rows = [r for r in rows if r[f] == v]
    rows = sort_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return list_success([public(r) for r in page], limit, offset, total)


@bp.get("/wellness/plan-services/<sid>")
def get_plan_service(sid):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    ps = get_or_404(db.plan_services, sid)
    return success(public(ps))


@bp.post("/wellness/plan-services/<sid>/retire")
def retire_plan_service(sid):
    _, role = authenticate()
    require_role(role, {"PlanAdmin"})
    ps = get_or_404(db.plan_services, sid)
    if ps["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Inclusion line is not ACTIVE")
    ps["status"] = "RETIRED"
    touch(ps)
    return success(public(ps))


# --------------------------------------------------------------------------
# Clinics
# --------------------------------------------------------------------------
@bp.post("/wellness/clinics")
def create_clinic():
    _, role = authenticate()
    require_role(role, {"PlanAdmin"})
    body = get_json()
    name = require_str(body, "name")
    region_code = require_str(body, "region_code")
    clinic = {
        "name": name,
        "region_code": region_code,
        "status": "OPEN",
    }
    stamp_new(clinic)
    db.clinics[clinic["id"]] = clinic
    return success(public(clinic), 201)


@bp.get("/wellness/clinics")
def list_clinics():
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    limit, offset = parse_pagination()
    rows = list(db.clinics.values())
    for f in ("status", "region_code"):
        v = request.args.get(f)
        if v is not None:
            rows = [r for r in rows if r[f] == v]
    rows = sort_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return list_success([public(r) for r in page], limit, offset, total)


@bp.get("/wellness/clinics/<cid>")
def get_clinic(cid):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    clinic = get_or_404(db.clinics, cid)
    return success(public(clinic))


@bp.post("/wellness/clinics/<cid>/close")
def close_clinic(cid):
    _, role = authenticate()
    require_role(role, {"PlanAdmin"})
    clinic = get_or_404(db.clinics, cid)
    if clinic["status"] != "OPEN":
        raise err(ERR_INVALID_STATE, "Clinic is not OPEN")
    clinic["status"] = "CLOSED"
    touch(clinic)
    return success(public(clinic))
