"""CDRReview routes."""

from __future__ import annotations

from flask import Blueprint, request

from app.envelope import list_response, success_response
from app.routes._helpers import (
    get_json_body,
    paginate,
    parse_pagination,
    with_auth,
)
from app.serializers import serialize_cdr_review
from app.services import cdr_reviews as service


bp = Blueprint("cdr_reviews", __name__)


@bp.route("/cdr-reviews", methods=["GET"])
@with_auth("CDR_Reviewer", "PlatformAdmin")
def list_reviews(caller):
    limit, offset = parse_pagination()
    status = request.args.get("status")
    due_before = request.args.get("due_before")
    rows = service.list_cdr_reviews(status, due_before)
    page, total = paginate(rows, limit, offset)
    return list_response(
        [serialize_cdr_review(r) for r in page],
        limit=limit,
        offset=offset,
        total=total,
    )


@bp.route("/cdr-reviews/<review_id>/schedule", methods=["POST"])
@with_auth("CDR_Reviewer")
def schedule(caller, review_id: str):
    record = service.schedule_review(review_id)
    return success_response(serialize_cdr_review(record))


@bp.route("/cdr-reviews/<review_id>/complete", methods=["POST"])
@with_auth("CDR_Reviewer")
def complete(caller, review_id: str):
    body = get_json_body()
    record = service.complete_review(review_id, body)
    return success_response(serialize_cdr_review(record))
