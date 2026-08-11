"""SecurityPlan endpoints."""

from flask import Blueprint, request

import errors
import serializers
from db import stamp_new, store, touch
from envelope import ok
from listing import page_out
from validators import (
    CATEGORIES,
    as_dt,
    as_enum_list,
    as_str,
    body,
    endpoint,
    get_or_404,
    req,
)

bp = Blueprint("plans", __name__)

ALL_ROLES = ["CarrierAdmin", "ShipperComplianceOfficer", "Regulator"]


def _plan_or_404(plan_id):
    return get_or_404(store.security_plans, plan_id,
                      errors.ERR_SECURITY_PLAN_NOT_FOUND, "SecurityPlan")


def _overlap_exists(carrier_id, effective_from, effective_to, exclude_id=None):
    """Closed-interval overlap vs other non-terminal plans of the carrier."""
    for p in store.security_plans.values():
        if p["carrier_id"] != carrier_id or p["id"] == exclude_id:
            continue
        if p["status"] in ("REJECTED", "EXPIRED"):
            continue
        if effective_from <= p["effective_to"] and p["effective_from"] <= effective_to:
            return True
    return False


@bp.route("/hazmat/carriers/<carrierId>/security-plans", methods=["POST"])
@endpoint(["CarrierAdmin"])
def create_plan(uid, role, carrierId):
    carrier = get_or_404(store.carriers, carrierId, errors.ERR_CARRIER_NOT_FOUND,
                         "Carrier")
    b = body()
    plan_name = as_str(req(b, "plan_name"), "plan_name")
    coverage = as_enum_list(req(b, "coverage_categories"), "coverage_categories",
                            CATEGORIES)
    eff_from = as_dt(req(b, "effective_from"), "effective_from")
    eff_to = as_dt(req(b, "effective_to"), "effective_to")
    if eff_to <= eff_from:
        raise errors.invalid("effective_to must be strictly later than effective_from")
    if carrier["registration_status"] != "APPROVED_ACTIVE":
        raise errors.conflict(errors.ERR_CARRIER_NOT_ACTIVE,
                              "Carrier must be APPROVED_ACTIVE to create security plans")
    if _overlap_exists(carrier["id"], eff_from, eff_to):
        raise errors.conflict(errors.ERR_PLAN_WINDOW_CONFLICT,
                              "Plan window overlaps another non-terminal plan")
    plan = {
        "carrier_id": carrier["id"],
        "plan_name": plan_name,
        "coverage_categories": coverage,
        "effective_from": eff_from,
        "effective_to": eff_to,
        "status": "DRAFT",
        "approved_at": None,
    }
    stamp_new(plan)
    store.security_plans[plan["id"]] = plan
    return ok(serializers.security_plan(plan), 201)


@bp.route("/hazmat/carriers/<carrierId>/security-plans", methods=["GET"])
@endpoint(ALL_ROLES)
def list_plans(uid, role, carrierId):
    carrier = get_or_404(store.carriers, carrierId, errors.ERR_CARRIER_NOT_FOUND,
                         "Carrier")
    rows = [p for p in store.security_plans.values()
            if p["carrier_id"] == carrier["id"]]
    status = request.args.get("status")
    if status is not None:
        rows = [p for p in rows if p["status"] == status]
    return page_out(rows, serializers.security_plan)


@bp.route("/hazmat/security-plans/<planId>/submit", methods=["POST"])
@endpoint(["CarrierAdmin"])
def submit_plan(uid, role, planId):
    plan = _plan_or_404(planId)
    if plan["status"] not in ("DRAFT", "UNDER_REVISION"):
        raise errors.conflict(errors.ERR_PLAN_NOT_SUBMITTABLE,
                              "Plan submit requires DRAFT or UNDER_REVISION")
    plan["status"] = "SUBMITTED"
    touch(plan)
    return ok(serializers.security_plan(plan), 200)


@bp.route("/hazmat/security-plans/<planId>/approve", methods=["POST"])
@endpoint(["Regulator"])
def approve_plan(uid, role, planId):
    plan = _plan_or_404(planId)
    if plan["status"] != "SUBMITTED":
        raise errors.conflict(errors.ERR_PLAN_NOT_SUBMITTED,
                              "Plan approve requires SUBMITTED")
    if _overlap_exists(plan["carrier_id"], plan["effective_from"],
                       plan["effective_to"], exclude_id=plan["id"]):
        raise errors.conflict(errors.ERR_PLAN_WINDOW_CONFLICT,
                              "Plan window overlaps another non-terminal plan")
    plan["status"] = "APPROVED"
    plan["approved_at"] = store.clock
    touch(plan)
    return ok(serializers.security_plan(plan), 200)


@bp.route("/hazmat/security-plans/<planId>/reject", methods=["POST"])
@endpoint(["Regulator"])
def reject_plan(uid, role, planId):
    plan = _plan_or_404(planId)
    if plan["status"] != "SUBMITTED":
        raise errors.conflict(errors.ERR_PLAN_NOT_SUBMITTED,
                              "Plan reject requires SUBMITTED")
    plan["status"] = "REJECTED"
    touch(plan)
    return ok(serializers.security_plan(plan), 200)


@bp.route("/hazmat/security-plans/<planId>/revise", methods=["POST"])
@endpoint(["CarrierAdmin"])
def revise_plan(uid, role, planId):
    plan = _plan_or_404(planId)
    if plan["status"] != "APPROVED":
        raise errors.conflict(errors.ERR_PLAN_NOT_APPROVED,
                              "Plan revise requires APPROVED")
    plan["status"] = "UNDER_REVISION"
    touch(plan)  # version bump stales any pinned shipments
    return ok(serializers.security_plan(plan), 200)
