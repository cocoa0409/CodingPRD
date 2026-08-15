"""Suppliers and their regulatory documents (PRD §3.1)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_SUPPLIER_NOT_FOUND,
    ERR_DOCUMENT_NOT_FOUND,
    ERR_DUPLICATE_VALUE,
    ERR_SUPPLIER_INVALID_STATE,
    ERR_REQUIRED_DOCUMENTS_NOT_VERIFIED,
    ERR_SUPPLIER_SCORE_BELOW_THRESHOLD,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_DOCUMENT_INVALID_STATE,
    ERR_INVALID_WINDOW,
    ERR_DOC_VALIDITY_OVERLAP,
)
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list
from services import domain
from util import fmt_dt
from validate import get_body, req_str, req_enum, req_dt, paginate

bp = Blueprint("suppliers", __name__)

ANY = ALL_ROLES


def _get_supplier(supplier_id: str) -> dict:
    supplier = db["suppliers"].get(supplier_id)
    if supplier is None:
        raise_error(ERR_SUPPLIER_NOT_FOUND, f"supplier {supplier_id} does not exist")
    return supplier


def _get_document(supplier: dict, doc_id: str) -> dict:
    doc = db["documents"].get(doc_id)
    if doc is None or doc["supplier_id"] != supplier["id"]:
        raise_error(ERR_DOCUMENT_NOT_FOUND, f"document {doc_id} does not exist under supplier {supplier['id']}")
    return doc


# ---------------------------------------------------------------------------
# Suppliers
# ---------------------------------------------------------------------------


@bp.route("/tissue-bank/suppliers", methods=["POST"])
def create_supplier():
    require_roles({"QualityManager"})
    body = get_body()
    legal_name = req_str(body, "legal_name")
    license_number = req_str(body, "license_number")
    # uniqueness: license_number unique across suppliers (structural rung)
    if any(s["license_number"] == license_number for s in db["suppliers"].values()):
        raise_error(ERR_DUPLICATE_VALUE, f"license_number {license_number} is already registered")
    supplier = {
        "legal_name": legal_name,
        "license_number": license_number,
        "status": "PENDING_QUALIFICATION",
        "suspended_at": None,
    }
    domain.stamp_new(supplier)
    db["suppliers"][supplier["id"]] = supplier
    return success_object(domain.supplier_json(supplier), status=201)


@bp.route("/tissue-bank/suppliers", methods=["GET"])
def list_suppliers():
    require_roles(ANY)
    status_filter = request.args.get("status")
    items = list(db["suppliers"].values())
    if status_filter is not None:
        items = [s for s in items if s["status"] == status_filter]
    items.sort(key=lambda s: (s["_created_dt"], s["license_number"], s["_seq"]))
    page, total, limit, offset = paginate(items)
    return success_list([domain.supplier_json(s) for s in page], total, limit, offset)


@bp.route("/tissue-bank/suppliers/<supplier_id>", methods=["GET"])
def get_supplier(supplier_id):
    require_roles(ANY)
    supplier = _get_supplier(supplier_id)
    return success_object(domain.supplier_json(supplier))


@bp.route("/tissue-bank/suppliers/<supplier_id>/approve", methods=["POST"])
def approve_supplier(supplier_id):
    caller = require_roles({"ComplianceOfficer"})
    supplier = _get_supplier(supplier_id)
    # state rung: approve is defined from PENDING_QUALIFICATION or SUSPENDED
    if supplier["status"] not in ("PENDING_QUALIFICATION", "SUSPENDED"):
        raise_error(
            ERR_SUPPLIER_INVALID_STATE,
            f"supplier status {supplier['status']} cannot be approved",
        )
    # compliance rung: required-document coverage
    if not domain.has_required_doc_coverage(supplier["id"]):
        raise_error(
            ERR_REQUIRED_DOCUMENTS_NOT_VERIFIED,
            "VERIFIED AATB_ACCREDITATION and FDA_REGISTRATION documents valid on or after the clock are required",
        )
    # structural rung: segregation of duties vs the most recently verified
    # required-type document
    required_docs = [
        d for d in db["documents"].values()
        if d["supplier_id"] == supplier["id"]
        and d["doc_type"] in domain.REQUIRED_DOC_TYPES
        and d["_verified_seq"] is not None
    ]
    if required_docs:
        most_recent = max(required_docs, key=lambda d: d["_verified_seq"])
        if most_recent["verified_by_user_id"] == caller.user_id:
            raise_error(
                ERR_SEGREGATION_OF_DUTIES,
                "approver must differ from the verifier of the most recently verified required-type document",
            )
    supplier["status"] = "QUALIFIED"
    domain.touch(supplier)
    return success_object(domain.supplier_json(supplier))


@bp.route("/tissue-bank/suppliers/<supplier_id>/suspend", methods=["POST"])
def suspend_supplier(supplier_id):
    require_roles({"ComplianceOfficer"})
    supplier = _get_supplier(supplier_id)
    if supplier["status"] != "QUALIFIED":
        raise_error(
            ERR_SUPPLIER_INVALID_STATE,
            f"supplier status {supplier['status']} cannot be suspended",
        )
    supplier["status"] = "SUSPENDED"
    supplier["suspended_at"] = fmt_dt(domain.CLOCK.now())
    domain.touch(supplier)
    return success_object(domain.supplier_json(supplier))


@bp.route("/tissue-bank/suppliers/<supplier_id>/reinstate", methods=["POST"])
def reinstate_supplier(supplier_id):
    require_roles({"ComplianceOfficer"})
    supplier = _get_supplier(supplier_id)
    if supplier["status"] != "SUSPENDED":
        raise_error(
            ERR_SUPPLIER_INVALID_STATE,
            f"supplier status {supplier['status']} cannot be reinstated",
        )
    if not domain.has_required_doc_coverage(supplier["id"]):
        raise_error(
            ERR_REQUIRED_DOCUMENTS_NOT_VERIFIED,
            "VERIFIED AATB_ACCREDITATION and FDA_REGISTRATION documents valid on or after the clock are required",
        )
    prov, _fin = domain.supplier_scores(supplier["id"])
    if prov < domain.SUSPENSION_THRESHOLD:
        raise_error(
            ERR_SUPPLIER_SCORE_BELOW_THRESHOLD,
            f"qualification_score_provisional {prov} is below the reinstatement threshold 60",
        )
    supplier["status"] = "QUALIFIED"
    domain.touch(supplier)
    return success_object(domain.supplier_json(supplier))


@bp.route("/tissue-bank/suppliers/<supplier_id>/disqualify", methods=["POST"])
def disqualify_supplier(supplier_id):
    require_roles({"ComplianceOfficer"})
    supplier = _get_supplier(supplier_id)
    if supplier["status"] not in ("PENDING_QUALIFICATION", "SUSPENDED"):
        raise_error(
            ERR_SUPPLIER_INVALID_STATE,
            f"supplier status {supplier['status']} cannot be disqualified",
        )
    supplier["status"] = "DISQUALIFIED"
    domain.touch(supplier)
    return success_object(domain.supplier_json(supplier))


# ---------------------------------------------------------------------------
# Supplier documents
# ---------------------------------------------------------------------------


@bp.route("/tissue-bank/suppliers/<supplier_id>/documents", methods=["GET"])
def list_documents(supplier_id):
    require_roles(ANY)
    supplier = _get_supplier(supplier_id)
    doc_type = request.args.get("doc_type")
    items = [d for d in db["documents"].values() if d["supplier_id"] == supplier["id"]]
    if doc_type is not None:
        items = [d for d in items if d["doc_type"] == doc_type]
    items.sort(key=lambda d: (d["_created_dt"], d["document_ref"], d["_seq"]))
    page, total, limit, offset = paginate(items)
    return success_list([domain.document_json(d) for d in page], total, limit, offset)


@bp.route("/tissue-bank/suppliers/<supplier_id>/documents", methods=["POST"])
def create_document(supplier_id):
    require_roles({"QualityManager"})
    supplier = _get_supplier(supplier_id)
    body = get_body()
    doc_type = req_enum(body, "doc_type", domain.DOC_TYPES)
    document_ref = req_str(body, "document_ref")
    valid_from = req_dt(body, "valid_from")
    valid_to = req_dt(body, "valid_to")
    if valid_to < valid_from:
        raise_error(ERR_INVALID_WINDOW, "valid_to must not fall before valid_from")
    # state rung: a DISQUALIFIED supplier accepts no further mutations
    if supplier["status"] == "DISQUALIFIED":
        raise_error(ERR_SUPPLIER_INVALID_STATE, "supplier is DISQUALIFIED")
    # structural rung: closed-interval overlap among SUBMITTED/VERIFIED docs of
    # the same supplier + doc_type (touching endpoints conflict)
    for other in db["documents"].values():
        if (
            other["supplier_id"] == supplier["id"]
            and other["doc_type"] == doc_type
            and other["status"] in ("SUBMITTED", "VERIFIED")
            and valid_from <= other["_valid_to"]
            and other["_valid_from"] <= valid_to
        ):
            raise_error(
                ERR_DOC_VALIDITY_OVERLAP,
                f"validity window overlaps existing {doc_type} document {other['document_ref']}",
            )
    doc = {
        "supplier_id": supplier["id"],
        "doc_type": doc_type,
        "document_ref": document_ref,
        "valid_from": fmt_dt(valid_from),
        "valid_to": fmt_dt(valid_to),
        "status": "SUBMITTED",
        "verified_by_user_id": None,
        "_valid_from": valid_from,
        "_valid_to": valid_to,
        "_verified_seq": None,
    }
    domain.stamp_new(doc)
    db["documents"][doc["id"]] = doc
    return success_object(domain.document_json(doc), status=201)


@bp.route("/tissue-bank/suppliers/<supplier_id>/documents/<doc_id>/verify", methods=["POST"])
def verify_document(supplier_id, doc_id):
    caller = require_roles({"QualityManager"})
    supplier = _get_supplier(supplier_id)
    doc = _get_document(supplier, doc_id)
    if doc["status"] != "SUBMITTED":
        raise_error(ERR_DOCUMENT_INVALID_STATE, f"document status {doc['status']} cannot be verified")
    doc["status"] = "VERIFIED"
    doc["verified_by_user_id"] = caller.user_id
    doc["_verified_seq"] = domain.next_seq()
    domain.touch(doc)
    return success_object(domain.document_json(doc))


@bp.route("/tissue-bank/suppliers/<supplier_id>/documents/<doc_id>/reject", methods=["POST"])
def reject_document(supplier_id, doc_id):
    require_roles({"QualityManager"})
    supplier = _get_supplier(supplier_id)
    doc = _get_document(supplier, doc_id)
    if doc["status"] != "SUBMITTED":
        raise_error(ERR_DOCUMENT_INVALID_STATE, f"document status {doc['status']} cannot be rejected")
    doc["status"] = "REJECTED"
    domain.touch(doc)
    return success_object(domain.document_json(doc))


# ---------------------------------------------------------------------------
# Supplier-scoped shipment / recall lists
# ---------------------------------------------------------------------------


@bp.route("/tissue-bank/suppliers/<supplier_id>/shipments", methods=["GET"])
def list_supplier_shipments(supplier_id):
    require_roles(ANY)
    supplier = _get_supplier(supplier_id)
    items = [sh for sh in db["shipments"].values() if sh["supplier_id"] == supplier["id"]]
    items.sort(key=lambda sh: (sh["_created_dt"], sh["_seq"]))
    page, total, limit, offset = paginate(items)
    return success_list([domain.shipment_json(sh) for sh in page], total, limit, offset)


@bp.route("/tissue-bank/suppliers/<supplier_id>/recalls", methods=["GET"])
def list_supplier_recalls(supplier_id):
    require_roles(ANY)
    supplier = _get_supplier(supplier_id)
    items = [r for r in db["recalls"].values() if r["supplier_id"] == supplier["id"]]
    items.sort(key=lambda r: (r["_created_dt"], r["_seq"]))
    page, total, limit, offset = paginate(items)
    return success_list([domain.recall_json(r) for r in page], total, limit, offset)
