"""Suppliers, traceability documents, due diligence and suspension (PRD 3.1)."""
from decimal import Decimal

from flask import Blueprint

import domain
import response
import store
import validate
from constants import DD_MONTH_DAYS, DOC_TYPES, FEEDSTOCK_TYPES
from errors import (
    ERR_DUE_DILIGENCE_DOCS_INSUFFICIENT,
    ERR_DUPLICATE_DOCUMENT,
    ERR_INVALID_REQUEST,
    ERR_INVALID_SUPPLIER_STATE,
    ERR_SUPPLIER_SCOPE_VIOLATION,
    fail,
)
from routes.helpers import find, listing
from store import bump, q

bp = Blueprint("suppliers", __name__)
ZERO = Decimal("0")


def _scope(user_id, role, supplier):
    if role == "Supplier" and user_id != supplier["id"]:
        fail(ERR_SUPPLIER_SCOPE_VIOLATION,
             "A Supplier caller may only act on its own supplier record.")


@bp.post("/suppliers")
def create_supplier():
    validate.auth("FeedstockTrader")
    data = validate.body()
    legal_name = validate.get_str(data, "legal_name", 1, 120)
    country_code = validate.get_str(data, "country_code", 2, 2)
    if len(country_code) != 2 or not country_code.isalpha() or country_code != country_code.upper():
        fail(ERR_INVALID_REQUEST, "Field 'country_code' must be exactly two uppercase letters.")
    feedstock_types = validate.get_enum_array(data, "feedstock_types", FEEDSTOCK_TYPES)
    is_high_risk = validate.get_bool(data, "is_high_risk_origin", required=False, default=False)

    row = store.new_row()
    row.update({
        "legal_name": legal_name,
        "country_code": country_code,
        "feedstock_types": feedstock_types,
        "is_high_risk_origin": is_high_risk,
        "dd_status": "PENDING",
        "dd_verified_at": None,
        "dd_expires_at": None,
        "dd_document_type_count": 0,
        "suspension_reason": None,
    })
    store.suppliers[row["id"]] = row
    return response.ok(row, 201)


@bp.get("/suppliers/<sid>")
def read_supplier(sid):
    user_id, role = validate.auth("FeedstockTrader", "QualityAnalyst",
                                 "ComplianceOfficer", "Supplier")
    supplier = find("supplier", sid)
    _scope(user_id, role, supplier)
    domain.recompute_dd_document_type_count(supplier)
    return response.ok(supplier)


@bp.post("/suppliers/<sid>/traceability-documents")
def upload_document(sid):
    user_id, role = validate.auth("Supplier", "FeedstockTrader")
    supplier = find("supplier", sid)
    _scope(user_id, role, supplier)
    data = validate.body()
    doc_type = validate.get_enum(data, "doc_type", DOC_TYPES)
    issued_at = validate.get_dt(data, "issued_at")
    valid_until = validate.get_dt(data, "valid_until")
    doc_hash = validate.get_str(data, "doc_hash", 8, 128)
    if valid_until <= issued_at:
        fail(ERR_INVALID_REQUEST, "Field 'valid_until' must be strictly after 'issued_at'.")

    for existing in domain.supplier_documents(supplier["id"]):
        if existing["doc_type"] == doc_type:
            fail(ERR_DUPLICATE_DOCUMENT,
                 "Supplier already holds a %s document." % doc_type)
    for existing in store.documents.values():
        if existing["doc_hash"] == doc_hash:
            fail(ERR_DUPLICATE_DOCUMENT, "A document with this doc_hash already exists.")

    row = store.new_row(versioned=False)
    row.update({
        "supplier_id": supplier["id"],
        "doc_type": doc_type,
        "issued_at": issued_at,
        "valid_until": valid_until,
        "doc_hash": doc_hash,
    })
    store.documents[row["id"]] = row

    domain.recompute_dd_document_type_count(supplier)
    bump(supplier)
    return response.ok(row, 201)


@bp.get("/suppliers/<sid>/traceability-documents")
def list_documents(sid):
    user_id, role = validate.auth("ComplianceOfficer", "FeedstockTrader", "Supplier")
    supplier = find("supplier", sid)
    _scope(user_id, role, supplier)
    rows, limit, offset = listing(domain.supplier_documents(supplier["id"]),
                                  {"doc_type": "doc_type"})
    return response.page(rows, limit, offset)


@bp.post("/suppliers/<sid>/due-diligence-verifications")
def verify_supplier(sid):
    validate.auth("ComplianceOfficer")
    supplier = find("supplier", sid)
    data = validate.body()
    valid_months = validate.get_int(data, "valid_months", minv=1)

    if supplier["dd_status"] != "PENDING":
        fail(ERR_INVALID_SUPPLIER_STATE,
             "Supplier due diligence is %s, not PENDING." % supplier["dd_status"])

    valid_types = domain.valid_doc_types(supplier)
    supplier["dd_document_type_count"] = len(valid_types)
    if supplier["is_high_risk_origin"]:
        if len(valid_types) < 3 or "THIRD_PARTY_AUDIT" not in valid_types:
            fail(ERR_DUE_DILIGENCE_DOCS_INSUFFICIENT,
                 "A high-risk-origin supplier needs 3 valid document types including "
                 "a THIRD_PARTY_AUDIT.")
    elif len(valid_types) < 2:
        fail(ERR_DUE_DILIGENCE_DOCS_INSUFFICIENT,
             "At least 2 valid traceability document types are required.")

    clock = store.now()
    supplier["dd_status"] = "VERIFIED"
    supplier["dd_verified_at"] = clock
    supplier["dd_expires_at"] = clock + store.timedelta(days=DD_MONTH_DAYS * valid_months)
    supplier["suspension_reason"] = None
    bump(supplier)
    return response.ok(supplier)


@bp.post("/suppliers/<sid>/suspensions")
def suspend_supplier(sid):
    validate.auth("ComplianceOfficer")
    supplier = find("supplier", sid)
    data = validate.body()
    reason = validate.get_str(data, "reason", 1, 500)

    if supplier["dd_status"] not in ("PENDING", "VERIFIED"):
        fail(ERR_INVALID_SUPPLIER_STATE,
             "Supplier due diligence is %s and cannot be suspended." % supplier["dd_status"])

    domain.suspend_supplier_cascade(supplier, reason)
    return response.ok(supplier)
