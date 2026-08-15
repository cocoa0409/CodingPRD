"""SupplierIngredientApproval endpoints (with SoD and cascade on revoke)."""

from flask import Blueprint

import errors
from db import store
from middleware import require_roles, get_json_body, require_string, optional_field
from response import success_object
from services.calculations import stamp_new, touch, serialize, iso_format
from routes.suppliers import recompute_supplier_approved_count

bp = Blueprint("supplier_ingredient_approvals", __name__)

TERMINAL = {"REJECTED", "REVOKED"}


@bp.route("/supplier-ingredient-approvals", methods=["POST"])
def create_pairing():
    user_id, _ = require_roles("QualityAnalyst")
    body = get_json_body()
    supplier_id = require_string(body, "supplier_id")
    ingredient_id = require_string(body, "ingredient_id")
    supplier = store.suppliers.get(supplier_id)
    if supplier is None:
        raise errors.not_found("Supplier not found")
    ingredient = store.ingredients.get(ingredient_id)
    if ingredient is None:
        raise errors.not_found("Ingredient not found")

    coa_document_ref = optional_field(body, "coa_document_ref")
    if ingredient.get("requires_coa", True):
        if not coa_document_ref or not isinstance(coa_document_ref, str) or not coa_document_ref.strip():
            raise errors.invalid_request("coa_document_ref is required when ingredient.requires_coa is true")
    elif coa_document_ref is not None and not isinstance(coa_document_ref, str):
        raise errors.invalid_request("coa_document_ref must be a string")

    review_notes = optional_field(body, "review_notes", "")
    if not isinstance(review_notes, str):
        raise errors.invalid_request("review_notes must be a string")

    pairing = {
        "supplier_id": supplier_id,
        "ingredient_id": ingredient_id,
        "approval_state": "PENDING_REVIEW",
        "coa_document_ref": coa_document_ref,
        "review_notes": review_notes,
        "decided_by": None,
        "decided_at": None,
        "_created_by_user_id": user_id,
    }
    stamp_new(pairing)
    store.supplier_ingredient_approvals[pairing["id"]] = pairing
    return success_object(serialize(pairing), 201)


def _get_pairing(id):
    p = store.supplier_ingredient_approvals.get(id)
    if p is None:
        raise errors.not_found("SupplierIngredientApproval not found")
    return p


def _check_not_terminal(p):
    if p["approval_state"] in TERMINAL:
        raise errors.already_terminal("Pairing is in a terminal state")


def _stamp_decision(p, user_id):
    now = store.now()
    p["decided_by"] = user_id
    p["decided_at"] = iso_format(now)


@bp.route("/supplier-ingredient-approvals/<id>/approve", methods=["POST"])
def approve_pairing(id):
    user_id, _ = require_roles("QAApprover")
    pairing = _get_pairing(id)
    _check_not_terminal(pairing)
    if pairing["approval_state"] != "PENDING_REVIEW":
        raise errors.invalid_state("Only PENDING_REVIEW pairings can be approved")
    # SoD: approver must differ from requester
    if user_id == pairing.get("_created_by_user_id"):
        raise errors.sod_violation()
    supplier = store.suppliers.get(pairing["supplier_id"])
    if supplier is None or supplier["approval_state"] != "APPROVED":
        raise errors.supplier_not_approved()
    ingredient = store.ingredients.get(pairing["ingredient_id"])
    if ingredient is None or ingredient["status"] != "ACTIVE":
        raise errors.ingredient_inactive()

    pairing["approval_state"] = "APPROVED"
    _stamp_decision(pairing, user_id)
    touch(pairing, status_changed=True)
    recompute_supplier_approved_count(pairing["supplier_id"])
    return success_object(serialize(pairing), 200)


@bp.route("/supplier-ingredient-approvals/<id>/reject", methods=["POST"])
def reject_pairing(id):
    user_id, _ = require_roles("QAApprover")
    pairing = _get_pairing(id)
    _check_not_terminal(pairing)
    if pairing["approval_state"] != "PENDING_REVIEW":
        raise errors.invalid_state("Only PENDING_REVIEW pairings can be rejected")
    if user_id == pairing.get("_created_by_user_id"):
        raise errors.sod_violation()

    pairing["approval_state"] = "REJECTED"
    _stamp_decision(pairing, user_id)
    touch(pairing, status_changed=True)
    return success_object(serialize(pairing), 200)


@bp.route("/supplier-ingredient-approvals/<id>/revoke", methods=["POST"])
def revoke_pairing(id):
    user_id, _ = require_roles("QAApprover")
    pairing = _get_pairing(id)
    _check_not_terminal(pairing)
    if pairing["approval_state"] != "APPROVED":
        raise errors.invalid_state("Only APPROVED pairings can be revoked")

    pairing["approval_state"] = "REVOKED"
    _stamp_decision(pairing, user_id)
    touch(pairing, status_changed=True)
    recompute_supplier_approved_count(pairing["supplier_id"])

    # Cascade: formulas in NUTRIENT_REVIEW that include this ingredient and now
    # lack any APPROVED pairing covering that ingredient -> DRAFT, revision+1, version+1.
    ingredient_id = pairing["ingredient_id"]
    for formula in store.formulas.values():
        if formula["status"] != "NUTRIENT_REVIEW":
            continue
        formula_ingredient_ids = [
            fi["ingredient_id"] for fi in store.formula_ingredients.values()
            if fi["formula_id"] == formula["id"]
        ]
        if ingredient_id not in formula_ingredient_ids:
            continue
        # Does any APPROVED pairing still cover this ingredient?
        covered = any(
            a["ingredient_id"] == ingredient_id and a["approval_state"] == "APPROVED"
            for a in store.supplier_ingredient_approvals.values()
        )
        if not covered:
            formula["status"] = "DRAFT"
            formula["revision_number"] = int(formula["revision_number"]) + 1
            touch(formula, status_changed=True)
    return success_object(serialize(pairing), 200)


@bp.route("/supplier-ingredient-approvals/<id>", methods=["GET"])
def get_pairing(id):
    require_roles("PlatformAdmin", "QualityAnalyst", "QAApprover")
    pairing = _get_pairing(id)
    return success_object(serialize(pairing), 200)
