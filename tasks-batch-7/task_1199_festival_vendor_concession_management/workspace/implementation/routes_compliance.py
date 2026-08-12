"""Compliance fines (strikes) and performance reviews."""
from flask import Blueprint

import serialize
from calc import apply_strike_contagion, compute_review_scores
from store import db
from util import (body_json, err, get_or_404, list_response, new_id, opt_str,
                  req_enum, req_int, require_role, stamp_new, success, touch)

bp = Blueprint("compliance", __name__)

FINE_TYPES = ("WASTE_SORTING", "COMPOST_CONTAMINATION", "GREASE_DISPOSAL",
              "HEALTH_VIOLATION", "NO_SHOW_PENALTY")
FINE_READ_ROLES = ("FestivalDirector", "VendorManager", "OperationsLead",
                   "SustainabilityOfficer", "FinanceLead", "Vendor")
REVIEW_READ_ROLES = ("FestivalDirector", "VendorManager", "FinanceLead", "Vendor")


def _vendor_of_assignment(assignment):
    return db.applications[assignment["application_id"]]["vendor_id"]


# ---------------------------------------------------------------------------
# Compliance fines
# ---------------------------------------------------------------------------

@bp.route("/compliance-fines", methods=["POST"])
def create_fine():
    uid, _ = require_role("SustainabilityOfficer", "FestivalDirector")
    b = body_json()
    # (4) Body FK existence.
    assignment = None
    if b.get("assignment_id") is not None:
        assignment = get_or_404(db.assignments, b.get("assignment_id"),
                                "ERR_ASSIGNMENT_NOT_FOUND", "Assignment")
    # (8) Request shape.
    fine_type = req_enum(b, "type", FINE_TYPES)
    amount = req_int(b, "amount_cents")
    description = opt_str(b, "description")
    if assignment is None:
        get_or_404(db.assignments, b.get("assignment_id"),
                   "ERR_ASSIGNMENT_NOT_FOUND", "Assignment")
    # (13) Fiscal: positive amount.
    if amount < 1:
        err("ERR_INVALID_AMOUNT", 400, "amount_cents must be >= 1")
    fine = stamp_new({
        "id": new_id(),
        "_seq": db.next_seq(),
        "assignment_id": assignment["id"],
        "festival_id": assignment["festival_id"],
        "type": fine_type,
        "amount_cents": amount,
        "description": description,
        "status": "ISSUED",
        "created_by_user_id": uid,
        "waived_by_user_id": None,
    })
    db.fines[fine["id"]] = fine
    return success(serialize.serialize_fine(fine), 201)


@bp.route("/compliance-fines", methods=["GET"])
def list_fines():
    require_role(*FINE_READ_ROLES)
    return list_response(list(db.fines.values()), serialize.serialize_fine, {
        "assignment_id": "assignment_id",
        "festival_id": "festival_id",
        "status": "status",
        "type": "type",
    })


@bp.route("/compliance-fines/<fineId>", methods=["GET"])
def get_fine(fineId):
    require_role(*FINE_READ_ROLES)
    fine = get_or_404(db.fines, fineId, "ERR_FINE_NOT_FOUND", "Fine")
    return success(serialize.serialize_fine(fine))


@bp.route("/compliance-fines/<fineId>/respond", methods=["POST"])
def respond_fine(fineId):
    uid, _ = require_role("Vendor")
    fine = get_or_404(db.fines, fineId, "ERR_FINE_NOT_FOUND", "Fine")
    assignment = db.assignments[fine["assignment_id"]]
    if _vendor_of_assignment(assignment) != uid:
        err("ERR_NOT_RESOURCE_OWNER", 403,
            "A vendor may only respond to its own fines")
    b = body_json()
    response = req_enum(b, "response", ("ACKNOWLEDGED", "DISPUTED"))
    if fine["status"] == "ISSUED" and response in ("ACKNOWLEDGED", "DISPUTED"):
        fine["status"] = response
    elif fine["status"] == "DISPUTED" and response == "ACKNOWLEDGED":
        fine["status"] = "ACKNOWLEDGED"
    else:
        err("ERR_INVALID_STATE_TRANSITION", 409,
            f"respond({response}) is not permitted from {fine['status']}")
    touch(fine)
    return success(serialize.serialize_fine(fine))


