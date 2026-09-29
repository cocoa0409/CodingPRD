"""Blend recipes and the specification-change workflow."""
from decimal import Decimal

from flask import Blueprint

import calc
import cascades
import core
import enums
import store
import views
from core import (D, authenticate, body, fail, opt_enum, opt_str, pagination, q_enum,
                  q_str, req_enum, req_num, req_str)

bp = Blueprint("formulation", __name__)


# ==========================================================================
# BlendRecipe
# ==========================================================================
def _validate_components(b):
    raw = b.get("components")
    if raw is None:
        fail("ERR_INVALID_REQUEST", "Field 'components' is required.")
    if not isinstance(raw, list) or not raw:
        fail("ERR_INVALID_REQUEST", "Field 'components' must be a non-empty array.")
    parsed = []
    for entry in raw:
        if not isinstance(entry, dict):
            fail("ERR_INVALID_REQUEST", "Each component must be an object.")
        parsed.append({
            "component_code": req_str(entry, "component_code"),
            "component_type": req_enum(entry, "component_type", enums.COMPONENT_TYPES),
            "mass_fraction_pct": req_num(entry, "mass_fraction_pct", gt=0, le=100),
            "nominal_kv100_cst": req_num(entry, "nominal_kv100_cst", gt=0),
            "additive_family": opt_enum(entry, "additive_family",
                                        enums.ADDITIVE_FAMILIES_OPT, "NONE"),
        })
    return parsed


@bp.post("/blend-recipes")
def create_recipe():
    authenticate(["ProductManager"])
    b = body()
    spec_id = req_str(b, "product_spec_id")
    total_mass_basis_kg = req_num(b, "total_mass_basis_kg", gt=0)
    components = _validate_components(b)

    spec = store.must_get("ProductSpec", spec_id)

    total = Decimal(0)
    for comp in components:
        total += D(comp["mass_fraction_pct"])
    if total != Decimal(100):
        fail("ERR_RECIPE_FRACTION_SUM")

    recipe = store.insert("BlendRecipe", {
        "product_spec_id": spec["id"],
        "spec_revision_pinned": spec["revision"],
        "status": "DRAFT",
        "total_mass_basis_kg": total_mass_basis_kg,
        "additive_treat_pct": Decimal("0.00"),
        "predicted_kv100_cst": Decimal("0.000"),
        "component_count": 0,
    })
    for comp in components:
        record = {"blend_recipe_id": recipe["id"]}
        record.update(comp)
        store.insert("RecipeComponent", record, versioned=False)

    rows = calc.recipe_components(recipe["id"])
    recipe["additive_treat_pct"] = calc.recipe_additive_treat_pct(rows)
    recipe["predicted_kv100_cst"] = calc.recipe_predicted_kv100(rows)
    recipe["component_count"] = len(rows)
    return views.one(recipe, 201)


@bp.get("/blend-recipes/<rid>")
def read_recipe(rid):
    authenticate(views.STAFF_ALL)
    return views.one(store.must_get("BlendRecipe", rid))


@bp.get("/blend-recipes")
def list_recipes():
    authenticate(views.STAFF_ALL)
    limit, offset = pagination()
    spec_id = q_str("product_spec_id")
    status = q_enum("status", enums.RECIPE_STATUSES)
    rows = store.where("BlendRecipe", product_spec_id=spec_id, status=status)
    return views.listing(views.by_created_asc(rows), limit, offset)


@bp.get("/blend-recipes/<rid>/components")
def list_recipe_components(rid):
    authenticate(views.STAFF_OPS)
    limit, offset = pagination()
    store.must_get("BlendRecipe", rid)
    return views.listing(calc.recipe_components(rid), limit, offset)


@bp.post("/blend-recipes/<rid>/activate")
def activate_recipe(rid):
    authenticate(["ProductManager"])
    recipe = store.must_get("BlendRecipe", rid)
    if recipe["status"] != "DRAFT":
        fail("ERR_INVALID_STATE")
    spec = store.get("ProductSpec", recipe["product_spec_id"])
    if spec is None or spec["status"] != "ACTIVE":
        fail("ERR_SPEC_NOT_ACTIVE")

    components = calc.recipe_components(recipe["id"])
    # rung 20 - treat rate floor
    if D(recipe["additive_treat_pct"]) < D(spec["min_additive_treat_pct"]):
        fail("ERR_TREAT_RATE_BELOW_SPEC")
    # rung 21 - predicted viscosity band
    lower, upper = calc.viscosity_band(spec["target_kv100_cst"],
                                       spec["kv100_tolerance_pct"])
    if not calc.in_band(recipe["predicted_kv100_cst"], lower, upper):
        fail("ERR_PREDICTED_VISCOSITY_OUT_OF_SPEC")
    # rung 28 - fraction sum
    if calc.fraction_sum(components) != Decimal(100):
        fail("ERR_RECIPE_FRACTION_SUM")
    # rung 29 - pinned revision currency
    if recipe["spec_revision_pinned"] != spec["revision"]:
        fail("ERR_SPEC_REVISION_STALE")

    recipe["status"] = "ACTIVE"
    store.touch(recipe)
    return views.one(recipe)


