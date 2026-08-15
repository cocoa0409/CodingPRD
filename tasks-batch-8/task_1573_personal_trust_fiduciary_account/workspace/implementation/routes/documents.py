"""TrustDocument CRUD + interpretation workflow."""

from flask import Blueprint, request

import db
from errors import (ApiError, ERR_VALIDATION, ERR_INVALID_STATE,
                    ERR_TRUST_NOT_ACTIVE, ERR_RESOURCE_NOT_FOUND)
from middleware import authenticate, require_role
from response import ok, ok_list
from serialize import document_json
from services import workflow
from services.workflow import find_or_404
from validation import get_body, validate, parse_pagination

bp = Blueprint("documents", __name__)

READ_ROLES = {"TrustOfficer", "TrustExecutive", "InvestmentManager",
              "TrustOperationsOfficer", "TaxSpecialist"}


@bp.route("/trusts/documents", methods=["POST"])
def create_document():
    _, role = authenticate()
    data = get_body()
    v = validate(data, [
        ("trust_id", "str", True),
        ("version_number", "int", True),
        ("prior_document_id", "str", False),
        ("summary", "str", False),
    ])
    if v["version_number"] < 1:
        raise ApiError(ERR_VALIDATION, 400, "version_number must be >= 1")
    # version_number unique per trust (priority 2 shape rule)
    trust = db.trusts.get(v["trust_id"])
    if trust is not None:
        for d in db.documents.values():
            if d["trust_id"] == trust["id"] and d["version_number"] == v["version_number"]:
                raise ApiError(ERR_VALIDATION, 400,
                               "version_number must be unique within the trust")
    require_role(role, {"TrustOfficer"})
    if trust is None:
        raise ApiError(ERR_RESOURCE_NOT_FOUND, 404,
                       "Trust not found: %s" % v["trust_id"])
    prior_id = v.get("prior_document_id")
    if prior_id is not None:
        find_or_404(db.documents, prior_id, "TrustDocument")
    d = workflow.new_entity()
    d.update({
        "trust_id": trust["id"],
        "version_number": v["version_number"],
        "prior_document_id": prior_id,
        "summary": v.get("summary"),
        "per_stirpes": None,
        "interpretation_notes": None,
        "status": "DRAFT",
        "submitted_at": None,
        "approved_at": None,
        "rejected_reason": None,
    })
    db.documents[d["id"]] = d
    return ok(document_json(d), status=201)


@bp.route("/trusts/documents", methods=["GET"])
def list_documents():
    _, role = authenticate()
    limit, offset = parse_pagination()
    require_role(role, READ_ROLES)
    filters = []
    for param in ("trust_id", "prior_document_id", "status"):
        val = request.args.get(param)
        if val is not None:
            filters.append((param, val))
    items, total = workflow.list_page(db.documents, filters, document_json,
                                      limit, offset)
    return ok_list(items, limit, offset, total)


@bp.route("/trusts/documents/<did>", methods=["GET"])
def get_document(did):
    _, role = authenticate()
    require_role(role, READ_ROLES)
    d = find_or_404(db.documents, did, "TrustDocument")
    return ok(document_json(d))


@bp.route("/trusts/documents/<did>/submit", methods=["POST"])
def submit_document(did):
    _, role = authenticate()
    get_body()
    require_role(role, {"TrustOfficer"})
    d = find_or_404(db.documents, did, "TrustDocument")
    if d["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409, "Document must be DRAFT to submit")
    trust = db.trusts.get(d["trust_id"])
    if trust is None or trust["status"] not in ("DRAFT", "UNDER_ACCEPTANCE_REVIEW", "ACTIVE"):
        raise ApiError(ERR_TRUST_NOT_ACTIVE, 409,
                       "Owning trust is not in a submittable status")
    d["status"] = "SUBMITTED"
    d["submitted_at"] = workflow.now_stamp()
    workflow.touch(d)
    return ok(document_json(d))


@bp.route("/trusts/documents/<did>/interpret", methods=["POST"])
def interpret_document(did):
    _, role = authenticate()
    data = get_body()
    v = validate(data, [
        ("per_stirpes", "bool", True),
        ("interpretation_notes", "str", True),
    ])
    require_role(role, {"TrustOfficer"})
    d = find_or_404(db.documents, did, "TrustDocument")
    if d["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, 409, "Document must be SUBMITTED to interpret")
    d["per_stirpes"] = v["per_stirpes"]
    d["interpretation_notes"] = v["interpretation_notes"]
    d["status"] = "INTERPRETED"
    workflow.touch(d)
    return ok(document_json(d))


@bp.route("/trusts/documents/<did>/approve", methods=["POST"])
def approve_document(did):
    _, role = authenticate()
    get_body()
    require_role(role, {"TrustExecutive"})
    d = find_or_404(db.documents, did, "TrustDocument")
    if d["status"] != "INTERPRETED":
        raise ApiError(ERR_INVALID_STATE, 409, "Document must be INTERPRETED to approve")
    # cascade: any other APPROVED document of the same trust -> SUPERSEDED
    for other in db.documents.values():
        if (other["trust_id"] == d["trust_id"] and other["id"] != d["id"]
                and other["status"] == "APPROVED"):
            other["status"] = "SUPERSEDED"
            workflow.touch(other)
    d["status"] = "APPROVED"
    d["approved_at"] = workflow.now_stamp()
    workflow.touch(d)
    return ok(document_json(d))


@bp.route("/trusts/documents/<did>/reject-interpretation", methods=["POST"])
def reject_document(did):
    _, role = authenticate()
    data = get_body()
    v = validate(data, [("rejected_reason", "str", True)])
    require_role(role, {"TrustExecutive"})
    d = find_or_404(db.documents, did, "TrustDocument")
    if d["status"] != "INTERPRETED":
        raise ApiError(ERR_INVALID_STATE, 409, "Document must be INTERPRETED to reject")
    d["status"] = "REJECTED"
    d["rejected_reason"] = v["rejected_reason"]
    workflow.touch(d)
    return ok(document_json(d))
