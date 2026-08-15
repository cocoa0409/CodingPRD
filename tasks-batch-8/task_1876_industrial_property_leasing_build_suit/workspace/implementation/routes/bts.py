"""Build-to-suit pricing, revision loop, and approval (PRD §3.5)."""
from flask import Blueprint

from db import store, public, touch
from errors import (
    ApiError, ERR_INVALID_STATE, ERR_RENT_CONVERSION_OVER_RUN,
)
from middleware import (
    authenticate, body, require_fields, check_enums, get_path,
    PRICING_METHODS, ALL_ROLES,
)
from response import success_object
from routes import list_response
from services import calc, cascades
from services.calc import D, rhu2

bp = Blueprint("bts_plans", __name__)


@bp.get("/api/bts-plans")
def list_plans():
    authenticate(ALL_ROLES)
    return list_response(store.plans.values(), [
        ("loi_id", lambda e: e["loi_id"]),
        ("status", lambda e: e["status"]),
    ])


@bp.get("/api/bts-plans/<pid>")
def get_plan(pid):
    authenticate(ALL_ROLES)
    return success_object(public(get_path(store.plans, pid, "build-to-suit plan")))


@bp.post("/api/bts-plans/<pid>/price")
def price_plan(pid):
    authenticate(["ProjectManager"])
    plan = get_path(store.plans, pid, "build-to-suit plan")
    b = body()
    require_fields(b, [
        ("hard_cost_total", "number", True),
        ("soft_cost_total", "number", True),
        ("pricing_method", "string", True),
        ("contingency_pct", "number", False),
    ])
    check_enums(b, [("pricing_method", PRICING_METHODS)])
    if plan["status"] != "SCHEMATIC":
        raise ApiError(ERR_INVALID_STATE,
                       f"Cannot price a plan in status {plan['status']}", 409)
    loi = store.lois[plan["loi_id"]]
    site = store.sites[loi["site_id"]]
    contingency = D(b["contingency_pct"]) if b.get("contingency_pct") is not None else D("0.05")
    results = calc.bts_cost_rent_conversion(
        b["hard_cost_total"], b["soft_cost_total"], contingency,
        b["pricing_method"], loi["leased_sf"], loi["term_years"],
        loi["escalation_pct"], site["asking_rate_psf"])
    plan["hard_cost_total"] = D(b["hard_cost_total"])
    plan["soft_cost_total"] = D(b["soft_cost_total"])
    plan["contingency_pct"] = contingency
    plan["pricing_method"] = b["pricing_method"]
    plan.update(results)
    plan["status"] = "PRICED"
    touch(plan)
    return success_object(public(plan))


@bp.post("/api/bts-plans/<pid>/revise")
def revise_plan(pid):
    authenticate(["ProjectManager"])
    plan = get_path(store.plans, pid, "build-to-suit plan")
    if plan["status"] != "PRICED":
        raise ApiError(ERR_INVALID_STATE,
                       f"Cannot revise a plan in status {plan['status']}", 409)
    # Computed pricing fields are retained until the next price run overwrites them.
    plan["status"] = "SCHEMATIC"
    touch(plan)
    return success_object(public(plan))


@bp.post("/api/bts-plans/<pid>/approve")
def approve_plan(pid):
    authenticate(["AssetManager"])
    plan = get_path(store.plans, pid, "build-to-suit plan")
    if plan["status"] != "PRICED":
        raise ApiError(ERR_INVALID_STATE,
                       f"Cannot approve a plan in status {plan['status']}", 409)
    loi = store.lois[plan["loi_id"]]
    cap = rhu2(D("1.10") * D(loi["base_rate_psf"]))
    if D(plan["converted_base_rate_psf"]) > cap:
        raise ApiError(ERR_RENT_CONVERSION_OVER_RUN,
                       "converted_base_rate_psf exceeds 110% of the LOI base rate", 422)
    plan["status"] = "APPROVED"
    touch(plan)
    # Shortcut: if every milestone (at least one) is already COMPLETE, the plan
    # continues straight through APPROVED -> DELIVERED in the same request.
    if cascades.all_milestones_complete(plan["id"]):
        cascades.deliver_plan_cascade(plan)
    return success_object(public(plan))
