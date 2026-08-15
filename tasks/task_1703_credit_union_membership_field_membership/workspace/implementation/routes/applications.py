"""Membership application endpoints."""
from flask import Blueprint, request

import db
from auth import require_roles
from errors import ApiError
from response import ok_object, paginate, now_iso
from serializers import serialize_application
from services.sweep import new_id, bump
from validators import get_body, req_str, req_enum, req_date, req_doc_codes

bp = Blueprint("applications", __name__)

FAMILY_RELATIONSHIPS = {"SPOUSE", "CHILD", "PARENT", "SIBLING", "GRANDPARENT", "GRANDCHILD"}
MO_ROLES = {"MembershipOfficer"}
MO_CO_ROLES = {"MembershipOfficer", "ComplianceOfficer"}


def _get_application_or_404(aid):
    a = db.applications.get(aid)
    if a is None:
        raise ApiError("ERR_NOT_FOUND", f"membership application {aid} not found")
    return a


def _compute_docs_complete(app):
    app["docs_complete"] = all(c in app["documents_provided"] for c in app["required_documents"])


@bp.post("/credit-union/membership-applications")
def create_application():
    uid, _ = require_roles(MO_ROLES)
    body = get_body()
    # Tier 4: syntactic
    applicant_full_name = req_str(body, "applicant_full_name")
    date_of_birth = req_date(body, "date_of_birth")
    basis = req_enum(body, "basis", {"SEGMENT_MATCH", "FAMILY", "HOUSEHOLD"})
    documents_provided = req_doc_codes(body, "documents_provided")
    segment_id = None
    sponsor_member_id = None
    relationship = None
    if basis == "SEGMENT_MATCH":
        segment_id = req_str(body, "segment_id")
    elif basis == "FAMILY":
        sponsor_member_id = req_str(body, "sponsor_member_id")
        relationship = req_enum(body, "relationship_to_sponsor", FAMILY_RELATIONSHIPS)
    else:  # HOUSEHOLD
        sponsor_member_id = req_str(body, "sponsor_member_id")
        relationship = req_enum(body, "relationship_to_sponsor", {"HOUSEHOLD_MEMBER"})
    # Tier 5: existence
    segment = None
    sponsor = None
    if segment_id is not None:
        segment = db.segments.get(segment_id)
        if segment is None:
            raise ApiError("ERR_NOT_FOUND", f"segment {segment_id} not found")
    if sponsor_member_id is not None:
        sponsor = db.members.get(sponsor_member_id)
        if sponsor is None:
            raise ApiError("ERR_NOT_FOUND", f"sponsor member {sponsor_member_id} not found")
    # Tier 8: sponsor eligibility at filing
    if sponsor is not None and sponsor["status"] != "ACTIVE":
        raise ApiError("ERR_SPONSOR_NOT_ELIGIBLE", "sponsor member is not ACTIVE")
    # Tier 9: segment state
    if segment is not None and segment["status"] != "ACTIVE":
        raise ApiError("ERR_SEGMENT_NOT_ACTIVE", "referenced segment is not ACTIVE")
    if basis == "SEGMENT_MATCH":
        required_documents = list(segment["required_documents"])
    elif basis == "FAMILY":
        required_documents = ["GOVERNMENT_ID", "RELATIONSHIP_PROOF"]
    else:
        required_documents = ["GOVERNMENT_ID", "ADDRESS_PROOF"]
    app = {
        "id": new_id(),
        "applicant_full_name": applicant_full_name,
        "date_of_birth": date_of_birth,
        "basis": basis,
        "segment_id": segment_id,
        "sponsor_member_id": sponsor_member_id,
        "relationship_to_sponsor": relationship,
        "documents_provided": documents_provided,
        "required_documents": required_documents,
        "docs_complete": False,
        "requested_document_codes": [],
        "status": "UNDER_REVIEW",
        "filed_by_user_id": uid,
        "decided_by_user_id": None,
        "denial_reason": None,
        "resulting_member_id": None,
        "version": 1,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "_seq": db.next_seq(),
    }
    _compute_docs_complete(app)
    db.applications[app["id"]] = app
    return ok_object(serialize_application(app), 201)


@bp.get("/credit-union/membership-applications")
def list_applications():
    require_roles(MO_CO_ROLES)
    items = list(db.applications.values())
    for f in ("status", "segment_id", "sponsor_member_id", "resulting_member_id"):
        v = request.args.get(f)
        if v is not None:
            items = [a for a in items if a.get(f) == v]
    items.sort(key=lambda a: (a["created_at"], a["_seq"]))
    return paginate([serialize_application(a) for a in items])


