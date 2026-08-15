"""Recommendation routes: creation, review ladder, formulation preview."""

from flask import Blueprint, request, g

import db
from errors import not_found, invalid_transition, validation
from middleware import require_roles, check_grower_ownership, ALL_ROLES
from response import success_object, success_list
from services.agronomy import compute_recommendation_rates, formulation_preview
from services.core import scaffold_entity, touch, public, lazy_recommendation
from util import (
    get_body, require, optional, reject_unknown, as_string, as_enum, as_int,
    parse_pagination, paginate, parse_instant,
)

bp = Blueprint("recommendations", __name__)

CROPS = {"CORN", "SOYBEAN", "WHEAT"}
RATE_VARIANTS = {"BUILD_RATE", "MAINTENANCE_RATE"}


def _get_soil_test(sid):
    x = db.soil_tests.get(sid)
    if x is None:
        raise not_found("Soil test not found")
    return x


def _get_rec(rid):
    x = db.recommendations.get(rid)
    if x is None:
        raise not_found("Recommendation not found")
    return x


def _ownership_check_for_rec(rec):
    field = db.fields.get(rec["field_id"])
    if field is not None:
        check_grower_ownership(field["grower_id"])


@bp.post("/agronomy/soil-tests/<soilTestId>/recommendations")
def create_recommendation(soilTestId):
    require_roles("Agronomist")
    st = _get_soil_test(soilTestId)
    body = get_body()
    reject_unknown(body, {"crop", "yield_goal_bu_per_acre", "rate_variant", "valid_until",
                          "previous_crop", "manure_credit_n_lbs"})
    crop = as_enum(require(body, "crop"), "crop", CROPS)
    yield_goal = as_int(require(body, "yield_goal_bu_per_acre"), "yield_goal_bu_per_acre", minimum=1)
    rate_variant = as_enum(require(body, "rate_variant"), "rate_variant", RATE_VARIANTS)
    valid_until = parse_instant(require(body, "valid_until"), "valid_until")
    previous_crop = as_enum(optional(body, "previous_crop", "CORN"), "previous_crop", CROPS)
    manure_credit = as_int(optional(body, "manure_credit_n_lbs", 0), "manure_credit_n_lbs", minimum=0)
    if st["status"] != "RESULTED":
        raise invalid_transition("Soil test not RESULTED")
    n, p2o5, k2o = compute_recommendation_rates(
        st, crop, yield_goal, rate_variant, previous_crop, manure_credit)
    from response import iso8601_ms
    rec = scaffold_entity(db.recommendations, {
        "soil_test_id": st["id"],
        "field_id": st["field_id"],
        "crop": crop,
        "yield_goal_bu_per_acre": yield_goal,
        "rate_variant": rate_variant,
        "previous_crop": previous_crop,
        "manure_credit_n_lbs": manure_credit,
        "n_lbs_per_acre": n,
        "p2o5_lbs_per_acre": p2o5,
        "k2o_lbs_per_acre": k2o,
        "valid_until": iso8601_ms(valid_until),
        "return_reason": None,
        "status": "DRAFT",
    })
    rec["_valid_until"] = valid_until
    return success_object(public(rec), 201)


@bp.get("/agronomy/soil-tests/<soilTestId>/recommendations")
def list_soil_test_recs(soilTestId):
    require_roles(*ALL_ROLES)
    st = _get_soil_test(soilTestId)
    field = db.fields.get(st["field_id"])
    if field is not None:
        check_grower_ownership(field["grower_id"])
    limit, offset = parse_pagination()
    items = [r for r in db.recommendations.values() if r["soil_test_id"] == st["id"]]
    for r in items:
        lazy_recommendation(r)
    items.sort(key=lambda x: (x["created_at"], x["id"]))
    total = len(items)
    return success_list([public(x) for x in paginate(items, limit, offset)], limit, offset, total)


@bp.get("/agronomy/recommendations")
def list_recommendations():
    require_roles(*ALL_ROLES)
    limit, offset = parse_pagination()
    items = list(db.recommendations.values())
    if "field_id" in request.args:
        items = [r for r in items if r["field_id"] == request.args["field_id"]]
    for r in items:
        lazy_recommendation(r)
    if "status" in request.args:
        items = [r for r in items if r["status"] == request.args["status"]]
    if g.role == "Grower":
        own_fields = {f["id"] for f in db.fields.values() if f["grower_id"] == g.user_id}
        items = [r for r in items if r["field_id"] in own_fields]
    items.sort(key=lambda x: (x["created_at"], x["id"]))
    total = len(items)
    return success_list([public(x) for x in paginate(items, limit, offset)], limit, offset, total)


@bp.get("/agronomy/recommendations/<recommendationId>")
def get_recommendation(recommendationId):
    require_roles(*ALL_ROLES)
    rec = _get_rec(recommendationId)
    lazy_recommendation(rec)
    _ownership_check_for_rec(rec)
    return success_object(public(rec))


@bp.post("/agronomy/recommendations/<recommendationId>/submit")
def submit_rec(recommendationId):
    require_roles("Agronomist")
    rec = _get_rec(recommendationId)
    lazy_recommendation(rec)
    if rec["status"] != "DRAFT":
        raise invalid_transition("Recommendation not DRAFT")
    rec["status"] = "PENDING_REVIEW"
    touch(rec)
    return success_object(public(rec))


@bp.post("/agronomy/recommendations/<recommendationId>/return")
def return_rec(recommendationId):
    require_roles("ComplianceOfficer")
    rec = _get_rec(recommendationId)
    lazy_recommendation(rec)
    body = get_body()
    reject_unknown(body, {"reason"})
    reason = as_string(require(body, "reason"), "reason")
    if rec["status"] != "PENDING_REVIEW":
        raise invalid_transition("Recommendation not PENDING_REVIEW")
    rec["status"] = "DRAFT"
    rec["return_reason"] = reason
    touch(rec)
    return success_object(public(rec))


@bp.post("/agronomy/recommendations/<recommendationId>/approve")
def approve_rec(recommendationId):
    require_roles("ComplianceOfficer")
    rec = _get_rec(recommendationId)
    lazy_recommendation(rec)
    if rec["status"] != "PENDING_REVIEW":
        raise invalid_transition("Recommendation not PENDING_REVIEW")
    rec["status"] = "APPROVED"
    touch(rec)
    return success_object(public(rec))


@bp.post("/agronomy/recommendations/<recommendationId>/supersede")
def supersede_rec(recommendationId):
    require_roles("Agronomist")
    rec = _get_rec(recommendationId)
    lazy_recommendation(rec)
    if rec["status"] != "APPROVED":
        raise invalid_transition("Recommendation not APPROVED")
    rec["status"] = "SUPERSEDED"
    touch(rec)
    return success_object(public(rec))


@bp.post("/agronomy/recommendations/<recommendationId>/formulation-preview")
def formulation(recommendationId):
    require_roles("Agronomist", "Grower", "BranchAdmin")
    rec = _get_rec(recommendationId)
    lazy_recommendation(rec)
    _ownership_check_for_rec(rec)
    body = get_body()
    reject_unknown(body, {"product_ids"})
    product_ids = require(body, "product_ids")
    if not isinstance(product_ids, list) or not all(isinstance(x, str) for x in product_ids):
        raise validation("product_ids must be an array of strings")
    products = []
    for pid in product_ids:
        p = db.products.get(pid)
        if p is None:
            raise not_found(f"Product {pid} not found")
        products.append(p)
    lines = formulation_preview(rec, products)
    return success_object({"feasible": True, "lines": lines})
