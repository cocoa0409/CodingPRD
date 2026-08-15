"""CommitteeReview endpoints."""
from flask import Blueprint, request

from db import store, clock, new_id, now_iso, _parse_iso
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_NOT_FOUND, ERR_INVALID_STATE,
    ERR_DUPLICATE_READER_REVIEW, ERR_REVIEWER_WINDOW_OVERLAP,
    ERR_REVIEW_WINDOW_CLOSED, ERR_SCORE_OUT_OF_RANGE, ERR_REVIEWER_MISMATCH,
)
from middleware import require_roles
from response import success_object, success_list
from services.derived import recompute_submitted_read_count
from services.serializers import serialize_review, touch

bp = Blueprint("reviews", __name__, url_prefix="/enrollment/reviews")


def _get_review_or_404(rid):
    r = store.reviews.get(rid)
    if not r:
        raise ApiError(ERR_NOT_FOUND, 404, "Review not found")
    return r


@bp.route("", methods=["POST"])
def create_review():
    require_roles("AdmissionsOfficer")
    body = request.get_json(silent=True) or {}
    application_id = body.get("application_id")
    reader_id = body.get("reader_id")
    window_start = body.get("window_start_at")
    window_end = body.get("window_end_at")

    if application_id is None or application_id not in store.applications:
        raise ApiError(ERR_NOT_FOUND, 404, "application_id not found")
    for v, n in [(reader_id, "reader_id"), (window_start, "window_start_at"),
                 (window_end, "window_end_at")]:
        if v is None:
            raise ApiError(ERR_INVALID_REQUEST, 400, f"{n} required")

    ws = _parse_iso(window_start)
    we = _parse_iso(window_end)
    if ws is None or we is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "window malformed")
    if we <= ws:
        raise ApiError(ERR_INVALID_REQUEST, 400, "window_end_at must be > window_start_at")

    app = store.applications[application_id]
    if app["status"] not in ("IN_REVIEW", "COMMITTEE_REVIEW"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       f"Application status {app['status']} does not permit review assignment")

    # Duplicate reader
    for r in store.reviews.values():
        if (r["application_id"] == application_id and r["reader_id"] == reader_id
                and r["status"] in ("ASSIGNED", "SUBMITTED")):
            raise ApiError(ERR_DUPLICATE_READER_REVIEW, 409,
                           "Reader already has an active/submitted review")

    # Window overlap (half-open): new window overlaps existing ASSIGNED for same reader
    for r in store.reviews.values():
        if r["reader_id"] != reader_id or r["status"] != "ASSIGNED":
            continue
        es = _parse_iso(r["window_start_at"])
        ee = _parse_iso(r["window_end_at"])
        # half-open overlap: ws < ee AND es < we
        if ws < ee and es < we:
            raise ApiError(ERR_REVIEWER_WINDOW_OVERLAP, 409,
                           "Window overlaps another ASSIGNED review")

    now = now_iso()
    review = {
        "id": new_id(),
        "application_id": application_id,
        "reader_id": reader_id,
        "window_start_at": window_start,
        "window_end_at": window_end,
        "score_academic": None,
        "score_fit": None,
        "recommendation": None,
        "submitted_at": None,
        "status": "ASSIGNED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    store.reviews[review["id"]] = review

    # First assignment moves application IN_REVIEW -> COMMITTEE_REVIEW
    if app["status"] == "IN_REVIEW":
        app["status"] = "COMMITTEE_REVIEW"
        touch(app)

    return success_object(serialize_review(review), status=201)


@bp.route("/<reviewId>", methods=["GET"])
def get_review(reviewId):
    require_roles("SystemAdmin", "EnrollmentManager", "AdmissionsOfficer", "ApplicationReader")
    r = _get_review_or_404(reviewId)
    return success_object(serialize_review(r))


@bp.route("", methods=["GET"])
def list_reviews():
    require_roles("SystemAdmin", "EnrollmentManager", "AdmissionsOfficer", "ApplicationReader")
    application_id = request.args.get("application_id")
    reader_id = request.args.get("reader_id")
    status = request.args.get("status")
    try:
        limit = int(request.args.get("limit", 10))
        offset = int(request.args.get("offset", 0))
    except (ValueError, TypeError):
        raise ApiError(ERR_INVALID_REQUEST, 400, "limit/offset must be integers")
    limit = max(1, min(100, limit))
    offset = max(0, offset)

    items = list(store.reviews.values())
    if application_id:
        items = [r for r in items if r["application_id"] == application_id]
    if reader_id:
        items = [r for r in items if r["reader_id"] == reader_id]
    if status:
        items = [r for r in items if r["status"] == status]
    items.sort(key=lambda r: (r["created_at"], r["id"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_review(r) for r in page], limit, offset, total)


@bp.route("/<reviewId>/submit", methods=["POST"])
def submit_review(reviewId):
    user_id, role = require_roles("ApplicationReader")
    r = _get_review_or_404(reviewId)

    if user_id != r["reader_id"]:
        raise ApiError(ERR_REVIEWER_MISMATCH, 403,
                       "X-User-ID does not match review reader_id")

    body = request.get_json(silent=True) or {}
    score_academic = body.get("score_academic")
    score_fit = body.get("score_fit")
    recommendation = body.get("recommendation")

    if r["status"] != "ASSIGNED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       f"Review status {r['status']} does not permit submit")

    now = clock.now()
    ws = _parse_iso(r["window_start_at"])
    we = _parse_iso(r["window_end_at"])
    if not (ws <= now < we):
        raise ApiError(ERR_REVIEW_WINDOW_CLOSED, 409,
                       "Outside review window")

    for v, n in [(score_academic, "score_academic"), (score_fit, "score_fit")]:
        if v is None:
            raise ApiError(ERR_INVALID_REQUEST, 400, f"{n} required")
        if not isinstance(v, (int, float)) or v < 0 or v > 100:
            raise ApiError(ERR_SCORE_OUT_OF_RANGE, 422,
                           f"{n} must be 0..100")
    if recommendation not in ("ADMIT", "DENY", "WAITLIST"):
        raise ApiError(ERR_INVALID_REQUEST, 400, "recommendation invalid")

    r["score_academic"] = score_academic
    r["score_fit"] = score_fit
    r["recommendation"] = recommendation
    r["submitted_at"] = now_iso()
    r["status"] = "SUBMITTED"
    touch(r)

    app = store.applications.get(r["application_id"])
    if app:
        recompute_submitted_read_count(app)
        touch(app)
    return success_object(serialize_review(r))
