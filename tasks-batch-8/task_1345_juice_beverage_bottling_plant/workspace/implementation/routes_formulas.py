"""Formula and LabelClaimReview endpoints."""
from flask import Blueprint, request

from domain import (ALLERGEN_GROUPS, CLAIMS, OPEN_RUN_STATES, PROCESS_TYPES,
                    ser_batch, ser_formula, ser_review)
from errors import err
from routes_customers import get_customer_or_404
from store import db, stamp, touch
from util import (body, ok, paginate, req_enum, req_enum_list, req_field,
                  require_any, require_roles)

bp = Blueprint("formulas", __name__)


def get_formula_or_404(formula_id):
    formula = db.formulas.get(formula_id)
    if formula is None:
        raise err("ERR_FORMULA_NOT_FOUND", f"Formula {formula_id} not found")
    return formula


def get_review_or_404(review_id):
    review = db.reviews.get(review_id)
    if review is None:
        raise err("ERR_LABEL_REVIEW_NOT_FOUND", f"LabelClaimReview {review_id} not found")
    return review


@bp.post("/v1/formulas")
def create_formula():
    require_roles("ProductDeveloper")
    data = body()
    customer_id = req_field(data, "customer_id", "str")
    formula_code = req_field(data, "formula_code", "str")
    name = req_field(data, "name", "str")
    target_brix = req_field(data, "target_brix", "num")
    brix_tolerance = req_field(data, "brix_tolerance", "num")
    process_type = req_enum(data, "process_type", PROCESS_TYPES)
    container_fill_ml = req_field(data, "container_fill_ml", "int")
    concentrate_brix = req_field(data, "concentrate_brix", "num")
    allergen_group = req_enum(data, "allergen_group", ALLERGEN_GROUPS)
    shelf_life_days = req_field(data, "shelf_life_days", "int")
    claims = req_enum_list(data, "claims", CLAIMS)
    get_customer_or_404(customer_id)
    formula = {
        "customer_id": customer_id,
        "formula_code": formula_code,
        "name": name,
        "target_brix": target_brix,
        "brix_tolerance": brix_tolerance,
        "process_type": process_type,
        "container_fill_ml": container_fill_ml,
        "concentrate_brix": concentrate_brix,
        "allergen_group": allergen_group,
        "shelf_life_days": shelf_life_days,
        "claims": claims,
        "label_version": 0,
        "submitted_by_user_id": None,
        "status": "DRAFT",
    }
    stamp(formula)
    db.formulas[formula["id"]] = formula
    return ok(ser_formula(formula), 201)


@bp.get("/v1/formulas")
def list_formulas():
    require_any()
    customer_id = request.args.get("customer_id")
    status = request.args.get("status")
    items = list(db.formulas.values())
    if customer_id is not None:
        items = [f for f in items if f["customer_id"] == customer_id]
    if status is not None:
        items = [f for f in items if f["status"] == status]
    return paginate(items, ser_formula)


@bp.get("/v1/formulas/<formula_id>")
def get_formula(formula_id):
    require_any()
    return ok(ser_formula(get_formula_or_404(formula_id)))


@bp.post("/v1/formulas/<formula_id>/submit-label-review")
def submit_label_review(formula_id):
    user_id, _ = require_roles("ProductDeveloper")
    formula = get_formula_or_404(formula_id)
    data = body()
    expected = req_field(data, "expected_formula_version", "int")
    if expected != formula["version"]:
        raise err("ERR_STALE_VERSION",
                  "expected_formula_version does not match the formula's current version")
    if formula["status"] not in ("DRAFT", "REVISION_REQUIRED", "APPROVED", "LABEL_REVIEW"):
        raise err("ERR_FORMULA_STATE_INVALID",
                  "submit-label-review requires DRAFT, REVISION_REQUIRED, APPROVED or LABEL_REVIEW")
    for review in db.reviews.values():
        if review["formula_id"] == formula_id and review["status"] == "PENDING":
            review["status"] = "SUPERSEDED"
            touch(review)
    review = {
        "formula_id": formula_id,
        "claims_snapshot": list(formula["claims"]),
        "review_note": None,
        "reviewer_user_id": None,
        "status": "PENDING",
    }
    stamp(review)
    db.reviews[review["id"]] = review
    formula["status"] = "LABEL_REVIEW"
    formula["submitted_by_user_id"] = user_id
    touch(formula)
    return ok(ser_review(review), 201)