# ==========================================================================
# SpecChangeRequest
# ==========================================================================
@bp.get("/spec-change-requests/<cid>")
def read_change_request(cid):
    authenticate(["PlatformAdmin", "ProductManager", "QualityManager",
                  "ComplianceOfficer"])
    return views.one(store.must_get("SpecChangeRequest", cid))


@bp.get("/spec-change-requests")
def list_change_requests():
    authenticate(["PlatformAdmin", "ProductManager", "QualityManager",
                  "ComplianceOfficer"])
    limit, offset = pagination()
    spec_id = q_str("product_spec_id")
    status = q_enum("status", enums.SCR_STATUSES)
    rows = store.where("SpecChangeRequest", product_spec_id=spec_id, status=status)
    return views.listing(views.by_created_asc(rows), limit, offset)


@bp.post("/spec-change-requests/<cid>/submit")
def submit_change_request(cid):
    authenticate(["ProductManager"])
    request_row = store.must_get("SpecChangeRequest", cid)
    if request_row["status"] != "DRAFT":
        fail("ERR_INVALID_STATE")
    spec = store.get("ProductSpec", request_row["product_spec_id"])
    if spec is None or spec["status"] != "ACTIVE":
        fail("ERR_SPEC_NOT_ACTIVE")
    request_row["status"] = "IN_REVIEW"
    request_row["viscosity_review"] = "PENDING"
    request_row["approval_review"] = "PENDING"
    store.touch(request_row)
    return views.one(request_row)


def _join(request_row):
    if request_row["viscosity_review"] == "PENDING":
        return
    if request_row["approval_review"] == "PENDING":
        return
    if "BLOCKED" in (request_row["viscosity_review"], request_row["approval_review"]):
        request_row["status"] = "REJECTED"
    else:
        request_row["status"] = "CLEARED"


@bp.post("/spec-change-requests/<cid>/viscosity-review")
def viscosity_review(cid):
    authenticate(["QualityManager"])
    b = body()
    decision = req_enum(b, "decision", enums.REVIEW_DECISIONS)
    opt_str(b, "note")
    request_row = store.must_get("SpecChangeRequest", cid)
    if request_row["status"] != "IN_REVIEW" or request_row["viscosity_review"] != "PENDING":
        fail("ERR_INVALID_STATE")
    if decision == "CLEAR":
        lower, upper = calc.viscosity_band(
            request_row["requested_kv100_cst"],
            request_row["requested_kv100_tolerance_pct"])
        for recipe in store.where("BlendRecipe",
                                  product_spec_id=request_row["product_spec_id"]):
            if recipe["status"] != "ACTIVE":
                continue
            if not calc.in_band(recipe["predicted_kv100_cst"], lower, upper):
                fail("ERR_VISCOSITY_REVIEW_BLOCKED")
    request_row["viscosity_review"] = "CLEARED" if decision == "CLEAR" else "BLOCKED"
    _join(request_row)
    store.touch(request_row)
    return views.one(request_row)


@bp.post("/spec-change-requests/<cid>/approval-review")
def approval_review(cid):
    authenticate(["ComplianceOfficer"])
    b = body()
    decision = req_enum(b, "decision", enums.REVIEW_DECISIONS)
    opt_str(b, "note")
    request_row = store.must_get("SpecChangeRequest", cid)
    if request_row["status"] != "IN_REVIEW" or request_row["approval_review"] != "PENDING":
        fail("ERR_INVALID_STATE")
    request_row["approval_review"] = "CLEARED" if decision == "CLEAR" else "BLOCKED"
    request_row["claims_to_suspend_count"] = len([
        c for c in store.where("ApprovalClaim",
                               product_spec_id=request_row["product_spec_id"])
        if c["status"] == "ACTIVE"])
    _join(request_row)
    store.touch(request_row)
    return views.one(request_row)


@bp.post("/spec-change-requests/<cid>/make-effective")
def make_effective(cid):
    authenticate(["ProductManager"])
    request_row = store.must_get("SpecChangeRequest", cid)
    if request_row["status"] != "CLEARED":
        fail("ERR_INVALID_STATE")
    spec = store.get("ProductSpec", request_row["product_spec_id"])
    if spec is None or spec["status"] != "ACTIVE":
        fail("ERR_SPEC_NOT_ACTIVE")

    spec["revision"] = spec["revision"] + 1
    spec["target_kv100_cst"] = request_row["requested_kv100_cst"]
    spec["kv100_tolerance_pct"] = request_row["requested_kv100_tolerance_pct"]
    spec["min_additive_treat_pct"] = request_row["requested_min_additive_treat_pct"]
    spec["additive_family"] = request_row["requested_additive_family"]
    store.touch(spec)

    cascades.spec_revision_advanced(spec)

    request_row["effective_revision"] = spec["revision"]
    request_row["status"] = "EFFECTIVE"
    store.touch(request_row)
    return views.one(request_row)


@bp.post("/spec-change-requests/<cid>/withdraw")
def withdraw_change_request(cid):
    authenticate(["ProductManager"])
    b = body()
    req_str(b, "reason")
    request_row = store.must_get("SpecChangeRequest", cid)
    if request_row["status"] != "DRAFT":
        fail("ERR_INVALID_STATE")
    request_row["status"] = "WITHDRAWN"
    store.touch(request_row)
    return views.one(request_row)
