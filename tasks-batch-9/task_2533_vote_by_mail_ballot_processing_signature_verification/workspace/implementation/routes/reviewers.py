"""Signature reviewers and their training window."""
from flask import Blueprint

import db
import lookups
import middleware as mw
import response
from constants import PARTY_AFFILIATIONS, TRAINING_STATUSES, TRAINING_VALID_DAYS

bp = Blueprint("reviewers", __name__)


@bp.post("/reviewers")
def create_reviewer():
    mw.require_roles("ElectionsAdmin")
    payload = mw.body()
    full_name = mw.require_string(payload, "full_name")
    party_affiliation = mw.require_enum(payload, "party_affiliation", PARTY_AFFILIATIONS)
    training_status = mw.optional_enum(
        payload, "training_status", TRAINING_STATUSES, "UNTRAINED"
    )
    training_completed_at = mw.optional_datetime(payload, "training_completed_at", None)
    curriculum_version = mw.optional_string(payload, "curriculum_version", None)

    training_expires_at = None
    if training_completed_at is not None:
        training_expires_at = db.whole_second(
            db.add_days(training_completed_at, TRAINING_VALID_DAYS)
        )

    rec = db.make_record(
        db.reviewers,
        {
            "full_name": full_name,
            "party_affiliation": party_affiliation,
            "training_status": training_status,
            "training_completed_at": training_completed_at,
            "training_expires_at": training_expires_at,
            "curriculum_version": curriculum_version,
            "active_review_count": 0,
            "completed_review_count": 0,
        },
    )
    return response.record_response(rec, 201)


@bp.get("/reviewers/<reviewer_id>")
def get_reviewer(reviewer_id):
    mw.require_roles(
        "ElectionsAdmin", "ElectionsClerk", "CanvassSupervisor", "SignatureReviewer"
    )
    return response.record_response(lookups.reviewer(reviewer_id))


@bp.get("/reviewers")
def list_reviewers():
    mw.require_roles("ElectionsAdmin", "ElectionsClerk", "CanvassSupervisor")
    limit, offset = mw.pagination()
    rows = mw.apply_filters(
        list(db.reviewers.values()), ["training_status", "party_affiliation"]
    )
    return response.list_response(db.ordered(rows), limit, offset)


@bp.post("/reviewers/<reviewer_id>/training-completions")
def record_training_completion(reviewer_id):
    mw.require_roles("ElectionsAdmin")
    payload = mw.body()
    completed_at = mw.require_datetime(payload, "completed_at")
    curriculum_version = mw.require_string(payload, "curriculum_version")
    training_status = mw.optional_enum(
        payload, "training_status", TRAINING_STATUSES, "TRAINED"
    )
    rec = lookups.reviewer(reviewer_id)

    rec["training_status"] = training_status
    rec["training_completed_at"] = completed_at
    rec["training_expires_at"] = db.whole_second(
        db.add_days(completed_at, TRAINING_VALID_DAYS)
    )
    rec["curriculum_version"] = curriculum_version
    db.touch(rec)
    return response.record_response(rec)