@bp.post("/v1/formulas/<formula_id>/retire")
def retire_formula(formula_id):
    require_roles("ProductDeveloper")
    formula = get_formula_or_404(formula_id)
    if formula["status"] not in ("DRAFT", "APPROVED"):
        raise err("ERR_FORMULA_STATE_INVALID",
                  "retire requires DRAFT or APPROVED")
    for run in db.runs.values():
        if run["formula_id"] == formula_id and run["production_status"] in OPEN_RUN_STATES:
            raise err("ERR_FORMULA_STATE_INVALID",
                      "Formula has production runs still open")
    formula["status"] = "RETIRED"
    touch(formula)
    return ok(ser_formula(formula))


@bp.get("/v1/formulas/<formula_id>/label-reviews")
def formula_reviews(formula_id):
    require_any()
    get_formula_or_404(formula_id)
    items = [r for r in db.reviews.values() if r["formula_id"] == formula_id]
    return paginate(items, ser_review)


@bp.get("/v1/formulas/<formula_id>/batches")
def formula_batches(formula_id):
    require_any()
    get_formula_or_404(formula_id)
    items = [b for b in db.batches.values() if b["formula_id"] == formula_id]
    return paginate(items, ser_batch)


@bp.get("/v1/label-reviews/<review_id>")
def get_review(review_id):
    require_any()
    return ok(ser_review(get_review_or_404(review_id)))


@bp.post("/v1/label-reviews/<review_id>/approve")
def approve_review(review_id):
    user_id, _ = require_roles("LabelComplianceReviewer")
    review = get_review_or_404(review_id)
    if review["status"] != "PENDING":
        raise err("ERR_REVIEW_STATE_INVALID", "approve requires status PENDING")
    formula = get_formula_or_404(review["formula_id"])
    if user_id == formula["submitted_by_user_id"]:
        raise err("ERR_SOD_LABEL_SELF_REVIEW",
                  "Reviewer must differ from the submitting user")
    review["status"] = "APPROVED"
    review["reviewer_user_id"] = user_id
    touch(review)
    formula["status"] = "APPROVED"
    formula["label_version"] += 1
    touch(formula)
    for run in db.runs.values():
        if run["formula_id"] == formula["id"] and run["production_status"] == "BLOCKED_LABEL":
            run["production_status"] = "CONFIRMED"
            touch(run)
    return ok(ser_review(review))


@bp.post("/v1/label-reviews/<review_id>/reject")
def reject_review(review_id):
    user_id, _ = require_roles("LabelComplianceReviewer")
    review = get_review_or_404(review_id)
    if review["status"] != "PENDING":
        raise err("ERR_REVIEW_STATE_INVALID", "reject requires status PENDING")
    formula = get_formula_or_404(review["formula_id"])
    if user_id == formula["submitted_by_user_id"]:
        raise err("ERR_SOD_LABEL_SELF_REVIEW",
                  "Reviewer must differ from the submitting user")
    data = body()
    note = data.get("review_note")
    if note is not None and not isinstance(note, str):
        raise err("ERR_INVALID_REQUEST", "review_note must be a string")
    review["status"] = "REJECTED"
    review["reviewer_user_id"] = user_id
    if note is not None:
        review["review_note"] = note
    touch(review)
    formula["status"] = "REVISION_REQUIRED"
    touch(formula)
    for run in db.runs.values():
        if run["formula_id"] == formula["id"] and run["production_status"] == "CONFIRMED":
            run["production_status"] = "BLOCKED_LABEL"
            touch(run)
    return ok(ser_review(review))
