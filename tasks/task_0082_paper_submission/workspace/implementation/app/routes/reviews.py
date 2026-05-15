"""Review endpoints: get, patch (DRAFT only), submit."""
from __future__ import annotations

from flask import Blueprint, g

from ..auth import require_auth
from ..clock import clock
from ..errors import api_error
from ..response import success_envelope
from ..store import fmt_ts, store
from ..utils import check_version, get_json_body


reviews_bp = Blueprint("reviews", __name__)

_REC_VALUES = {"ACCEPT", "MINOR_REVISION", "MAJOR_REVISION", "REJECT"}


def _resolve_review_and_invitation(rid: str) -> tuple[dict, dict, dict]:
    review = store.reviews.get(rid)
    if not review:
        raise api_error("ERR_NOT_FOUND", "Review not found")
    inv = store.reviewer_invitations.get(review["invitation_id"])
    if not inv:
        raise api_error("ERR_NOT_FOUND", "Parent invitation not found")
    m = store.manuscripts.get(review["manuscript_id"])
    if not m:
        raise api_error("ERR_NOT_FOUND", "Parent manuscript not found")
    return review, inv, m


@reviews_bp.route("/reviews/<rid>", methods=["GET"])
@require_auth(["PlatformAdmin", "EditorInChief", "SectionEditor", "AssociateEditor", "Reviewer"])
def get_review(rid: str):
    review, _, _ = _resolve_review_and_invitation(rid)
    return success_envelope(review, status=200, response_type="object")


@reviews_bp.route("/reviews/<rid>", methods=["PATCH"])
@require_auth(["Reviewer"])
def patch_review(rid: str):
    body = get_json_body()
    with store.lock:
        review, inv, m = _resolve_review_and_invitation(rid)
        if g.user_id != inv["reviewer_id"]:
            raise api_error("ERR_FORBIDDEN", "Caller is not the reviewer")
        if review["status"] != "DRAFT":
            raise api_error("ERR_INVALID_STATE", "Review not in DRAFT state")
        check_version(body, review)
        changed = False
        if "rating" in body:
            r = body["rating"]
            if not isinstance(r, int) or r < 1 or r > 5:
                raise api_error("ERR_VALIDATION", "rating must be integer in [1,5]")
            review["rating"] = r
            changed = True
        if "recommendation" in body:
            rec = body["recommendation"]
            if rec not in _REC_VALUES:
                raise api_error("ERR_VALIDATION", "recommendation must be one of ACCEPT, MINOR_REVISION, MAJOR_REVISION, REJECT")
            review["recommendation"] = rec
            changed = True
        if "comments_to_author" in body:
            v = body["comments_to_author"]
            if not isinstance(v, str):
                raise api_error("ERR_VALIDATION", "comments_to_author must be a string")
            review["comments_to_author"] = v
            changed = True
        if "comments_to_editor" in body:
            v = body["comments_to_editor"]
            if not isinstance(v, str):
                raise api_error("ERR_VALIDATION", "comments_to_editor must be a string")
            review["comments_to_editor"] = v
            changed = True
        if changed:
            store.stamp_update(review)
        return success_envelope(review, status=200, response_type="object")


@reviews_bp.route("/reviews/<rid>/submit", methods=["POST"])
@require_auth(["Reviewer"])
def submit_review(rid: str):
    body = get_json_body()
    with store.lock:
        review, inv, m = _resolve_review_and_invitation(rid)
        if g.user_id != inv["reviewer_id"]:
            raise api_error("ERR_FORBIDDEN", "Caller is not the reviewer")
        if review["status"] != "DRAFT":
            raise api_error("ERR_INVALID_STATE", "Review not in DRAFT state")
        if m["status"] != "UNDER_REVIEW":
            raise api_error("ERR_INVALID_STATE", "Manuscript not in UNDER_REVIEW state")
        check_version(body, review)
        # Business validation: all fields populated, rating in range, recommendation valid
        rating = review.get("rating")
        rec = review.get("recommendation")
        cta = review.get("comments_to_author")
        cte = review.get("comments_to_editor")
        if (
            not isinstance(rating, int) or rating < 1 or rating > 5
            or rec not in _REC_VALUES
            or not isinstance(cta, str) or not cta
            or not isinstance(cte, str) or not cte
        ):
            raise api_error("ERR_REVIEW_INCOMPLETE", "Review fields incomplete or out of range")
        prev = review["status"]
        review["status"] = "SUBMITTED"
        review["submitted_at"] = fmt_ts(clock.now())
        store.stamp_update(review)
        # Decrement reviewer.active_assignments
        rev = store.reviewers.get(inv["reviewer_id"])
        if rev and rev.get("active_assignments", 0) > 0:
            rev["active_assignments"] = rev["active_assignments"] - 1
            store.stamp_update(rev)
        store.append_audit(
            actor_role=g.user_role, actor_id=g.user_id,
            entity="Review", entity_id=review["id"],
            action="REVIEW_SUBMITTED", from_state=prev, to_state="SUBMITTED",
        )
        return success_envelope(review, status=200, response_type="object")
