"""PRD 3.7 — travel training referrals and fixed-route competency."""

from flask import Blueprint

import lookups
import mirrors
import owners
import serializers
import shapes
from auth import require
from envelope import created, ok
from errors import ApiError
from store import base_record, date_of, db, now, plus_days, today, touch

bp = Blueprint("training", __name__)

REFERRAL_RESPONSE_WINDOW_DAYS = 14
TRAINABLE_CATEGORIES = ("CONDITIONAL", "TEMPORARY")
COMPETENCY_PASS_SCORE = 80


def _trainable(applicant_id):
    """PRD 3.7: the rider must hold an ISSUED determination whose category is
    CONDITIONAL or TEMPORARY."""
    det = lookups.issued_determination_of(applicant_id)
    return det is not None and det["category"] in TRAINABLE_CATEGORIES


@bp.post("/applicants/<applicant_id>/travel-training-referrals")
@require(("EligibilitySpecialist", "TravelTrainer", "AccessibilityOfficeAdmin"))
def refer_to_training(applicant_id):
    applicant = lookups.applicant(applicant_id)
    payload = shapes.body()
    determination = None
    if payload.get("determination_id") is not None:
        determination = lookups.determination(payload["determination_id"])
    referral_reason = shapes.req_enum(payload, "referral_reason", shapes.REFERRAL_REASONS)

    if not _trainable(applicant["id"]):
        raise ApiError("ERR_CATEGORY_NOT_TRAINABLE")

    rec = base_record()
    rec.update(
        {
            "applicant_id": applicant["id"],
            "determination_id": None if determination is None else determination["id"],
            "referral_reason": referral_reason,
            "status": "REFERRED",
            "referral_response_deadline_date": plus_days(
                date_of(now()), REFERRAL_RESPONSE_WINDOW_DAYS
            ),
            "fixed_route_competency_score": None,
            "completed_at": None,
            "withdrawal_reason": None,
        }
    )
    db.referrals[rec["id"]] = rec
    return created(serializers.referral(rec))


@bp.post("/travel-training-referrals/<referral_id>/response")
@require(("Applicant", "TravelTrainer"), ownership=owners.referral_path)
def respond_to_referral(referral_id):
    rec = lookups.referral(referral_id)
    payload = shapes.body()
    decision = shapes.req_enum(payload, "decision", shapes.REFERRAL_DECISIONS)

    if rec["status"] != "REFERRED":
        raise ApiError("ERR_REFERRAL_STATE_INVALID")
    deadline = rec["referral_response_deadline_date"]
    if deadline is not None and today() > deadline:
        raise ApiError("ERR_RESPONSE_WINDOW_CLOSED")

    if decision == "ENROLLED":
        # PRD 3.7: the category guard is re-checked at enrolment time.
        if not _trainable(rec["applicant_id"]):
            raise ApiError("ERR_CATEGORY_NOT_TRAINABLE")
        rec["status"] = "ENROLLED"
    else:
        rec["status"] = "DECLINED"
    touch(rec)
    return ok(serializers.referral(rec))


@bp.post("/travel-training-referrals/<referral_id>/complete")
@require(("TravelTrainer",))
def complete_referral(referral_id):
    rec = lookups.referral(referral_id)
    payload = shapes.body()
    score = shapes.req_int(payload, "fixed_route_competency_score", minimum=0, maximum=100)

    if rec["status"] != "ENROLLED":
        raise ApiError("ERR_REFERRAL_STATE_INVALID")

    rec["fixed_route_competency_score"] = score
    rec["completed_at"] = now()
    rec["status"] = "COMPLETED"
    touch(rec)

    if score >= COMPETENCY_PASS_SCORE:
        mirrors.sync_determination_competency(rec["applicant_id"])
    applicant = db.applicants.get(rec["applicant_id"])
    if applicant is not None:
        touch(applicant)
    return ok(serializers.referral(rec))
