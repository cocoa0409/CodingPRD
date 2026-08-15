"""RecruitmentFeeReview + Reimbursement endpoints."""
from flask import Blueprint, request
import db
from middleware import require_roles, ALL_BUSINESS_ROLES, get_pagination
from response import success_object, success_array
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
    ERR_OWNERSHIP_VIOLATION,
    ERR_AUDIT_INVALID_STATE,
    ERR_RECORD_ALREADY_EXISTS,
    ERR_REVIEW_INVALID_STATE,
    ERR_LINKED_GRIEVANCE_UNRESOLVED,
    ERR_GRIEVANCE_FACILITY_MISMATCH,
    ERR_REIMBURSEMENT_EXCEEDS_OUTSTANDING,
    ERR_REIMBURSEMENT_INVALID_STATE,
)
from services.utils import new_uuid
from services.scorecard import (
    compute_reimbursement_totals,
    recompute_review_balance,
)

bp = Blueprint("reviews", __name__)


def serialize_review(r):
    return {
        "id": r["id"],
        "audit_id": r["audit_id"],
        "workers_assessed": r["workers_assessed"],
        "fee_items": r["fee_items"],
        "linked_grievance_id": r.get("linked_grievance_id"),
        "total_reimbursement_cents": r["total_reimbursement_cents"],
        "reimbursed_cents": r["reimbursed_cents"],
        "outstanding_reimbursement_cents": r["outstanding_reimbursement_cents"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def serialize_reimbursement(r):
    return {
        "id": r["id"],
        "review_id": r["review_id"],
        "amount_cents": r["amount_cents"],
        "worker_ref": r.get("worker_ref"),
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


@bp.route("/audits/<audit_id>/recruitment-fee-reviews", methods=["POST"])
def create_review(audit_id):
    user_id, _ = require_roles("Auditor")
    body = request.get_json(silent=True) or {}
    workers_assessed = body.get("workers_assessed")
    fee_items = body.get("fee_items")
    linked_grievance_id = body.get("linked_grievance_id")
    if not isinstance(workers_assessed, int) or isinstance(workers_assessed, bool) or workers_assessed < 1:
        raise_err(ERR_INVALID_REQUEST, "workers_assessed must be an integer >= 1")
    if not isinstance(fee_items, list):
        raise_err(ERR_INVALID_REQUEST, "fee_items must be an array")
    audit = db.audits.get(audit_id)
    if not audit:
        raise_err(ERR_NOT_FOUND, "audit not found")
    if audit["status"] != "IN_PROGRESS":
        raise_err(ERR_AUDIT_INVALID_STATE, f"audit status is {audit['status']}")
    if user_id != audit["auditor_id"]:
        raise_err(ERR_OWNERSHIP_VIOLATION, "caller is not the audit's lead auditor")
    existing = next((r for r in db.recruitment_fee_reviews.values() if r["audit_id"] == audit_id), None)
    if existing is not None:
        raise_err(ERR_RECORD_ALREADY_EXISTS, "recruitment fee review already exists for this audit")
    # Linked grievance must exist (existence check for body-referenced id)
    if linked_grievance_id is not None:
        g = db.grievances.get(linked_grievance_id)
        if g is None:
            raise_err(ERR_NOT_FOUND, "linked grievance not found")
    review = {
        "id": new_uuid(),
        "audit_id": audit_id,
        "workers_assessed": workers_assessed,
        "fee_items": list(fee_items),
        "linked_grievance_id": linked_grievance_id,
        "total_reimbursement_cents": 0,
        "reimbursed_cents": 0,
        "outstanding_reimbursement_cents": 0,
        "status": "PENDING_CONFIRMATION",
        "created_at": db.get_clock(),
        "updated_at": db.get_clock(),
        "version": 1,
    }
    review["total_reimbursement_cents"] = compute_reimbursement_totals(review)
    review["reimbursed_cents"] = 0
    review["outstanding_reimbursement_cents"] = review["total_reimbursement_cents"]
    if len(fee_items) == 0:
        review["status"] = "CLEARED"
    db.recruitment_fee_reviews[review["id"]] = review
    return success_object(serialize_review(review), 201)


@bp.route("/audits/<audit_id>/recruitment-fee-reviews", methods=["GET"])
def list_audit_reviews(audit_id):
    require_roles(*ALL_BUSINESS_ROLES)
    audit = db.audits.get(audit_id)
    if not audit:
        raise_err(ERR_NOT_FOUND, "audit not found")
    limit, offset = get_pagination()
    items = [r for r in db.recruitment_fee_reviews.values() if r["audit_id"] == audit_id]
    items.sort(key=lambda r: r["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_array([serialize_review(r) for r in page], total, limit, offset)


@bp.route("/recruitment-fee-reviews/<rid>", methods=["GET"])
def get_review(rid):
    require_roles(*ALL_BUSINESS_ROLES)
    r = db.recruitment_fee_reviews.get(rid)
    if not r:
        raise_err(ERR_NOT_FOUND, "review not found")
    return success_object(serialize_review(r))


@bp.route("/recruitment-fee-reviews/<rid>/confirm-violation", methods=["POST"])
def confirm_violation(rid):
    require_roles("ComplianceOfficer")
    r = db.recruitment_fee_reviews.get(rid)
    if not r:
        raise_err(ERR_NOT_FOUND, "review not found")
    if r["status"] != "PENDING_CONFIRMATION":
        raise_err(ERR_REVIEW_INVALID_STATE, f"review status is {r['status']}")
    if r.get("linked_grievance_id"):
        g = db.grievances.get(r["linked_grievance_id"])
        if g is None:
            raise_err(ERR_NOT_FOUND, "linked grievance not found")
        if g["status"] != "RESOLVED":
            raise_err(ERR_LINKED_GRIEVANCE_UNRESOLVED,
                      "linked grievance is not RESOLVED")
        audit = db.audits.get(r["audit_id"])
        if audit and g["facility_id"] != audit["facility_id"]:
            raise_err(ERR_GRIEVANCE_FACILITY_MISMATCH,
                      "linked grievance belongs to a different facility")
    r["status"] = "VIOLATION_CONFIRMED"
    r["outstanding_reimbursement_cents"] = r["total_reimbursement_cents"]
    r["version"] += 1
    r["updated_at"] = db.get_clock()
    return success_object(serialize_review(r))


@bp.route("/recruitment-fee-reviews/<rid>/reimbursements", methods=["POST"])
def create_reimbursement(rid):
    require_roles("ComplianceOfficer")
    body = request.get_json(silent=True) or {}
    amount_cents = body.get("amount_cents")
    worker_ref = body.get("worker_ref")
    if not isinstance(amount_cents, int) or isinstance(amount_cents, bool):
        raise_err(ERR_INVALID_REQUEST, "amount_cents must be an integer")
    if amount_cents <= 0:
        raise_err(ERR_INVALID_REQUEST, "amount_cents must be > 0")
    r = db.recruitment_fee_reviews.get(rid)
    if not r:
        raise_err(ERR_NOT_FOUND, "review not found")
    if r["status"] != "VIOLATION_CONFIRMED":
        raise_err(ERR_REVIEW_INVALID_STATE, f"review status is {r['status']}")
    if amount_cents > r["outstanding_reimbursement_cents"]:
        raise_err(ERR_REIMBURSEMENT_EXCEEDS_OUTSTANDING,
                  "amount_cents exceeds outstanding balance")
    reimb = {
        "id": new_uuid(),
        "review_id": rid,
        "amount_cents": amount_cents,
        "worker_ref": worker_ref if isinstance(worker_ref, str) else None,
        "status": "RECORDED",
        "created_at": db.get_clock(),
        "updated_at": db.get_clock(),
        "version": 1,
    }
    db.reimbursements[reimb["id"]] = reimb
    recompute_review_balance(r)
    if r["outstanding_reimbursement_cents"] == 0:
        r["status"] = "REIMBURSED"
        r["version"] += 1
        r["updated_at"] = db.get_clock()
    return success_object(serialize_reimbursement(reimb), 201)


@bp.route("/recruitment-fee-reviews/<rid>/reimbursements", methods=["GET"])
def list_reimbursements(rid):
    require_roles(*ALL_BUSINESS_ROLES)
    r = db.recruitment_fee_reviews.get(rid)
    if not r:
        raise_err(ERR_NOT_FOUND, "review not found")
    limit, offset = get_pagination()
    status_f = request.args.get("status")
    items = [x for x in db.reimbursements.values() if x["review_id"] == rid]
    if status_f is not None:
        items = [x for x in items if x["status"] == status_f]
    items.sort(key=lambda x: x["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_array([serialize_reimbursement(x) for x in page], total, limit, offset)


@bp.route("/reimbursements/<rid>/reverse", methods=["POST"])
def reverse_reimbursement(rid):
    require_roles("ComplianceOfficer")
    r = db.reimbursements.get(rid)
    if not r:
        raise_err(ERR_NOT_FOUND, "reimbursement not found")
    if r["status"] != "RECORDED":
        raise_err(ERR_REIMBURSEMENT_INVALID_STATE, f"reimbursement status is {r['status']}")
    r["status"] = "REVERSED"
    r["version"] += 1
    r["updated_at"] = db.get_clock()
    review = db.recruitment_fee_reviews.get(r["review_id"])
    if review is not None:
        recompute_review_balance(review)
        if review["status"] == "REIMBURSED" and review["outstanding_reimbursement_cents"] > 0:
            review["status"] = "VIOLATION_CONFIRMED"
            review["version"] += 1
            review["updated_at"] = db.get_clock()
    return success_object(serialize_reimbursement(r))
