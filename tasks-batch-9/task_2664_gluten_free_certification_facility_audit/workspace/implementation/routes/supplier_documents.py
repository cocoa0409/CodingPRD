"""Supplier document upload, verification and reads."""

from flask import Blueprint

import clock
import db
import middleware as mw
import query
import response
from constants import (
    COA_MAX_PPM_CLAIM,
    DOC_REJECTION_REASONS,
    DOC_TYPES,
    READ_SUPPLIER_DOCS,
    ROLE_APPLICANT_CONTACT,
    ROLE_CERTIFICATION_REVIEWER,
)
from errors import ApiError
from services import calc, derive

bp = Blueprint("supplier_documents", __name__)


@bp.post("/gfco/supplier-documents")
def create_document():
    user_id, _ = mw.authenticate([ROLE_APPLICANT_CONTACT])
    data = mw.body()
    supplier_id = mw.req_str(data, "supplier_id")
    ingredient_id = mw.req_str(data, "ingredient_id")
    doc_type = mw.req_enum(data, "doc_type", DOC_TYPES)
    issued_on = mw.req_dt(data, "issued_on")
    expires_on = mw.req_dt(data, "expires_on")
    lab_ppm_claim = mw.opt_num(data, "lab_ppm_claim", None, minimum=0)

    query.fetch("supplier", supplier_id)
    ingredient = query.fetch("ingredient", ingredient_id)
    if ingredient["applicant_id"] != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    if ingredient["supplier_id"] != supplier_id:
        raise ApiError("ERR_DOCUMENT_SUPPLIER_MISMATCH")

    row = db.insert(
        db.supplier_documents,
        {
            "supplier_id": supplier_id,
            "ingredient_id": ingredient_id,
            "doc_type": doc_type,
            "issued_on": issued_on,
            "expires_on": expires_on,
            "lab_ppm_claim": lab_ppm_claim,
            "status": "PENDING",
            "verified_by_user_id": None,
            "verified_on": None,
            "rejection_reason": None,
        },
    )
    return response.created(response.serialize(row))


@bp.get("/gfco/supplier-documents/<document_id>")
def get_document(document_id):
    mw.authenticate(READ_SUPPLIER_DOCS)
    return response.ok(
        response.serialize(query.fetch("supplier_document", document_id))
    )


@bp.get("/gfco/supplier-documents")
def list_documents():
    mw.authenticate(READ_SUPPLIER_DOCS)
    return query.listing(
        db.supplier_documents,
        {
            "supplier_id": query.arg("supplier_id"),
            "ingredient_id": query.arg("ingredient_id"),
            "status": query.arg("status"),
        },
    )


@bp.post("/gfco/supplier-documents/<document_id>/verification")
def verify_document(document_id):
    user_id, _ = mw.authenticate([ROLE_CERTIFICATION_REVIEWER])
    data = mw.body()
    decision = mw.req_enum(data, "decision", ("APPROVE", "REJECT"))
    rejection_reason = mw.opt_enum(data, "rejection_reason", DOC_REJECTION_REASONS)
    doc = query.fetch("supplier_document", document_id)

    if doc["status"] != "PENDING":
        raise ApiError("ERR_DOCUMENT_ALREADY_DECIDED")

    ingredient = db.ingredients.get(doc["ingredient_id"])

    if decision == "APPROVE":
        if doc["doc_type"] == "COA" and doc["lab_ppm_claim"] is not None \
                and ingredient is not None:
            cap = COA_MAX_PPM_CLAIM[ingredient["risk_class"]]
            if calc.dec(doc["lab_ppm_claim"]) > calc.dec(cap):
                raise ApiError("ERR_COA_PPM_CLAIM_TOO_HIGH")
        if doc["expires_on"] is None or doc["expires_on"] <= clock.now():
            raise ApiError("ERR_SUPPLIER_DOCUMENT_EXPIRED")
        doc["status"] = "VERIFIED"
        doc["verified_by_user_id"] = user_id
        doc["verified_on"] = clock.now()
        db.touch(doc)
        supplier = db.suppliers.get(doc["supplier_id"])
        if supplier is not None:
            derive.recompute_supplier(supplier)
        if ingredient is not None:
            derive.recompute_ingredient_docs(ingredient)
        return response.ok(response.serialize(doc))

    if rejection_reason is None:
        mw.bad("rejection_reason", "is required when rejecting a document")
    doc["status"] = "REJECTED"
    doc["rejection_reason"] = rejection_reason
    db.touch(doc)
    if ingredient is not None:
        derive.recompute_ingredient_docs(ingredient)
        if ingredient["status"] == "APPROVED":
            required = derive.required_doc_types(ingredient)
            if not set(required).issubset(set(ingredient["verified_doc_types"])):
                derive.block_ingredients_for_cause(
                    [ingredient], "DOCUMENT_REJECTED"
                )
    return response.ok(response.serialize(doc))
