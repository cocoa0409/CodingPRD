"""Validation evidence and closure requests (PRD §3.7)."""
from flask import Blueprint, request

from calc import maybe_advance_exam, recompute_exam
from db import db, new_id, next_seq, now, touch
from errors import (ApiError, ERR_ALREADY_TERMINAL, ERR_INVALID_REFERENCE,
                    ERR_INVALID_REQUEST, ERR_INVALID_STATE,
                    ERR_SEGREGATION_OF_DUTIES)
from middleware import auth, require_role, reviewer_gate
from response import ok_obj
from routes_remediation import _cert_gate, _occ, _operative_plan
from serializers import ser_closure, ser_evidence
from util import enum_filter, get_or_404, list_page, payload, req_enum, req_str

bp = Blueprint("evidence", __name__)

OWNER = "RemediationOwner"
REVIEWER = "ComplianceReviewer"
EVIDENCE_TYPES = ["DOCUMENT_PACKAGE", "TEST_RESULTS", "INTERNAL_AUDIT_REPORT",
                  "THIRD_PARTY_ATTESTATION"]
REVIEW_STATUSES = ["PENDING", "SUFFICIENT", "INSUFFICIENT"]
CLOSURE_STATUSES = ["PENDING", "APPROVED", "REJECTED"]


# ------------------------------------------------------------- evidence
@bp.post("/regulatory-exams/issues/<iid>/validation-evidence")
def create_evidence(iid):
    auth_pair = auth()
    require_role(auth_pair[1], OWNER)
    issue = get_or_404(db.issues, iid)
    p = payload()
    # (12) referential: submitted_by_user_id -> BankOfficer
    sub_by = p.get("submitted_by_user_id")
    if sub_by is not None:
        if not isinstance(sub_by, str):
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "submitted_by_user_id must be a string")
        if sub_by not in db.officers:
            raise ApiError(ERR_INVALID_REFERENCE, 422,
                           "submitted_by_user_id does not reference a BankOfficer")
    # (14) shape
    sub_by = req_str(p, "submitted_by_user_id")
    etype = req_enum(p, "evidence_type", EVIDENCE_TYPES)
    manifest = p.get("artifact_manifest")
    if not isinstance(manifest, list):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "artifact_manifest must be an array")
    for a in manifest:
        if not isinstance(a, dict):
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "artifact_manifest entries must be objects")
        for k in ("artifact_id", "name", "sha256"):
            if not isinstance(a.get(k), str) or not a.get(k):
                raise ApiError(ERR_INVALID_REQUEST, 400,
                               "artifact entry missing %s" % k)
    rec = {"id": new_id(), "issue_id": iid, "evidence_type": etype,
           "artifact_manifest": manifest, "submitted_by_user_id": sub_by,
           "review_status": "PENDING", "review_notes": None,
           "created_at": now(), "updated_at": now(), "version": 1,
           "_seq": next_seq()}
    db.evidences[rec["id"]] = rec
    touch(issue)
    return ok_obj(ser_evidence(rec), 201)


@bp.get("/regulatory-exams/issues/<iid>/validation-evidence")
def list_evidence_for_issue(iid):
    auth()
    get_or_404(db.issues, iid)
    rs = enum_filter("review_status", REVIEW_STATUSES)
    rows = [e for e in db.evidences.values()
            if e["issue_id"] == iid
            and (rs is None or e["review_status"] == rs)]
    return list_page(rows, ser_evidence)


@bp.get("/regulatory-exams/validation-evidence")
def list_evidence_portfolio():
    auth()
    sub = request.args.get("submitted_by_user_id")
    rows = [e for e in db.evidences.values()
            if sub is None or e["submitted_by_user_id"] == sub]
    return list_page(rows, ser_evidence)


@bp.get("/regulatory-exams/validation-evidence/<eid>")
def get_evidence(eid):
    auth()
    return ok_obj(ser_evidence(get_or_404(db.evidences, eid)))


@bp.post("/regulatory-exams/validation-evidence/<eid>/mark-sufficient")
def mark_sufficient(eid):
    uid, role = auth()
    require_role(role, REVIEWER)
    reviewer_gate(uid)
    ev = get_or_404(db.evidences, eid)
    if ev["review_status"] in ("SUFFICIENT", "INSUFFICIENT"):
        raise ApiError(ERR_ALREADY_TERMINAL, 409, "evidence already reviewed")
    ev["review_status"] = "SUFFICIENT"
    touch(ev)
    return ok_obj(ser_evidence(ev))