@bp.get("/credit-union/membership-applications/<aid>")
def get_application(aid):
    require_roles(MO_CO_ROLES)
    return ok_object(serialize_application(_get_application_or_404(aid)), 200)


@bp.post("/credit-union/membership-applications/<aid>/request-documents")
def request_documents(aid):
    require_roles(MO_ROLES)
    body = get_body()
    codes = req_doc_codes(body, "requested_document_codes")
    app = _get_application_or_404(aid)
    if app["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_APPLICATION_INVALID_STATE",
                       "application is not UNDER_REVIEW")
    app["requested_document_codes"] = codes
    app["status"] = "DOCS_REQUESTED"
    bump(app)
    return ok_object(serialize_application(app), 200)


@bp.post("/credit-union/membership-applications/<aid>/submit-documents")
def submit_documents(aid):
    require_roles(MO_ROLES)
    body = get_body()
    new_docs = req_doc_codes(body, "documents_provided")
    app = _get_application_or_404(aid)
    if app["status"] != "DOCS_REQUESTED":
        raise ApiError("ERR_APPLICATION_INVALID_STATE",
                       "application is not DOCS_REQUESTED")
    merged = list(app["documents_provided"])
    for c in new_docs:
        if c not in merged:
            merged.append(c)
    app["documents_provided"] = merged
    _compute_docs_complete(app)
    app["status"] = "UNDER_REVIEW"
    bump(app)
    return ok_object(serialize_application(app), 200)


@bp.post("/credit-union/membership-applications/<aid>/approve")
def approve_application(aid):
    uid, _ = require_roles(MO_ROLES)
    app = _get_application_or_404(aid)
    if app["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_APPLICATION_INVALID_STATE",
                       "application is not UNDER_REVIEW")
    # Tier 8: documentation completeness, sponsor eligibility, segregation of duties
    if not app["docs_complete"]:
        raise ApiError("ERR_DOCUMENTATION_INCOMPLETE",
                       "required documents have not all been provided")
    if app["basis"] in ("FAMILY", "HOUSEHOLD"):
        sponsor = db.members.get(app["sponsor_member_id"])
        if sponsor is None or sponsor["status"] != "ACTIVE":
            raise ApiError("ERR_SPONSOR_NOT_ELIGIBLE", "sponsor member is not ACTIVE")
    if uid == app["filed_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "the deciding officer must differ from the filing officer")
    # Tier 9: segment state at approval
    if app["basis"] == "SEGMENT_MATCH":
        segment = db.segments.get(app["segment_id"])
        if segment is None or segment["status"] != "ACTIVE":
            raise ApiError("ERR_SEGMENT_NOT_ACTIVE", "referenced segment is not ACTIVE")
    member = {
        "id": new_id(),
        "application_id": app["id"],
        "full_name": app["applicant_full_name"],
        "date_of_birth": app["date_of_birth"],
        "eligibility_basis": app["basis"],
        "segment_id": app["segment_id"],
        "sponsor_member_id": app["sponsor_member_id"],
        "relationship_to_sponsor": app["relationship_to_sponsor"],
        "membership_effective_date": db.clock.current_date_str(),
        "status": "ACTIVE",
        "grace_end_date": None,
        "tier": "STANDARD",
        "last_tier_review_at": None,
        "mailing_address": None,
        "email": None,
        "phone": None,
        "version": 1,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "_seq": db.next_seq(),
    }
    db.members[member["id"]] = member
    app["status"] = "APPROVED"
    app["decided_by_user_id"] = uid
    app["resulting_member_id"] = member["id"]
    bump(app)
    return ok_object(serialize_application(app), 200)


@bp.post("/credit-union/membership-applications/<aid>/deny")
def deny_application(aid):
    uid, _ = require_roles(MO_ROLES)
    body = get_body()
    denial_reason = req_str(body, "denial_reason")
    app = _get_application_or_404(aid)
    if app["status"] not in ("UNDER_REVIEW", "DOCS_REQUESTED"):
        raise ApiError("ERR_APPLICATION_INVALID_STATE",
                       "application is not UNDER_REVIEW or DOCS_REQUESTED")
    if uid == app["filed_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "the deciding officer must differ from the filing officer")
    app["status"] = "DENIED"
    app["denial_reason"] = denial_reason
    app["decided_by_user_id"] = uid
    bump(app)
    return ok_object(serialize_application(app), 200)
