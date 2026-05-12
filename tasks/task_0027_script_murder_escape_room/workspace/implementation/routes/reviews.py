"""Review routes."""
from flask import Blueprint

from db import store, make_common, bump, MAX_MODERATION_ROUNDS, SPAM_SIGNAL_HARD_BLOCK
from middleware import require_role
from response import success_object
from validators import (
    get_json_body, require_int, optional_int, require_string, require_enum,
)
from errors import (
    raise_error,
    ERR_BOOKING_NOT_FOUND, ERR_REVIEW_NOT_FOUND, ERR_INVALID_REQUEST,
    ERR_REVIEW_NOT_ELIGIBLE, ERR_REVIEW_DUPLICATE, ERR_REVIEW_REVISION_LIMIT,
    ERR_REVIEW_ALREADY_MODERATED, ERR_INSUFFICIENT_PERMISSIONS,
)
from audit import write_audit
from services import review_service

reviews_bp = Blueprint("reviews", __name__)


def review_view(r: dict) -> dict:
    return {
        "id": r["id"],
        "booking_id": r["booking_id"],
        "author_player_id": r["author_player_id"],
        "theme_score": r.get("theme_score"),
        "host_score": r.get("host_score"),
        "venue_score": r.get("venue_score"),
        "comment": r.get("comment"),
        "spam_signal_count": r.get("spam_signal_count", 0),
        "moderation_round": r.get("moderation_round", 0),
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


@reviews_bp.route("/bookings/<booking_id>/reviews", methods=["POST"])
def submit_review(booking_id):
    user_id, role = require_role("Player")
    b = store.bookings.get(booking_id)
    if not b:
        raise_error(ERR_BOOKING_NOT_FOUND, "booking not found")
    if user_id != b["lead_player_id"]:
        raise_error(ERR_INSUFFICIENT_PERMISSIONS, "not own booking")
    if b["status"] != "SETTLED":
        raise_error(ERR_REVIEW_NOT_ELIGIBLE, "booking not SETTLED")
    # Duplicate
    for r in store.reviews.values():
        if r["booking_id"] == booking_id and r["author_player_id"] == user_id:
            raise_error(ERR_REVIEW_DUPLICATE, "review already exists")

    body = get_json_body()
    theme_score = require_int(body, "theme_score", 1, 5)
    host_score = optional_int(body, "host_score", 1, 5, default=None)
    venue_score = require_int(body, "venue_score", 1, 5)
    comment = body.get("comment", "")
    if comment is None:
        comment = ""
    if not isinstance(comment, str) or len(comment) > 2000:
        raise_error(ERR_INVALID_REQUEST, "comment must be string up to 2000 chars")

    r = make_common({
        "booking_id": booking_id,
        "author_player_id": user_id,
        "theme_score": theme_score,
        "host_score": host_score,
        "venue_score": venue_score,
        "comment": comment,
        "spam_signal_count": 0,
        "moderation_round": 0,
        "status": "PENDING_MODERATION",
    })
    store.reviews[r["id"]] = r

    # Spam score
    count = review_service.compute_spam_signal_count(r, is_resubmit=False)
    r["spam_signal_count"] = count

    write_audit(user_id, role, "Review", r["id"], "REVIEW_SUBMITTED", r)

    if count >= SPAM_SIGNAL_HARD_BLOCK:
        r["status"] = "REJECTED"
        bump(r)
        write_audit(user_id, role, "Review", r["id"], "REVIEW_REJECTED", r)

    return success_object(review_view(r), 201)


@reviews_bp.route("/reviews/<review_id>", methods=["PATCH"])
def revise_review(review_id):
    user_id, role = require_role("Player")
    r = store.reviews.get(review_id)
    if not r:
        raise_error(ERR_REVIEW_NOT_FOUND, "review not found")
    if user_id != r["author_player_id"]:
        raise_error(ERR_INSUFFICIENT_PERMISSIONS, "not own review")
    if r["status"] != "REJECTED":
        raise_error(ERR_INVALID_REQUEST, "review not REJECTED")
    if int(r.get("moderation_round", 0)) >= MAX_MODERATION_ROUNDS:
        raise_error(ERR_REVIEW_REVISION_LIMIT, "moderation round at limit")
    body = get_json_body()
    if "comment" in body and body["comment"] is not None:
        if not isinstance(body["comment"], str) or len(body["comment"]) > 2000:
            raise_error(ERR_INVALID_REQUEST, "comment too long")
        r["comment"] = body["comment"]
    for f in ("theme_score", "venue_score"):
        if f in body and body[f] is not None:
            v = body[f]
            if not isinstance(v, int) or v < 1 or v > 5:
                raise_error(ERR_INVALID_REQUEST, f"{f} out of range")
            r[f] = v
    if "host_score" in body:
        v = body["host_score"]
        if v is not None:
            if not isinstance(v, int) or v < 1 or v > 5:
                raise_error(ERR_INVALID_REQUEST, "host_score out of range")
            r["host_score"] = v
        else:
            r["host_score"] = None
    r["moderation_round"] = int(r["moderation_round"]) + 1
    r["status"] = "REVISED"
    bump(r)
    return success_object(review_view(r))


@reviews_bp.route("/reviews/<review_id>/resubmit", methods=["POST"])
def resubmit_review(review_id):
    user_id, role = require_role("Player")
    r = store.reviews.get(review_id)
    if not r:
        raise_error(ERR_REVIEW_NOT_FOUND, "review not found")
    if user_id != r["author_player_id"]:
        raise_error(ERR_INSUFFICIENT_PERMISSIONS, "not own review")
    if r["status"] != "REVISED":
        raise_error(ERR_INVALID_REQUEST, "review not REVISED")
    r["status"] = "PENDING_MODERATION"
    bump(r)
    # Recompute spam score
    count = review_service.compute_spam_signal_count(r, is_resubmit=True)
    r["spam_signal_count"] = count
    if count >= SPAM_SIGNAL_HARD_BLOCK:
        r["status"] = "REJECTED"
        bump(r)
        write_audit(user_id, role, "Review", r["id"], "REVIEW_REJECTED", r)
    return success_object(review_view(r))


@reviews_bp.route("/reviews/<review_id>/moderate", methods=["POST"])
def moderate_review(review_id):
    user_id, role = require_role("ContentModerator")
    r = store.reviews.get(review_id)
    if not r:
        raise_error(ERR_REVIEW_NOT_FOUND, "review not found")
    body = get_json_body()
    decision = require_enum(body, "decision", ["APPROVE", "REJECT", "HIDE"])

    if decision == "APPROVE":
        if r["status"] != "PENDING_MODERATION":
            raise_error(ERR_REVIEW_ALREADY_MODERATED, "not PENDING")
        r["status"] = "PUBLISHED"
        bump(r)
        write_audit(user_id, role, "Review", r["id"], "REVIEW_PUBLISHED", r)
        # Recompute aggregates
        booking = store.bookings.get(r["booking_id"])
        if booking:
            slot = store.session_slots.get(booking["slot_id"])
            if slot:
                review_service.recompute_theme_aggregates(slot["theme_id"])
    elif decision == "REJECT":
        if r["status"] != "PENDING_MODERATION":
            raise_error(ERR_REVIEW_ALREADY_MODERATED, "not PENDING")
        r["status"] = "REJECTED"
        bump(r)
        write_audit(user_id, role, "Review", r["id"], "REVIEW_REJECTED", r)
    elif decision == "HIDE":
        if r["status"] != "PUBLISHED":
            raise_error(ERR_INVALID_REQUEST, "HIDE requires PUBLISHED")
        r["status"] = "HIDDEN"
        bump(r)
        write_audit(user_id, role, "Review", r["id"], "REVIEW_HIDDEN", r)
        booking = store.bookings.get(r["booking_id"])
        if booking:
            slot = store.session_slots.get(booking["slot_id"])
            if slot:
                review_service.recompute_theme_aggregates(slot["theme_id"])
    return success_object(review_view(r))


@reviews_bp.route("/reviews/<review_id>", methods=["GET"])
def get_review(review_id):
    user_id, role = require_role("Player", "ContentModerator", "PlatformAdmin")
    r = store.reviews.get(review_id)
    if not r:
        raise_error(ERR_REVIEW_NOT_FOUND, "review not found")
    if role == "Player" and user_id != r["author_player_id"]:
        raise_error(ERR_INSUFFICIENT_PERMISSIONS, "not own review")
    return success_object(review_view(r))
