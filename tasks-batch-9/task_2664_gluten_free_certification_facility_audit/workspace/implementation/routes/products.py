"""Product declaration, formula review, testing plan, label review, reads."""

from flask import Blueprint

import db
import middleware as mw
import query
import response
from constants import (
    LABEL_REJECTION_REASONS,
    MARK_TIERS,
    READ_PRODUCTS,
    ROLE_APPLICANT_CONTACT,
    ROLE_CERTIFICATION_REVIEWER,
)
from errors import ApiError
from services import derive

bp = Blueprint("products", __name__)


@bp.post("/gfco/products")
def create_product():
    user_id, _ = mw.authenticate([ROLE_APPLICANT_CONTACT])
    data = mw.body()
    applicant_id = mw.req_str(data, "applicant_id")
    facility_id = mw.req_str(data, "facility_id")
    name = mw.req_str(data, "name")
    sku = mw.req_str(data, "sku")
    requested_tier = mw.opt_enum(data, "requested_mark_tier", MARK_TIERS, "STANDARD")

    query.fetch("applicant", applicant_id)
    facility = query.fetch("facility", facility_id)
    if applicant_id != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    for existing in db.products.values():
        if existing["applicant_id"] == applicant_id and existing["sku"] == sku:
            raise ApiError("ERR_DUPLICATE_SKU")
    if facility["applicant_id"] != applicant_id:
        raise ApiError("ERR_FACILITY_APPLICANT_MISMATCH")

    row = db.insert(
        db.products,
        {
            "applicant_id": applicant_id,
            "facility_id": facility_id,
            "name": name,
            "sku": sku,
            "requested_mark_tier": requested_tier,
            "formula_status": "DRAFT",
            "label_status": "NOT_SUBMITTED",
            "testing_plan_status": "NONE",
            "testing_plan_revision": 0,
            "threshold_ppm": None,
            "sampling_lots_per_year": None,
            "sampling_exclusion_days": None,
            "mark_tier_granted": "NONE",
            "formula_cleared_by_user_id": None,
            "label_reviewed_by_user_id": None,
            "linked_ingredient_count": 0,
            "blocked_ingredient_count": 0,
            "last_scheduled_sample_on": None,
            "label_rejection_reason": None,
        },
    )
    return response.created(response.serialize(row))


@bp.get("/gfco/products/<product_id>")
def get_product(product_id):
    mw.authenticate(READ_PRODUCTS)
    return response.ok(response.serialize(query.fetch("product", product_id)))


@bp.get("/gfco/products")
def list_products():
    mw.authenticate(READ_PRODUCTS)
    return query.listing(
        db.products,
        {
            "applicant_id": query.arg("applicant_id"),
            "facility_id": query.arg("facility_id"),
            "formula_status": query.arg("formula_status"),
        },
    )


@bp.post("/gfco/products/<product_id>/formula-review")
def formula_review(product_id):
    user_id, _ = mw.authenticate([ROLE_CERTIFICATION_REVIEWER])
    data = mw.body()
    decision = mw.req_enum(data, "decision", ("CLEAR", "REJECT"))
    rejection_reason = mw.opt_str(data, "rejection_reason")
    product = query.fetch("product", product_id)

    if product["formula_status"] not in ("DRAFT", "REJECTED"):
        raise ApiError("ERR_INVALID_PRODUCT_STATE")

    if decision == "CLEAR":
        lines = derive.lines_for_product(product["id"])
        if any(ingredient["status"] != "APPROVED" for ingredient, _ in lines):
            raise ApiError("ERR_INGREDIENT_NOT_APPROVED")
        derive.recompute_product_counts(product)
        if product["linked_ingredient_count"] < 1:
            raise ApiError("ERR_NO_INGREDIENTS_LINKED")
        product["formula_status"] = "CLEARED"
        product["formula_cleared_by_user_id"] = user_id
    else:
        if rejection_reason is None:
            mw.bad("rejection_reason", "is required when rejecting a formula")
        product["formula_status"] = "REJECTED"

    db.touch(product)
    return response.ok(response.serialize(product))


@bp.post("/gfco/products/<product_id>/testing-plan")
def testing_plan(product_id):
    mw.authenticate([ROLE_CERTIFICATION_REVIEWER])
    data = mw.body()
    expected_version = mw.req_int(data, "expected_product_version")
    product = query.fetch("product", product_id)

    if expected_version != product["version"]:
        raise ApiError("ERR_STALE_PRODUCT_VERSION")
    if product["formula_status"] != "CLEARED":
        raise ApiError("ERR_INVALID_PRODUCT_STATE")
    derive.recompute_product_counts(product)
    if product["linked_ingredient_count"] < 1:
        raise ApiError("ERR_NO_INGREDIENTS_LINKED")

    derive.recompute_product_plan(product)
    product["testing_plan_status"] = "ACTIVE"
    product["testing_plan_revision"] = product["testing_plan_revision"] + 1
    db.touch(product)
    return response.ok(response.serialize(product))


@bp.post("/gfco/products/<product_id>/label-review")
def label_review(product_id):
    user_id, _ = mw.authenticate([ROLE_CERTIFICATION_REVIEWER])
    data = mw.body()
    decision = mw.req_enum(data, "decision", ("APPROVE", "REJECT"))
    mark_tier_granted = mw.opt_enum(data, "mark_tier_granted", MARK_TIERS)
    rejection_reason = mw.opt_enum(
        data, "rejection_reason", LABEL_REJECTION_REASONS
    )
    product = query.fetch("product", product_id)

    if product["label_status"] not in ("NOT_SUBMITTED", "REJECTED", "APPROVED"):
        raise ApiError("ERR_INVALID_PRODUCT_STATE")

    if decision == "APPROVE":
        if mark_tier_granted is None \
                or mark_tier_granted != product["requested_mark_tier"]:
            raise ApiError("ERR_MARK_TIER_NOT_GRANTED")
        product["label_status"] = "APPROVED"
        product["mark_tier_granted"] = mark_tier_granted
        product["label_reviewed_by_user_id"] = user_id
        product["label_rejection_reason"] = None
    else:
        if rejection_reason is None:
            mw.bad("rejection_reason", "is required when rejecting a label")
        product["label_status"] = "REJECTED"
        product["mark_tier_granted"] = "NONE"
        product["label_reviewed_by_user_id"] = user_id
        product["label_rejection_reason"] = rejection_reason

    db.touch(product)
    return response.ok(response.serialize(product))
