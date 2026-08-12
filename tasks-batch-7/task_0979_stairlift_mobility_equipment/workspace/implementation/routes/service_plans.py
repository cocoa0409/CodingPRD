"""ServicePlan endpoints."""

from datetime import timedelta

from flask import Blueprint

import db
from errors import (err_not_found, err_invalid_request, err_invalid_state)
from middleware import require_role, get_json_body, get_pagination
from response import success_object, success_list
from services.core import stamp_new, touch, serialize, audit
from services.calculations import service_plan_fee, TIER_CAP_CENTS
from services.sweeps import SERVICE_INTERVAL_DAYS

bp = Blueprint("service_plans", __name__)

READ_ROLES = ("PlatformAdmin", "InstallCoordinator", "SalesRep",
              "ClaimsAdjuster")


@bp.post("/stairlift-ops/agreements/<aid>/service-plans")
def create_service_plan(aid):
    user_id, role = require_role("InstallCoordinator", "SalesRep")
    ag = db.agreements.get(aid)
    if ag is None:
        raise err_not_found("Agreement not found")
    if ag["status"] != "INSTALLED":
        raise err_invalid_state("Agreement must be INSTALLED to attach a plan")
    body = get_json_body(["tier"])
    tier = body["tier"]
    if tier not in ("BASIC", "STANDARD", "PREMIUM"):
        raise err_invalid_request("tier invalid")
    quote = db.quotes.get(ag["quote_id"])
    assessment = db.home_assessments.get(quote["home_assessment_id"]) \
        if quote else None
    unit = db.equipment_units.get(ag.get("equipment_unit_id"))
    fee = service_plan_fee(
        tier,
        bool(assessment and assessment.get("has_outdoor_exposure")),
        assessment["staircase_kind"] if assessment else "STRAIGHT",
        unit["condition_grade"] if unit else "NEW",
        bool(ag.get("liability_waiver_signed")),
    )
    sp = {
        "agreement_id": aid,
        "tier": tier,
        "status": "ACTIVE",
        "monthly_fee_cents": fee,
        "next_service_due_utc": db.iso_z(
            db.get_now() + timedelta(days=SERVICE_INTERVAL_DAYS)),
        "coverage_cap_cents": TIER_CAP_CENTS[tier],
        "coverage_used_cents": 0,
    }
    stamp_new(sp)
    db.service_plans[sp["id"]] = sp
    return success_object(serialize(sp), 201)


@bp.get("/stairlift-ops/agreements/<aid>/service-plans")
def list_service_plans(aid):
    user_id, role = require_role(*READ_ROLES, "Customer")
    ag = db.agreements.get(aid)
    if ag is None:
        raise err_not_found("Agreement not found")
    if role == "Customer" and user_id != ag["customer_id"]:
        from errors import err_unauthorized
        raise err_unauthorized()
    limit, offset = get_pagination()
    items = sorted(
        (s for s in db.service_plans.values() if s["agreement_id"] == aid),
        key=lambda s: s["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize(s) for s in page], limit, offset, total)


@bp.get("/stairlift-ops/service-plans/<sid>")
def get_service_plan(sid):
    user_id, role = require_role(*READ_ROLES, "Customer")
    sp = db.service_plans.get(sid)
    if sp is None:
        raise err_not_found("ServicePlan not found")
    if role == "Customer":
        ag = db.agreements.get(sp["agreement_id"])
        if ag is None or user_id != ag["customer_id"]:
            from errors import err_unauthorized
            raise err_unauthorized()
    return success_object(serialize(sp))


@bp.post("/stairlift-ops/service-plans/<sid>/cancel")
def cancel_service_plan(sid):
    user_id, role = require_role("InstallCoordinator")
    sp = db.service_plans.get(sid)
    if sp is None:
        raise err_not_found("ServicePlan not found")
    if sp["status"] != "ACTIVE":
        raise err_invalid_state("ServicePlan must be ACTIVE to cancel")
    sp["status"] = "CANCELLED"
    touch(sp)
    audit("ServicePlan", sp["id"], "SERVICE_PLAN_CANCELLED", role, {})
    return success_object(serialize(sp))


@bp.get("/stairlift-ops/service-plans/<sid>/warranty-claims")
def list_plan_claims(sid):
    require_role("PlatformAdmin", "ClaimsAdjuster", "InstallCoordinator")
    if sid not in db.service_plans:
        raise err_not_found("ServicePlan not found")
    limit, offset = get_pagination()
    items = sorted(
        (w for w in db.warranty_claims.values() if w["service_plan_id"] == sid),
        key=lambda w: w["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize(w) for w in page], limit, offset, total)
