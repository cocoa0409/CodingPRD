"""Routes: data submissions — privilege review and controlled release
(PRD §3.6)."""

from flask import Blueprint, request

import db
import services as svc
from errors import (
    raise_err,
    ERR_AUDIT_CASE_NOT_FOUND, ERR_SCOPE_ITEM_NOT_FOUND,
    ERR_SUBMISSION_NOT_FOUND, ERR_AUDIT_CASE_INVALID_STATE,
    ERR_SUBMISSION_INVALID_STATE, ERR_SEGREGATION_OF_DUTIES_VIOLATION,
    ERR_PRIVILEGED_CONTENT_REQUIRES_WAIVER, ERR_SUBMISSION_SCOPE_MISMATCH,
    ERR_EMPTY_SUBMISSION_PACKAGE,
)
from middleware import require_role, ALL_ROLES
from response import success_object, success_list, paginate
from validation import body, req_string, req_str_array, req_bool

bp = Blueprint("evidence", __name__)


def _get_submission(sid):
    rec = db.submissions.get(sid)
    if rec is None:
        raise_err(ERR_SUBMISSION_NOT_FOUND, "DataSubmission not found")
    return rec


@bp.post("/sam/data-submissions")
def create_submission():
    user_id, _role = require_role(["SAMManager"])
    data = body()
    audit_case_id = req_string(data, "audit_case_id")
    label = req_string(data, "submission_label")
    covered = req_str_array(data, "covered_scope_item_ids")
    privileged = req_bool(data, "contains_privileged", default=False)
    case = db.audit_cases.get(audit_case_id)
    if case is None:
        raise_err(ERR_AUDIT_CASE_NOT_FOUND, "audit_case_id does not exist")
    items = []
    for iid in covered:
        it = db.scope_items.get(iid)
        if it is None:
            raise_err(ERR_SCOPE_ITEM_NOT_FOUND,
                      f"covered scope item {iid} does not exist")
        items.append(it)
    if case["status"] in svc.TERMINAL_CASE_STATES:
        raise_err(ERR_AUDIT_CASE_INVALID_STATE,
                  "Submissions cannot be prepared for a closed or withdrawn "
                  "case")
    for it in items:
        if it["audit_case_id"] != audit_case_id:
            raise_err(ERR_SUBMISSION_SCOPE_MISMATCH,
                      "A covered scope item belongs to a different audit "
                      "case")
    rec = svc.stamp_new({
        "audit_case_id": audit_case_id,
        "submission_label": label,
        "covered_scope_item_ids": list(covered),
        "contains_privileged": privileged,
        "prepared_by_user_id": user_id,
        "status": "DRAFT",
        "released_on": None,
        "released_exposure_cents": None,
        "return_reason": None,
    })
    db.submissions[rec["id"]] = rec
    return success_object(rec, 201)


@bp.get("/sam/audit-cases/<cid>/data-submissions")
def list_case_submissions(cid):
    _user_id, role = require_role(ALL_ROLES)
    if cid not in db.audit_cases:
        raise_err(ERR_AUDIT_CASE_NOT_FOUND, "AuditCase not found")
    records = [s for s in db.submissions.values() if s["audit_case_id"] == cid]
    status = request.args.get("status")
    if status is not None:
        records = [s for s in records if s["status"] == status]
    if role == "VendorAuditor":
        # External auditor sees only RELEASED rows (server-side filter).
        records = [s for s in records if s["status"] == "RELEASED"]
    page, total, limit, offset = paginate(records)
    return success_list(page, total, limit, offset)


@bp.post("/sam/data-submissions/<sid>/submit-for-review")
def submit_for_review(sid):
    require_role(["SAMManager"])
    rec = _get_submission(sid)
    if rec["status"] != "DRAFT":
        raise_err(ERR_SUBMISSION_INVALID_STATE,
                  "Only a DRAFT submission can be sent to privilege review")
    rec["status"] = "PRIVILEGE_REVIEW"
    svc.touch(rec)
    return success_object(rec)


@bp.post("/sam/data-submissions/<sid>/approve")
def approve_submission(sid):
    user_id, _role = require_role(["LegalCounsel"])
    rec = _get_submission(sid)
    if rec["status"] != "PRIVILEGE_REVIEW":
        raise_err(ERR_SUBMISSION_INVALID_STATE,
                  "Only a PRIVILEGE_REVIEW submission can be approved")
    if user_id == rec["prepared_by_user_id"]:
        raise_err(ERR_SEGREGATION_OF_DUTIES_VIOLATION,
                  "The approver must differ from the preparer")
    rec["status"] = "APPROVED"
    svc.touch(rec)
    return success_object(rec)


@bp.post("/sam/data-submissions/<sid>/return")
def return_submission(sid):
    require_role(["LegalCounsel"])
    data = body()
    reason = req_string(data, "return_reason")
    rec = _get_submission(sid)
    if rec["status"] != "PRIVILEGE_REVIEW":
        raise_err(ERR_SUBMISSION_INVALID_STATE,
                  "Only a PRIVILEGE_REVIEW submission can be returned")
    rec["status"] = "DRAFT"
    rec["return_reason"] = reason
    svc.touch(rec)
    return success_object(rec)


@bp.post("/sam/data-submissions/<sid>/release")
def release_submission(sid):
    user_id, _role = require_role(["LegalCounsel"])
    data = body()
    waiver = req_bool(data, "privilege_waiver_confirmed", default=False)
    rec = _get_submission(sid)
    if rec["status"] != "APPROVED":
        raise_err(ERR_SUBMISSION_INVALID_STATE,
                  "Only an APPROVED submission can be released")
    case = db.audit_cases[rec["audit_case_id"]]
    if case["status"] not in ("EVIDENCE_COLLECTION", "FINDINGS_REVIEW"):
        raise_err(ERR_AUDIT_CASE_INVALID_STATE,
                  "Submissions may only be released while the case is in "
                  "EVIDENCE_COLLECTION or FINDINGS_REVIEW")
    if user_id == rec["prepared_by_user_id"]:
        raise_err(ERR_SEGREGATION_OF_DUTIES_VIOLATION,
                  "The releaser must differ from the preparer")
    if rec["contains_privileged"] and not waiver:
        raise_err(ERR_PRIVILEGED_CONTENT_REQUIRES_WAIVER,
                  "Privileged content requires privilege_waiver_confirmed")
    confirmed = [db.scope_items[iid] for iid in rec["covered_scope_item_ids"]
                 if db.scope_items[iid]["scope_status"] == "CONFIRMED"]
    if not confirmed:
        raise_err(ERR_EMPTY_SUBMISSION_PACKAGE,
                  "At least one covered scope item must be CONFIRMED at "
                  "release")
    exposure = 0
    for it in confirmed:
        pos = svc.position_for_product(it["product_id"])
        exposure += pos["self_audit_exposure_cents"]
    rec["status"] = "RELEASED"
    rec["released_on"] = db.now_iso()
    rec["released_exposure_cents"] = exposure
    svc.touch(rec)
    svc.touch(case)
    return success_object(rec)