@bp.post("/regulatory-exams/validation-evidence/<eid>/mark-insufficient")
def mark_insufficient(eid):
    uid, role = auth()
    require_role(role, REVIEWER)
    reviewer_gate(uid)
    ev = get_or_404(db.evidences, eid)
    if ev["review_status"] in ("SUFFICIENT", "INSUFFICIENT"):
        raise ApiError(ERR_ALREADY_TERMINAL, 409, "evidence already reviewed")
    notes = req_str(payload(), "review_notes")
    ev["review_status"] = "INSUFFICIENT"
    ev["review_notes"] = notes
    touch(ev)
    return ok_obj(ser_evidence(ev))


# -------------------------------------------------------- closure requests
@bp.get("/regulatory-exams/issues/<iid>/closure-requests")
def list_closures_for_issue(iid):
    auth()
    get_or_404(db.issues, iid)
    status = enum_filter("status", CLOSURE_STATUSES)
    rows = [c for c in db.closures.values()
            if c["issue_id"] == iid and (status is None or c["status"] == status)]
    return list_page(rows, ser_closure)


@bp.get("/regulatory-exams/closure-requests")
def list_closures_portfolio():
    auth()
    evid = request.args.get("validation_evidence_id")
    rev = request.args.get("reviewed_by_user_id")
    rows = [c for c in db.closures.values()
            if (evid is None or c["validation_evidence_id"] == evid)
            and (rev is None or c["reviewed_by_user_id"] == rev)]
    return list_page(rows, ser_closure)


@bp.get("/regulatory-exams/closure-requests/<cid>")
def get_closure(cid):
    auth()
    return ok_obj(ser_closure(get_or_404(db.closures, cid)))


def _sod_gate(uid, issue):
    """Segregation of duties (priority 5): the acting reviewer id must not
    equal the owner_user_id of the issue's operative remediation plan."""
    plan = _operative_plan(issue["id"])
    if plan is not None and plan["owner_user_id"] == uid:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, 422,
                       "reviewer owns the issue's active remediation plan")


@bp.post("/regulatory-exams/closure-requests/<cid>/approve")
def approve_closure(cid):
    uid, role = auth()
    require_role(role, REVIEWER)
    reviewer_gate(uid)
    cr = get_or_404(db.closures, cid)
    if cr["status"] in ("APPROVED", "REJECTED"):
        raise ApiError(ERR_ALREADY_TERMINAL, 409,
                       "closure request already adjudicated")
    issue = db.issues[cr["issue_id"]]
    # (5) segregation of duties
    _sod_gate(uid, issue)
    # (6) certification gate
    _cert_gate(uid, issue)
    # (7) optimistic concurrency on the parent issue
    p = payload()
    _occ(p, "expected_issue_version", issue["version"])
    # evidence linkage must still stand SUFFICIENT at decision time
    ev = db.evidences.get(cr["validation_evidence_id"])
    if ev is None or ev["review_status"] != "SUFFICIENT":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "referenced evidence is no longer SUFFICIENT")
    cr["status"] = "APPROVED"
    cr["reviewed_by_user_id"] = uid
    touch(cr)
    issue["status"] = "CLOSED"
    issue["closed_at"] = now()
    touch(issue)
    exam = db.exams[issue["examination_id"]]
    recompute_exam(exam)
    touch(exam)
    maybe_advance_exam(exam)
    return ok_obj(ser_closure(cr))


@bp.post("/regulatory-exams/closure-requests/<cid>/reject")
def reject_closure(cid):
    uid, role = auth()
    require_role(role, REVIEWER)
    reviewer_gate(uid)
    cr = get_or_404(db.closures, cid)
    if cr["status"] in ("APPROVED", "REJECTED"):
        raise ApiError(ERR_ALREADY_TERMINAL, 409,
                       "closure request already adjudicated")
    issue = db.issues[cr["issue_id"]]
    # (5) segregation of duties
    _sod_gate(uid, issue)
    reason = req_str(payload(), "rejection_reason")
    cr["status"] = "REJECTED"
    cr["reviewed_by_user_id"] = uid
    cr["rejection_reason"] = reason
    touch(cr)
    issue["status"] = "IN_PROGRESS"
    touch(issue)
    exam = db.exams[issue["examination_id"]]
    touch(exam)
    return ok_obj(ser_closure(cr))
