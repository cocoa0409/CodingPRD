"""LabelApproval endpoints: private-label drafts, submission (allergen
declaration must equal the formula's allergen_class), and QA review."""
from flask import Blueprint, g, request

from db import STORE
from errors import (
    err,
    ERR_FORMULA_NOT_FOUND,
    ERR_LABEL_ALLERGEN_MISMATCH,
    ERR_LABEL_NOT_DRAFT,
    ERR_LABEL_NOT_FOUND,
    ERR_LABEL_NOT_SUBMITTED,
)
from middleware import check_customer_scope, require_roles
from response import paginate, success
from services.core import find_or_404, new_record, serialize, sorted_created, touch
from util import as_bool, as_str, body_json, check_enum, opt, req

bp = Blueprint("labels", __name__)

ALLERGEN_CLASSES = ("NONE", "GLUTEN", "SOY", "NUT", "DAIRY")


def _formula_of(label):
    return STORE.formulas.get(label["formula_id"])


@bp.post("/copack/label-approvals")
def create_label():
    require_roles("OpsAdmin", "Customer")
    body = body_json()
    raw_formula_id = body.get("formula_id")
    formula = None
    if isinstance(raw_formula_id, str):
        formula = STORE.formulas.get(raw_formula_id)
        if formula is not None:
            check_customer_scope(formula["customer_id"])
    formula_id = as_str(req(body, "formula_id"), "formula_id")
    if formula is None:
        formula = find_or_404(STORE.formulas, formula_id, ERR_FORMULA_NOT_FOUND, "formula")
    label_version = as_str(req(body, "label_version"), "label_version")
    brand_display_name = as_str(req(body, "brand_display_name"), "brand_display_name")
    net_quantity_statement = as_str(req(body, "net_quantity_statement"), "net_quantity_statement")
    allergen_declaration = check_enum(
        as_str(req(body, "allergen_declaration"), "allergen_declaration"),
        ALLERGEN_CLASSES, "allergen_declaration",
    )
    rec = new_record({
        "formula_id": formula_id,
        "label_version": label_version,
        "brand_display_name": brand_display_name,
        "net_quantity_statement": net_quantity_statement,
        "allergen_declaration": allergen_declaration,
        "status": "DRAFT",
    })
    STORE.labels[rec["id"]] = rec
    return success(serialize(rec), 201)


@bp.get("/copack/label-approvals")
def list_labels():
    require_roles("OpsAdmin", "QAReviewer", "Customer")
    formula_id = request.args.get("formula_id")
    status = request.args.get("status")
    items = []
    for label in sorted_created(STORE.labels.values()):
        if g.user_role == "Customer":
            f = _formula_of(label)
            if f is None or f["customer_id"] != g.user_id:
                continue
        if formula_id is not None and label["formula_id"] != formula_id:
            continue
        if status is not None and label["status"] != status:
            continue
        items.append(serialize(label))
    return paginate(items)


@bp.get("/copack/label-approvals/<lid>")
def get_label(lid):
    require_roles("OpsAdmin", "QAReviewer", "Customer")
    rec = find_or_404(STORE.labels, lid, ERR_LABEL_NOT_FOUND, "label approval")
    f = _formula_of(rec)
    if f is not None:
        check_customer_scope(f["customer_id"])
    return success(serialize(rec))


@bp.post("/copack/label-approvals/<lid>/submit")
def submit_label(lid):
    require_roles("OpsAdmin", "Customer")
    rec = find_or_404(STORE.labels, lid, ERR_LABEL_NOT_FOUND, "label approval")
    f = _formula_of(rec)
    if f is not None:
        check_customer_scope(f["customer_id"])
    # Stage 6 state gate first, then (stage 8) the allergen declaration match.
    if rec["status"] != "DRAFT":
        raise err(ERR_LABEL_NOT_DRAFT, 409, "label is not in DRAFT")
    if f is not None and rec["allergen_declaration"] != f["allergen_class"]:
        raise err(ERR_LABEL_ALLERGEN_MISMATCH, 422, "allergen declaration disagrees with the formula's allergen_class")
    rec["status"] = "SUBMITTED"
    touch(rec)
    return success(serialize(rec))


@bp.post("/copack/label-approvals/<lid>/review")
def review_label(lid):
    require_roles("QAReviewer")
    rec = find_or_404(STORE.labels, lid, ERR_LABEL_NOT_FOUND, "label approval")
    body = body_json()
    approved = as_bool(req(body, "approved"), "approved")
    review_note = opt(body, "review_note")
    if review_note is not None:
        as_str(review_note, "review_note")
    if rec["status"] != "SUBMITTED":
        raise err(ERR_LABEL_NOT_SUBMITTED, 409, "label is not SUBMITTED")
    rec["status"] = "APPROVED" if approved else "REJECTED"
    if review_note is not None:
        rec["review_note"] = review_note
    touch(rec)
    return success(serialize(rec))
