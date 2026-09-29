"""Ingredient declaration, submission, review and reads."""

from flask import Blueprint

import clock
import db
import middleware as mw
import query
import response
from constants import (
    INGREDIENT_REJECTION_REASONS,
    READ_INGREDIENTS,
    RISK_CLASSES,
    ROLE_APPLICANT_CONTACT,
    ROLE_CERTIFICATION_REVIEWER,
)
from errors import ApiError
from services import derive

bp = Blueprint("ingredients", __name__)


def _check_graph(applicant_id, parent, new_id=None):
    """Priority 44: same applicant and no loop in the parent chain."""
    if parent["applicant_id"] != applicant_id:
        raise ApiError("ERR_INGREDIENT_GRAPH_CYCLE")
    if new_id is not None and parent["id"] == new_id:
        raise ApiError("ERR_INGREDIENT_GRAPH_CYCLE")
    seen = set()
    cursor = parent
    while cursor is not None:
        if cursor["id"] in seen or (new_id is not None and cursor["id"] == new_id):
            raise ApiError("ERR_INGREDIENT_GRAPH_CYCLE")
        seen.add(cursor["id"])
        parent_id = cursor.get("parent_ingredient_id")
        if not parent_id:
            break
        cursor = db.ingredients.get(parent_id)


@bp.post("/gfco/ingredients")
def create_ingredient():
    user_id, _ = mw.authenticate([ROLE_APPLICANT_CONTACT])
    data = mw.body()
    applicant_id = mw.req_str(data, "applicant_id")
    supplier_id = mw.req_str(data, "supplier_id")
    name = mw.req_str(data, "name")
    risk_class = mw.req_enum(data, "risk_class", RISK_CLASSES)
    parent_ingredient_id = mw.opt_id(data, "parent_ingredient_id")

    query.fetch("applicant", applicant_id)
    query.fetch("supplier", supplier_id)
    parent = query.maybe("ingredient", parent_ingredient_id)

    if applicant_id != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    if parent is not None:
        _check_graph(applicant_id, parent)

    row = db.insert(
        db.ingredients,
        {
            "applicant_id": applicant_id,
            "supplier_id": supplier_id,
            "parent_ingredient_id": parent_ingredient_id,
            "name": name,
            "risk_class": risk_class,
            "status": "DRAFT",
            "review_cycle_count": 0,
            "verified_doc_types": [],
            "blocked_reason": None,
            "rejection_reason": None,
            "reviewed_by_user_id": None,
            "approved_on": None,
        },
    )
    return response.created(response.serialize(row))


@bp.get("/gfco/ingredients/<ingredient_id>")
def get_ingredient(ingredient_id):
    mw.authenticate(READ_INGREDIENTS)
    return response.ok(response.serialize(query.fetch("ingredient", ingredient_id)))


@bp.get("/gfco/ingredients")
def list_ingredients():
    mw.authenticate(READ_INGREDIENTS)
    return query.listing(
        db.ingredients,
        {
            "applicant_id": query.arg("applicant_id"),
            "supplier_id": query.arg("supplier_id"),
            "parent_ingredient_id": query.arg("parent_ingredient_id"),
            "status": query.arg("status"),
        },
    )


@bp.post("/gfco/ingredients/<ingredient_id>/submission")
def submit_ingredient(ingredient_id):
    user_id, _ = mw.authenticate([ROLE_APPLICANT_CONTACT])
    mw.body()
    ingredient = query.fetch("ingredient", ingredient_id)
    if ingredient["applicant_id"] != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    if ingredient["status"] not in ("DRAFT", "REJECTED", "BLOCKED"):
        raise ApiError("ERR_INVALID_INGREDIENT_STATE")
    supplier = db.suppliers.get(ingredient["supplier_id"])
    if supplier is not None and supplier["status"] == "SUSPENDED":
        raise ApiError("ERR_SUPPLIER_SUSPENDED")

    ingredient["status"] = "UNDER_REVIEW"
    ingredient["review_cycle_count"] = ingredient["review_cycle_count"] + 1
    ingredient["blocked_reason"] = None
    ingredient["rejection_reason"] = None
    db.touch(ingredient)
    return response.ok(response.serialize(ingredient))


@bp.post("/gfco/ingredients/<ingredient_id>/review")
def review_ingredient(ingredient_id):
    user_id, _ = mw.authenticate([ROLE_CERTIFICATION_REVIEWER])
    data = mw.body()
    decision = mw.req_enum(data, "decision", ("APPROVE", "REJECT"))
    rejection_reason = mw.opt_enum(
        data, "rejection_reason", INGREDIENT_REJECTION_REASONS
    )
    ingredient = query.fetch("ingredient", ingredient_id)

    if ingredient["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_INGREDIENT_STATE")

    supplier = db.suppliers.get(ingredient["supplier_id"])
    if supplier is not None:
        if supplier["status"] == "SUSPENDED":
            raise ApiError("ERR_SUPPLIER_SUSPENDED")
        if decision == "APPROVE" and supplier["status"] != "ACTIVE":
            raise ApiError("ERR_SUPPLIER_SUSPENDED")

    if decision == "APPROVE":
        required = derive.required_doc_types(ingredient)
        if not set(required).issubset(set(ingredient["verified_doc_types"])):
            raise ApiError("ERR_REQUIRED_SUPPLIER_DOCS_MISSING")
        now = clock.now()
        counted = [
            doc
            for doc in derive.documents_for_ingredient(ingredient["id"])
            if doc["status"] == "VERIFIED" and doc["doc_type"] in required
        ]
        if any(doc["expires_on"] is None or doc["expires_on"] <= now
               for doc in counted):
            raise ApiError("ERR_SUPPLIER_DOCUMENT_EXPIRED")
        ingredient["status"] = "APPROVED"
        ingredient["approved_on"] = now
        ingredient["reviewed_by_user_id"] = user_id
        ingredient["blocked_reason"] = None
        db.touch(ingredient)
        derive.restore_products_of_ingredients([ingredient["id"]])
        return response.ok(response.serialize(ingredient))

    if rejection_reason is None:
        mw.bad("rejection_reason", "is required when rejecting an ingredient")
    ingredient["status"] = "REJECTED"
    ingredient["rejection_reason"] = rejection_reason
    ingredient["reviewed_by_user_id"] = user_id
    db.touch(ingredient)
    derive.refresh_products_of_ingredients(
        [ingredient["id"]], force_block=True
    )
    return response.ok(response.serialize(ingredient))
