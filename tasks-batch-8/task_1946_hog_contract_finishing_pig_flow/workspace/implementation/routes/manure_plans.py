"""Manure plans (PRD §3.9): annual nutrient budgets, submit/approve/reject/revise
revision loop, approval supersedes the site's other APPROVED plans."""

from flask import Blueprint, request

from db import store
from errors import (
    conflict,
    ERR_INVALID_STATE_TRANSITION,
    ERR_SITE_NOT_ACTIVE,
    ERR_PLAN_YEAR_OVERLAP,
    ERR_LAGOON_OVER_CAPACITY,
)
from middleware import (
    require_roles, ROLE_INTEGRATOR_ADMIN, ROLE_ENVIRONMENTAL_MANAGER,
)
from response import success_object, paginate
from services.core import new_record, touch, ser_manure_plan
from util import get_body, req, as_str, as_int, load_or_404

bp = Blueprint("manure_plans", __name__)

ROLES_READ = [ROLE_INTEGRATOR_ADMIN, ROLE_ENVIRONMENTAL_MANAGER]


@bp.route("/manure-plans", methods=["POST"])
def create_manure_plan():
    require_roles([ROLE_ENVIRONMENTAL_MANAGER])
    body = get_body()
    site_id = as_str(req(body, "site_id"), "site_id")
    load_or_404(store.sites, site_id, "Site")
    plan_year = as_int(req(body, "plan_year"), "plan_year")
    lagoon_capacity = as_int(req(body, "lagoon_capacity_gal"), "lagoon_capacity_gal", 0)
    lagoon_start = as_int(req(body, "lagoon_start_gal"), "lagoon_start_gal", 0)
    n_budget = as_int(req(body, "n_budget_lbs"), "n_budget_lbs", 0)
    p_budget = as_int(req(body, "p_budget_lbs"), "p_budget_lbs", 0)
    # fiscal (12): the starting volume must not exceed lagoon capacity
    if lagoon_start > lagoon_capacity:
        raise conflict(ERR_LAGOON_OVER_CAPACITY,
                       "lagoon_start_gal exceeds lagoon_capacity_gal")
    rec = new_record()
    rec.update({
        "site_id": site_id, "plan_year": plan_year,
        "lagoon_capacity_gal": lagoon_capacity, "lagoon_start_gal": lagoon_start,
        "n_budget_lbs": n_budget, "p_budget_lbs": p_budget,
        "submitted_by": None, "plan_status": "DRAFT",
    })
    store.manure_plans[rec["id"]] = rec
    return success_object(ser_manure_plan(rec), 201)


@bp.route("/manure-plans", methods=["GET"])
def list_manure_plans():
    require_roles(ROLES_READ)
    site_id = request.args.get("site_id")
    plan_year = request.args.get("plan_year")
    status = request.args.get("plan_status")
    items = list(store.manure_plans.values())
    if site_id is not None:
        items = [p for p in items if p["site_id"] == site_id]
    if plan_year is not None:
        try:
            py = int(plan_year)
            items = [p for p in items if p["plan_year"] == py]
        except (TypeError, ValueError):
            items = []
    if status is not None:
        items = [p for p in items if p["plan_status"] == status]
    return paginate(items, request.args, ser_manure_plan)


@bp.route("/manure-plans/<pid>", methods=["GET"])
def get_manure_plan(pid):
    require_roles(ROLES_READ)
    return success_object(ser_manure_plan(load_or_404(store.manure_plans, pid, "ManurePlan")))


@bp.route("/manure-plans/<pid>/submit", methods=["POST"])
def submit_manure_plan(pid):
    role, user_id = require_roles([ROLE_ENVIRONMENTAL_MANAGER])
    plan = load_or_404(store.manure_plans, pid, "ManurePlan")
    if plan["plan_status"] != "DRAFT":
        raise conflict(ERR_INVALID_STATE_TRANSITION,
                       f"Cannot submit a plan in {plan['plan_status']}")
    # no other plan for the same site+year may sit in SUBMITTED or APPROVED
    for p in store.manure_plans.values():
        if (p["id"] != pid and p["site_id"] == plan["site_id"]
                and p["plan_year"] == plan["plan_year"]
                and p["plan_status"] in ("SUBMITTED", "APPROVED")):
            raise conflict(ERR_PLAN_YEAR_OVERLAP,
                           "Another plan for this site and year is SUBMITTED or APPROVED")
    plan["plan_status"] = "SUBMITTED"
    plan["submitted_by"] = user_id
    touch(plan)
    return success_object(ser_manure_plan(plan))


@bp.route("/manure-plans/<pid>/approve", methods=["POST"])
def approve_manure_plan(pid):
    require_roles([ROLE_INTEGRATOR_ADMIN])
    plan = load_or_404(store.manure_plans, pid, "ManurePlan")
    if plan["plan_status"] != "SUBMITTED":
        raise conflict(ERR_INVALID_STATE_TRANSITION,
                       f"Cannot approve a plan in {plan['plan_status']}")
    site = store.sites.get(plan["site_id"])
    if site is None or site["site_status"] != "ACTIVE":
        raise conflict(ERR_SITE_NOT_ACTIVE, "Site is not ACTIVE")
    plan["plan_status"] = "APPROVED"
    touch(plan)
    # every other APPROVED plan of the same site is superseded
    for p in store.manure_plans.values():
        if p["id"] != pid and p["site_id"] == plan["site_id"] and p["plan_status"] == "APPROVED":
            p["plan_status"] = "SUPERSEDED"
            touch(p)
    return success_object(ser_manure_plan(plan))


@bp.route("/manure-plans/<pid>/reject", methods=["POST"])
def reject_manure_plan(pid):
    require_roles([ROLE_INTEGRATOR_ADMIN])
    plan = load_or_404(store.manure_plans, pid, "ManurePlan")
    if plan["plan_status"] != "SUBMITTED":
        raise conflict(ERR_INVALID_STATE_TRANSITION,
                       f"Cannot reject a plan in {plan['plan_status']}")
    plan["plan_status"] = "REJECTED"
    touch(plan)
    return success_object(ser_manure_plan(plan))


@bp.route("/manure-plans/<pid>/revise", methods=["POST"])
def revise_manure_plan(pid):
    require_roles([ROLE_ENVIRONMENTAL_MANAGER])
    plan = load_or_404(store.manure_plans, pid, "ManurePlan")
    if plan["plan_status"] != "REJECTED":
        raise conflict(ERR_INVALID_STATE_TRANSITION,
                       f"Cannot revise a plan in {plan['plan_status']}")
    plan["plan_status"] = "DRAFT"
    touch(plan)
    return success_object(ser_manure_plan(plan))
