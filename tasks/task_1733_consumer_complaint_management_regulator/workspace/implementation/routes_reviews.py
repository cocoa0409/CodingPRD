"""Quality review governance (PRD §3.7)."""
from flask import g, Blueprint

import services as svc
from db import store
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE_TRANSITION,
    ERR_REVIEW_NOT_OWNED,
    ERR_REVIEW_WINDOW_OVERLAP,
    ERR_SOD_SELF_REVIEW,
)
from middleware import get_body, pagination_params, req_datetime, req_enum, require_roles
from response import ok, ok_list

bp = Blueprint("reviews", __name__)

REVIEW_READERS = ("ComplaintManager", "CaseHandler", "QAReviewer", "ExecutiveReviewer", "Auditor")


@bp.post("/complaints/<cid>/quality-reviews")
@require_roles("QAReviewer")
def create_review(cid):
    svc.get_complaint(cid)
    body = get_body()
    start = req_datetime(body, "window_start_at")
    end = req_datetime(body, "window_end_at")
    if end <= start:
        raise ApiError(ERR_INVALID_REQUEST, "window_end_at must lie strictly after window_start_at.", 400)
    # Half-open [start, end) windows held by the acting reviewer must not
    # overlap; touching endpoints (end == start) do NOT overlap.
    for ex in store.reviews.values():
        if ex.reviewer_user_id != g.user_id or ex.status != "OPEN":
            continue
        if start < ex.window_end_at and ex.window_start_at < end:
            raise ApiError(
                ERR_REVIEW_WINDOW_OVERLAP,
                "The acting reviewer already holds an OPEN QualityReview whose sampling window intersects.",
                409,
            )
    complaint_id = cid
    r = svc.fresh_rec(
        complaint_id=complaint_id,
        reviewer_user_id=g.user_id,
        window_start_at=start,
        window_end_at=end,
        outcome=None,
        status="OPEN",
    )
    store.reviews[r.id] = r
    return ok(svc.ser_review(r), 201)


@bp.get("/complaints/<cid>/quality-reviews")
@require_roles(*REVIEW_READERS)
def list_reviews(cid):
    svc.get_complaint(cid)
    limit, offset = pagination_params()
    recs = [r for r in store.reviews.values() if r.complaint_id == cid]
    items, total = svc.paged(recs, svc.ser_review, limit, offset)
    return ok_list(items, total, limit, offset)


@bp.get("/quality-reviews/<reviewId>")
@require_roles(*REVIEW_READERS)
def get_review(reviewId):
    return ok(svc.ser_review(svc.get_review(reviewId)), 200)


@bp.post("/quality-reviews/<reviewId>/complete")
@require_roles("QAReviewer")
def complete_review(reviewId):
    r = svc.get_review(reviewId)
    body = get_body()
    outcome = req_enum(body, "outcome", ("PASS", "FAIL"))
    complaint = svc.get_complaint(r.complaint_id)
    # Segregation of duties (6) surfaces before the state check (8).
    if g.user_id == complaint.owner_user_id:
        raise ApiError(ERR_SOD_SELF_REVIEW, "A reviewer may not review a complaint they own.", 409)
    if r.status != "OPEN":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, f"Review status is {r.status}; complete requires OPEN.", 409)
    if g.user_id != r.reviewer_user_id:
        raise ApiError(ERR_REVIEW_NOT_OWNED, "A QAReviewer may only complete their own reviews.", 409)
    r.outcome = outcome
    r.status = "COMPLETED"
    svc.touch(r)
    svc.append_event(
        complaint.id,
        "QA_PASSED" if outcome == "PASS" else "QA_FAILED",
        {"review_id": r.id, "outcome": outcome},
    )
    svc.recompute_timeliness_score(complaint)
    return ok(svc.ser_review(r), 200)


@bp.post("/quality-reviews/<reviewId>/cancel")
@require_roles("QAReviewer", "ComplaintManager")
def cancel_review(reviewId):
    r = svc.get_review(reviewId)
    if r.status != "OPEN":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, f"Review status is {r.status}; cancel requires OPEN.", 409)
    # Ownership check applies to QAReviewers; ComplaintManager is exempt.
    if g.role == "QAReviewer" and g.user_id != r.reviewer_user_id:
        raise ApiError(ERR_REVIEW_NOT_OWNED, "A QAReviewer may only cancel their own reviews.", 409)
    r.status = "CANCELLED"
    svc.touch(r)
    return ok(svc.ser_review(r), 200)