@bp.route("/compliance-fines/<fineId>/waive", methods=["POST"])
def waive_fine(fineId):
    uid, _ = require_role("FestivalDirector")
    fine = get_or_404(db.fines, fineId, "ERR_FINE_NOT_FOUND", "Fine")
    # (3) Segregation of duties: waver != issuer unless the issuer is 'system'.
    if fine["created_by_user_id"] != "system" and uid == fine["created_by_user_id"]:
        err("ERR_SOD_FINE_WAIVER", 403,
            "The issuer of a fine may not waive it")
    if fine["status"] not in ("ISSUED", "ACKNOWLEDGED", "DISPUTED"):
        err("ERR_INVALID_STATE_TRANSITION", 409,
            f"waive is not permitted from {fine['status']}")
    fine["status"] = "WAIVED"
    fine["waived_by_user_id"] = uid
    touch(fine)
    return success(serialize.serialize_fine(fine))


@bp.route("/compliance-fines/<fineId>/mark-paid", methods=["POST"])
def mark_fine_paid(fineId):
    require_role("FinanceLead")
    fine = get_or_404(db.fines, fineId, "ERR_FINE_NOT_FOUND", "Fine")
    if fine["status"] != "ACKNOWLEDGED":
        err("ERR_INVALID_STATE_TRANSITION", 409,
            f"mark-paid is not permitted from {fine['status']}")
    fine["status"] = "PAID"
    touch(fine)
    assignment = db.assignments[fine["assignment_id"]]
    vendor = db.vendors[_vendor_of_assignment(assignment)]
    apply_strike_contagion(vendor)
    return success(serialize.serialize_fine(fine))


# ---------------------------------------------------------------------------
# Performance reviews
# ---------------------------------------------------------------------------

@bp.route("/performance-reviews", methods=["GET"])
def list_reviews():
    require_role(*REVIEW_READ_ROLES)
    return list_response(list(db.reviews.values()), serialize.serialize_review, {
        "assignment_id": "assignment_id",
        "festival_id": "festival_id",
        "vendor_id": "vendor_id",
        "status": "status",
    })


@bp.route("/performance-reviews/<reviewId>", methods=["GET"])
def get_review(reviewId):
    require_role(*REVIEW_READ_ROLES)
    review = get_or_404(db.reviews, reviewId, "ERR_REVIEW_NOT_FOUND", "Review")
    return success(serialize.serialize_review(review))


@bp.route("/performance-reviews/<reviewId>/compute-score", methods=["POST"])
def compute_score(reviewId):
    require_role("VendorManager")
    review = get_or_404(db.reviews, reviewId, "ERR_REVIEW_NOT_FOUND", "Review")
    if review["status"] != "PENDING":
        err("ERR_INVALID_STATE_TRANSITION", 409,
            f"compute-score is not permitted from {review['status']}")
    compute_review_scores(review)
    return success(serialize.serialize_review(review))


@bp.route("/performance-reviews/<reviewId>/issue-invitation", methods=["POST"])
def issue_invitation(reviewId):
    require_role("VendorManager")
    review = get_or_404(db.reviews, reviewId, "ERR_REVIEW_NOT_FOUND", "Review")
    if review["status"] == "INELIGIBLE":
        err("ERR_SCORE_THRESHOLD_NOT_MET", 409,
            "The review's official_score is below the return threshold")
    if review["status"] != "SCORED":
        err("ERR_INVALID_STATE_TRANSITION", 409,
            f"issue-invitation is not permitted from {review['status']}")
    review["status"] = "INVITED"
    touch(review)
    return success(serialize.serialize_review(review))


@bp.route("/performance-reviews/<reviewId>/respond", methods=["POST"])
def respond_review(reviewId):
    uid, _ = require_role("Vendor")
    review = get_or_404(db.reviews, reviewId, "ERR_REVIEW_NOT_FOUND", "Review")
    if review["vendor_id"] != uid:
        err("ERR_NOT_RESOURCE_OWNER", 403,
            "A vendor may only respond to its own review")
    b = body_json()
    response = req_enum(b, "response", ("ACCEPTED", "DECLINED"))
    if review["status"] != "INVITED":
        err("ERR_INVALID_STATE_TRANSITION", 409,
            f"respond is not permitted from {review['status']}")
    review["status"] = response
    touch(review)
    return success(serialize.serialize_review(review))
