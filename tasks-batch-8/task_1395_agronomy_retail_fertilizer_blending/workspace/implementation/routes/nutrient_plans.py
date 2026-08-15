"""NutrientManagementPlan routes."""

from flask import Blueprint

import db
from errors import not_found, invalid_transition
from middleware import require_roles, check_grower_ownership, ALL_ROLES
from response import success_object, success_list, iso8601_ms
from services.core import scaffold_entity, touch, public, lazy_plan
from services.agronomy import P_DRAWDOWN_PPM
from util import (
    get_body, require, optional, reject_unknown, as_string, as_int, as_number,
    parse_pagination, paginate, parse_instant,
)

bp = Blueprint("nutrient_plans", __name__)


def _get_field(fid):
    x = db.fields.get(fid)
    if x is None:
        raise not_found("Field not found")
    return x


def _get_plan(pid):
    x = db.nutrient_plans.get(pid)
    if x is None:
        raise not_found("Nutrient plan not found")
    return x


@bp.post("/agronomy/fields/<fieldId>/nutrient-plans")
def create_plan(fieldId):
    require_roles("Agronomist")
    field = _get_field(fieldId)
    body = get_body()
    reject_unknown(body, {"crop_year", "n_cap_lbs_per_acre", "valid_from", "valid_to",
                          "manure_credit_n_lbs", "previous_crop_credit_n_lbs"})
    crop_year = as_int(require(body, "crop_year"), "crop_year")
    n_cap = as_number(require(body, "n_cap_lbs_per_acre"), "n_cap_lbs_per_acre", minimum=0, exclusive_min=True)
    valid_from = parse_instant(require(body, "valid_from"), "valid_from")
    valid_to = parse_instant(require(body, "valid_to"), "valid_to")
    manure = as_int(optional(body, "manure_credit_n_lbs", 0), "manure_credit_n_lbs", minimum=0)
    prev_crop = as_int(optional(body, "previous_crop_credit_n_lbs", 0), "previous_crop_credit_n_lbs", minimum=0)
    plan = scaffold_entity(db.nutrient_plans, {
        "field_id": field["id"],
        "crop_year": crop_year,
        "n_cap_lbs_per_acre": float(n_cap),
        "manure_credit_n_lbs": manure,
        "previous_crop_credit_n_lbs": prev_crop,
        "p_restriction_active": False,
        "valid_from": iso8601_ms(valid_from),
        "valid_to": iso8601_ms(valid_to),
        "status": "DRAFT",
    })
    plan["_valid_to"] = valid_to
    return success_object(public(plan), 201)


@bp.get("/agronomy/fields/<fieldId>/nutrient-plans")
def list_field_plans(fieldId):
    require_roles(*ALL_ROLES)
    field = _get_field(fieldId)
    check_grower_ownership(field["grower_id"])
    limit, offset = parse_pagination()
    items = [p for p in db.nutrient_plans.values() if p["field_id"] == field["id"]]
    for p in items:
        lazy_plan(p)
    items.sort(key=lambda x: (x["created_at"], x["id"]))
    total = len(items)
    return success_list([public(x) for x in paginate(items, limit, offset)], limit, offset, total)


@bp.get("/agronomy/nutrient-plans/<planId>")
def get_plan(planId):
    require_roles(*ALL_ROLES)
    plan = _get_plan(planId)
    lazy_plan(plan)
    field = db.fields.get(plan["field_id"])
    if field is not None:
        check_grower_ownership(field["grower_id"])
    return success_object(public(plan))


def _transition(planId, allowed_role, from_status, to_status, extra=None):
    require_roles(allowed_role)
    plan = _get_plan(planId)
    lazy_plan(plan)
    if plan["status"] != from_status:
        raise invalid_transition(f"Nutrient plan not {from_status}")
    plan["status"] = to_status
    if extra:
        extra(plan)
    touch(plan)
    return success_object(public(plan))


@bp.post("/agronomy/nutrient-plans/<planId>/submit")
def submit_plan(planId):
    return _transition(planId, "Agronomist", "DRAFT", "SUBMITTED")


@bp.post("/agronomy/nutrient-plans/<planId>/return")
def return_plan(planId):
    require_roles("ComplianceOfficer")
    plan = _get_plan(planId)
    lazy_plan(plan)
    body = get_body()
    reject_unknown(body, {"reason"})
    as_string(require(body, "reason"), "reason")
    if plan["status"] != "SUBMITTED":
        raise invalid_transition("Nutrient plan not SUBMITTED")
    plan["status"] = "DRAFT"
    touch(plan)
    return success_object(public(plan))


@bp.post("/agronomy/nutrient-plans/<planId>/approve")
def approve_plan(planId):
    require_roles("ComplianceOfficer")
    plan = _get_plan(planId)
    lazy_plan(plan)
    if plan["status"] != "SUBMITTED":
        raise invalid_transition("Nutrient plan not SUBMITTED")
    field = db.fields.get(plan["field_id"])
    p_restriction = False
    if field is not None and field["watershed_zone"] in ("PROTECTED", "CRITICAL"):
        resulted = [s for s in db.soil_tests.values()
                    if s["field_id"] == field["id"] and s["status"] == "RESULTED"]
        if resulted:
            resulted.sort(key=lambda s: (s["created_at"], s["id"]))
            latest = resulted[-1]
            if latest["p_ppm"] is not None and latest["p_ppm"] >= P_DRAWDOWN_PPM:
                p_restriction = True
    plan["p_restriction_active"] = p_restriction
    plan["status"] = "APPROVED"
    touch(plan)
    return success_object(public(plan))


@bp.post("/agronomy/nutrient-plans/<planId>/suspend")
def suspend_plan(planId):
    return _transition(planId, "ComplianceOfficer", "APPROVED", "SUSPENDED")


@bp.post("/agronomy/nutrient-plans/<planId>/reinstate")
def reinstate_plan(planId):
    return _transition(planId, "ComplianceOfficer", "SUSPENDED", "APPROVED")
