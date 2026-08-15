"""Eligibility review endpoints."""
from flask import Blueprint

import db
from auth import require_roles
from errors import ApiError
from response import ok_object, now_iso
from serializers import serialize_review
from services import sweep
from services.sweep import new_id, bump
from validators import get_body, req_enum, opt_str_or_null
from routes.members import get_member_or_404

bp = Blueprint("reviews", __name__)

CO = {"ComplianceOfficer"}


def _get_review_or_404(rid):
    r = db.reviews.get(rid)
    if r is None:
        raise ApiError("ERR_NOT_FOUND", f"eligibility review {rid} not found")
    return r


@bp.post("/credit-union/members/<mid>/eligibility-reviews")
def create_review(mid):
    uid, _ = require_roles(CO)
    body = get_body()
    # Tier 4: the endpoint accepts only MANUAL_FLAG
    reason = req_enum(body, "reason", {"MANUAL_FLAG"})
    member = get_member_or_404(mid)
    # Tier 7: member posture gate (GRACE_PERIOD accepted to enable late cure)
    if member["status"] not in ("ACTIVE", "GRACE_PERIOD"):
        raise ApiError("ERR_MEMBER_NOT_ACTIVE",
                       "member is not ACTIVE or in GRACE_PERIOD")
    review = {
        "id": new_id(),
        "member_id": mid,
        "reason": reason,
        "status": "OPEN",
        "flagged_by_user_id": uid,
        "decided_by_user_id": None,
        "resolution_note": None,
        "version": 1,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "_seq": db.next_seq(),
    }
    db.reviews[review["id"]] = review
    if member["status"] == "ACTIVE":
        member["status"] = "INELIGIBLE_UNDER_REVIEW"
        bump(member)
    return ok_object(serialize_review(review), 201)


@bp.post("/credit-union/eligibility-reviews/<rid>/cure")
def cure_review(rid):
    uid, _ = require_roles(CO)
    body = get_body()
    note_present, resolution_note = opt_str_or_null(body, "resolution_note")
    review = _get_review_or_404(rid)
    if review["status"] != "OPEN":
        raise ApiError("ERR_REVIEW_INVALID_STATE", "review is not OPEN")
    member = db.members.get(review["member_id"])
    if member is None or member["status"] not in ("INELIGIBLE_UNDER_REVIEW", "GRACE_PERIOD"):
        raise ApiError("ERR_REVIEW_INVALID_STATE",
                       "member posture is inconsistent with a cure")
    if uid == review["flagged_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "the deciding officer must differ from the flagging officer")
    review["status"] = "CURED"
    review["decided_by_user_id"] = uid
    if note_present:
        review["resolution_note"] = resolution_note
    bump(review)
    member["status"] = "ACTIVE"
    member["grace_end_date"] = None
    bump(member)
    return ok_object(serialize_review(review), 200)


@bp.post("/credit-union/eligibility-reviews/<rid>/confirm-ineligible")
def confirm_ineligible(rid):
    uid, _ = require_roles(CO)
    review = _get_review_or_404(rid)
    if review["status"] != "OPEN":
        raise ApiError("ERR_REVIEW_INVALID_STATE", "review is not OPEN")
    member = db.members.get(review["member_id"])
    if member is None or member["status"] != "INELIGIBLE_UNDER_REVIEW":
        raise ApiError("ERR_REVIEW_INVALID_STATE",
                       "member posture is inconsistent with confirming ineligibility")
    if uid == review["flagged_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "the deciding officer must differ from the flagging officer")
    review["status"] = "CONFIRMED_INELIGIBLE"
    review["decided_by_user_id"] = uid
    bump(review)
    member["status"] = "GRACE_PERIOD"
    member["grace_end_date"] = sweep.grace_end_for(db.clock.current_date())
    bump(member)
    return ok_object(serialize_review(review), 200)
