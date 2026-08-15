"""Manure applications (PRD §3.9): budget-debiting land application records,
confirm/void with exact credit-back on void."""

from datetime import date as date_cls

from flask import Blueprint, request

from db import store
from errors import (
    conflict,
    ERR_INVALID_STATE_TRANSITION,
    ERR_PLAN_NOT_APPROVED,
    ERR_APPLICATION_OUTSIDE_WINDOW,
    ERR_NUTRIENT_BUDGET_EXCEEDED,
    ERR_LAGOON_INSUFFICIENT,
)
from middleware import require_roles, ROLE_INTEGRATOR_ADMIN, ROLE_ENVIRONMENTAL_MANAGER
from response import success_object, paginate
from services.core import (
    new_record, touch, ser_manure_application,
    plan_n_applied, plan_p_applied, plan_lagoon_available,
)
from util import get_body, req, as_str, as_int, as_datetime, load_or_404

bp = Blueprint("manure_applications", __name__)

ROLES = [ROLE_INTEGRATOR_ADMIN, ROLE_ENVIRONMENTAL_MANAGER]


@bp.route("/manure-applications", methods=["POST"])
def create_manure_application():
    role, user_id = require_roles([ROLE_ENVIRONMENTAL_MANAGER])
    body = get_body()
    plan_id = as_str(req(body, "plan_id"), "plan_id")
    plan = load_or_404(store.manure_plans, plan_id, "ManurePlan")
    field_code = as_str(req(body, "field_code"), "field_code")
    applied_at = as_datetime(req(body, "applied_at"), "applied_at")
    gallons = as_int(req(body, "gallons"), "gallons", 1)
    n_lbs = as_int(req(body, "n_lbs"), "n_lbs", 0)
    p_lbs = as_int(req(body, "p_lbs"), "p_lbs", 0)
    # state (7): applications draw down an APPROVED plan only
    if plan["plan_status"] != "APPROVED":
        raise conflict(ERR_PLAN_NOT_APPROVED, "Plan is not APPROVED")
    # temporal (9): within [plan_year-03-01, plan_year-11-30] inclusive, not future
    window_start = date_cls(plan["plan_year"], 3, 1)
    window_end = date_cls(plan["plan_year"], 11, 30)
    if (applied_at.date() < window_start or applied_at.date() > window_end
            or applied_at > store.now()):
        raise conflict(ERR_APPLICATION_OUTSIDE_WINDOW,
                       "applied_at is outside the plan year's Mar 1 - Nov 30 window "
                       "or lies in the future")
    # fiscal (12), in fixed order: nitrogen, then phosphorus, then lagoon volume
    if plan_n_applied(plan_id) + n_lbs > plan["n_budget_lbs"]:
        raise conflict(ERR_NUTRIENT_BUDGET_EXCEEDED,
                       "Nitrogen budget would be exceeded")
    if plan_p_applied(plan_id) + p_lbs > plan["p_budget_lbs"]:
        raise conflict(ERR_NUTRIENT_BUDGET_EXCEEDED,
                       "Phosphorus budget would be exceeded")
    if gallons > plan_lagoon_available(plan):
        raise conflict(ERR_LAGOON_INSUFFICIENT,
                       "gallons exceeds lagoon_available_gal")
    rec = new_record()
    rec.update({
        "plan_id": plan_id, "field_code": field_code, "applied_at": applied_at,
        "gallons": gallons, "n_lbs": n_lbs, "p_lbs": p_lbs,
        "application_status": "RECORDED",
    })
    store.manure_applications[rec["id"]] = rec
    # the plan's aggregates moved (n_applied/p_applied/lagoon_available debited)
    touch(plan)
    return success_object(ser_manure_application(rec), 201)


@bp.route("/manure-applications", methods=["GET"])
def list_manure_applications():
    require_roles(ROLES)
    plan_id = request.args.get("plan_id")
    status = request.args.get("application_status")
    items = list(store.manure_applications.values())
    if plan_id is not None:
        items = [a for a in items if a["plan_id"] == plan_id]
    if status is not None:
        items = [a for a in items if a["application_status"] == status]
    return paginate(items, request.args, ser_manure_application)


@bp.route("/manure-applications/<aid>", methods=["GET"])
def get_manure_application(aid):
    require_roles(ROLES)
    return success_object(ser_manure_application(
        load_or_404(store.manure_applications, aid, "ManureApplication")))


@bp.route("/manure-applications/<aid>/confirm", methods=["POST"])
def confirm_manure_application(aid):
    require_roles([ROLE_ENVIRONMENTAL_MANAGER])
    app = load_or_404(store.manure_applications, aid, "ManureApplication")
    if app["application_status"] != "RECORDED":
        raise conflict(ERR_INVALID_STATE_TRANSITION,
                       f"Cannot confirm an application in {app['application_status']}")
    app["application_status"] = "CONFIRMED"
    touch(app)
    return success_object(ser_manure_application(app))


@bp.route("/manure-applications/<aid>/void", methods=["POST"])
def void_manure_application(aid):
    require_roles([ROLE_ENVIRONMENTAL_MANAGER])
    app = load_or_404(store.manure_applications, aid, "ManureApplication")
    if app["application_status"] not in ("RECORDED", "CONFIRMED"):
        raise conflict(ERR_INVALID_STATE_TRANSITION,
                       f"Cannot void an application in {app['application_status']}")
    app["application_status"] = "VOIDED"
    touch(app)
    # compensating credit: the application leaves every aggregate (§3.9)
    plan = store.manure_plans.get(app["plan_id"])
    if plan is not None:
        touch(plan)
    return success_object(ser_manure_application(app))
