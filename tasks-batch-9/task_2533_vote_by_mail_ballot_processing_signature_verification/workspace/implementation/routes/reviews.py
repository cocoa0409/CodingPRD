"""Signature review rounds and decision submission."""
from flask import Blueprint

import db
import lookups
import middleware as mw
import response
from constants import DECISIONS, SIGNATURE_MAX_ROUNDS
from errors import ApiError
from services import accountability, logbook, posture, signature

bp = Blueprint("reviews", __name__)

READ_ROLES = (
    "ElectionsAdmin",
    "ElectionsClerk",
    "CanvassSupervisor",
    "SignatureReviewer",
)


@bp.post("/return-envelopes/<envelope_id>/signature-reviews")
def open_review_round(envelope_id):
    mw.require_roles("ElectionsClerk")
    mw.body()
    env = lookups.envelope(envelope_id)
    election_rec = lookups.election_of_envelope(env)
    posture.require(election_rec, ("RECEIVING", "CANVASS_LOCKED"))

    if env["signature_status"] not in ("UNVERIFIED", "ESCALATED"):
        raise ApiError("ERR_ENVELOPE_SIGNATURE_STATE_INVALID")

    target_round = env["review_round_count"] + 1
    if target_round == 1 and env["custody_status"] != "SEALED":
        raise ApiError("ERR_ENVELOPE_CUSTODY_STATE_INVALID")
    if target_round > SIGNATURE_MAX_ROUNDS:
        raise ApiError("ERR_ENVELOPE_SIGNATURE_STATE_INVALID")

    reviewer_rec = signature.select_reviewer(env, target_round)

    review = db.make_record(
        db.signature_reviews,
        {
            "return_envelope_id": env["id"],
            "reviewer_id": reviewer_rec["id"],
            "review_round": target_round,
            "status": "ASSIGNED",
            "decision": None,
            "similarity_score": None,
            "confidence_score": None,
            "notes": None,
            "submitted_at": None,
        },
    )
    reviewer_rec["active_review_count"] += 1
    db.touch(reviewer_rec)

    env["signature_status"] = "PENDING_REVIEW"
    db.touch(env)
    return response.record_response(review, 201)


@bp.get("/signature-reviews/<review_id>")
def get_review(review_id):
    mw.require_roles(*READ_ROLES)
    return response.record_response(lookups.signature_review(review_id))


@bp.get("/signature-reviews")
def list_reviews():
    mw.require_roles(*READ_ROLES)
    limit, offset = mw.pagination()
    rows = mw.apply_filters(
        list(db.signature_reviews.values()),
        ["return_envelope_id", "reviewer_id", "status"],
    )
    return response.list_response(db.ordered(rows), limit, offset)


@bp.post("/signature-reviews/<review_id>/decision")
def submit_decision(review_id):
    actor = mw.require_roles("SignatureReviewer")
    payload = mw.body()
    decision = mw.require_enum(payload, "decision", DECISIONS)
    similarity_score = mw.optional_int(
        payload, "similarity_score", None, minimum=0, maximum=100
    )
    notes = mw.optional_string(payload, "notes", None)
    if decision in ("MATCH", "NO_MATCH") and similarity_score is None:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "Field 'similarity_score' is required for a %s decision." % decision,
        )
    if decision == "MISSING_SIGNATURE" and similarity_score is not None:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "Field 'similarity_score' is not accepted for a MISSING_SIGNATURE decision.",
        )

    review = lookups.signature_review(review_id)
    env = db.return_envelopes.get(review["return_envelope_id"])
    election_rec = lookups.election_of_envelope(env)
    posture.require(election_rec, ("RECEIVING", "CANVASS_LOCKED"))

    if review["status"] != "ASSIGNED":
        raise ApiError("ERR_REVIEW_ALREADY_SUBMITTED")
    if env is None or env["signature_status"] != "PENDING_REVIEW":
        raise ApiError("ERR_ENVELOPE_SIGNATURE_STATE_INVALID")

    if actor.user_id != review["reviewer_id"]:
        raise ApiError("ERR_NOT_ASSIGNED_REVIEWER")

    reviewer_rec = db.reviewers.get(review["reviewer_id"])
    if reviewer_rec is None:
        raise ApiError("ERR_REVIEWER_TRAINING_INVALID")
    if reviewer_rec["training_status"] not in ("TRAINED", "CERTIFIED_LEAD"):
        raise ApiError("ERR_REVIEWER_TRAINING_INVALID")
    expires = reviewer_rec["training_expires_at"]
    if expires is None or not expires > db.now():
        raise ApiError("ERR_REVIEWER_TRAINING_INVALID")

    voter_rec = lookups.voter_of_envelope(env)
    review["decision"] = decision
    review["similarity_score"] = similarity_score
    review["notes"] = notes
    review["confidence_score"] = signature.confidence_score(
        decision, similarity_score, env, voter_rec, reviewer_rec
    )
    review["submitted_at"] = db.now()
    review["status"] = "SUBMITTED"
    db.touch(review)

    reviewer_rec["active_review_count"] = max(0, reviewer_rec["active_review_count"] - 1)
    reviewer_rec["completed_review_count"] += 1
    db.touch(reviewer_rec)

    env["review_round_count"] += 1
    db.touch(env)

    logbook.append(
        election_rec,
        "SIGNATURE_DECISION",
        actor.role,
        actor.user_id,
        "ReturnEnvelope",
        env["id"],
        "Signature decision %s recorded for round %d." % (decision, review["review_round"]),
    )

    signature.resolve(env, review, election_rec, actor)
    accountability.recompute(election_rec)
    return response.record_response(review)
