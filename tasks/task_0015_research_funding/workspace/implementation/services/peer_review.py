"""PeerReview — immutable append-only review records."""

from common import require_field, sort_by_created_at, stamp_immutable
from db import db
from errors import ERR_INVALID_INPUT, raise_error


VALID_RECS = {"APPROVE", "REJECT", "REVISE"}


def serialize_review(r):
    return {
        "id": r["id"],
        "project_id": r["project_id"],
        "reviewer_id": r["reviewer_id"],
        "score": r["score"],
        "recommendation": r["recommendation"],
        "comments": r["comments"],
        "created_at": r["created_at"],
    }


def create_review(project_id, body):
    reviewer_id = require_field(body, "reviewer_id", str)
    score = require_field(body, "score", int)
    if not (0 <= score <= 100):
        raise_error(ERR_INVALID_INPUT, "score must be 0..100")
    recommendation = require_field(body, "recommendation", str)
    if recommendation not in VALID_RECS:
        raise_error(ERR_INVALID_INPUT, "invalid recommendation")
    comments = require_field(body, "comments", str)

    rid = db.new_id()
    rec = {
        "id": rid,
        "project_id": project_id,
        "reviewer_id": reviewer_id,
        "score": score,
        "recommendation": recommendation,
        "comments": comments,
    }
    stamp_immutable(rec)
    db.peer_reviews[rid] = rec
    return rec


def list_reviews(project_id):
    items = [r for r in db.peer_reviews.values() if r["project_id"] == project_id]
    return sort_by_created_at(items)
