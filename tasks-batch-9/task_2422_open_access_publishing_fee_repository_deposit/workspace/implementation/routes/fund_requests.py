"""Fund requests, the review cycle, the funding decision and allocations."""
from flask import Blueprint, g

import constants as C
import schemas
from auth import endpoint, require_owner
from db import db, new_row, set_fields
from errors import ApiError
from response import object_response
from routes.helpers import paged
from services import funding
from services.determination import effective_determination
from validation import (
    filter_enum,
    get_body,
    invalid,
    opt_str,
    req_enum,
    req_int,
    req_str,
    resolve,
    resolve_body_fk,
    resolve_filter,
)

bp = Blueprint("fund_requests", __name__)

REVIEWABLE_WITHDRAWAL = ("SUBMITTED", "INFO_REQUESTED", "APPROVED")


def _article_of(request_row):
    return db.articles[request_row["article_id"]]


def _eligible_cents(article):
    determination = effective_determination(article["id"])
    if determination is None:
        return None
    return determination["eligible_request_cents"]


# ----------------------------------------------------------- Fund requests

@bp.post("/fund-requests")
@endpoint(["CorrespondingAuthor"])
def create_fund_request():
    body = get_body()
    article = resolve_body_fk(body, "article_id", "article")
    if article is not None:
        require_owner(article["corresponding_author_id"])
    if article is None:
        invalid("article_id is required")
    requested_cents = req_int(body, "requested_cents", minimum=1)
    justification = req_str(body, "justification")

    journal = db.journals[article["journal_id"]]
    publisher = db.publishers[journal["publisher_id"]]
    if publisher["screening_status"] == "BLOCKED":
        raise ApiError("ERR_PUBLISHER_BLOCKED", 422)

    grant_id = article.get("grant_id")
    if grant_id:
        grant = db.grants.get(grant_id)
        if grant is None or grant["status"] != "ACTIVE":
            raise ApiError("ERR_GRANT_NOT_ACTIVE", 409)

    eligible = _eligible_cents(article)
    if eligible is None or eligible <= 0:
        raise ApiError("ERR_ELIGIBILITY_NOT_DETERMINED", 409)
    if requested_cents > eligible:
        raise ApiError("ERR_REQUEST_EXCEEDS_ELIGIBLE", 422)

    row = new_row(
        article_id=article["id"],
        requested_cents=requested_cents,
        justification=justification,
        status="SUBMITTED",
        revision_round=0,
        info_needed=None,
        response_note=None,
        reviewed_by_user_id=None,
        decided_by_user_id=None,
        decision_reason=None,
        approved_cents=0,
        author_share_cents=0,
        fully_funded=False,
    )
    db.fund_requests[row["id"]] = row
    set_fields(article, funding_status="FUNDING_REQUESTED")
    return object_response(schemas.serialize(row, schemas.FUND_REQUEST), 201)


@bp.get("/articles/<article_id>/fund-requests")
@endpoint(["ScholCommLibrarian", "FundManager", "CorrespondingAuthor"])
def list_article_fund_requests(article_id):
    resolve("article", article_id)
    filter_article = resolve_filter("article", "article_id")
    status = filter_enum("status", C.FUND_REQUEST_STATUSES)
    rows = [r for r in db.fund_requests.values() if r["article_id"] == article_id]
    if filter_article:
        rows = [r for r in rows if r["article_id"] == filter_article]
    if status:
        rows = [r for r in rows if r["status"] == status]
    return paged(rows, schemas.FUND_REQUEST)


@bp.get("/fund-requests/<request_id>")
@endpoint(["ScholCommLibrarian", "FundManager", "CorrespondingAuthor"])
def get_fund_request(request_id):
    row = resolve("fund_request", request_id)
    return object_response(schemas.serialize(row, schemas.FUND_REQUEST))


@bp.post("/fund-requests/<request_id>/start-review")
@endpoint(["ScholCommLibrarian"])
def start_review(request_id):
    request_row = resolve("fund_request", request_id)
    if request_row["status"] != "SUBMITTED":
        raise ApiError("ERR_REQUEST_NOT_REVIEWABLE", 409)
    set_fields(request_row, status="UNDER_REVIEW", reviewed_by_user_id=g.user_id)
    return object_response(schemas.serialize(request_row, schemas.FUND_REQUEST))


@bp.post("/fund-requests/<request_id>/info-requests")
@endpoint(["ScholCommLibrarian"])
def request_info(request_id):
    request_row = resolve("fund_request", request_id)
    body = get_body()
    info_needed = req_str(body, "info_needed")
    if request_row["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_REQUEST_NOT_REVIEWABLE", 409)
    set_fields(request_row, status="INFO_REQUESTED", info_needed=info_needed)
    return object_response(schemas.serialize(request_row, schemas.FUND_REQUEST))


@bp.post("/fund-requests/<request_id>/resubmissions")
@endpoint(["CorrespondingAuthor"])
def resubmit(request_id):
    request_row = resolve("fund_request", request_id)
    article = _article_of(request_row)
    require_owner(article["corresponding_author_id"])
    body = get_body()
    requested_cents = req_int(body, "requested_cents", minimum=1)
    response_note = req_str(body, "response_note")
    if request_row["status"] != "INFO_REQUESTED":
        raise ApiError("ERR_REQUEST_NOT_RESUBMITTABLE", 409)
    eligible = _eligible_cents(article)
    if eligible is None or requested_cents > eligible:
        raise ApiError("ERR_REQUEST_EXCEEDS_ELIGIBLE", 422)
    set_fields(
        request_row,
        _force=True,
        status="SUBMITTED",
        requested_cents=requested_cents,
        response_note=response_note,
        revision_round=request_row["revision_round"] + 1,
    )
    return object_response(schemas.serialize(request_row, schemas.FUND_REQUEST))


@bp.post("/fund-requests/<request_id>/decision")
@endpoint(["FundManager"])
def decide(request_id):
    request_row = resolve("fund_request", request_id)
    body = get_body()
    decision = req_enum(body, "decision", C.DECISIONS)
    reason = opt_str(body, "reason")
    if request_row["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_REQUEST_NOT_REVIEWABLE", 409)

    article = _article_of(request_row)

    if decision == "REJECT":
        set_fields(
            request_row,
            _force=True,
            status="REJECTED",
            decided_by_user_id=g.user_id,
            decision_reason=reason,
        )
        set_fields(article, funding_status="DECLINED")
        return object_response(schemas.serialize(request_row, schemas.FUND_REQUEST))

    author = db.authors[article["corresponding_author_id"]]
    approved_cents = funding.run_waterfall(request_row, article, author)
    set_fields(
        request_row,
        _force=True,
        status="APPROVED",
        decided_by_user_id=g.user_id,
        decision_reason=reason,
        approved_cents=approved_cents,
        author_share_cents=request_row["requested_cents"] - approved_cents,
        fully_funded=approved_cents == request_row["requested_cents"],
    )
    set_fields(
        article,
        funding_status="FUNDED" if request_row["fully_funded"] else "PARTIALLY_FUNDED",
    )
    funding.recompute_author_totals(author["id"])
    return object_response(schemas.serialize(request_row, schemas.FUND_REQUEST))


@bp.post("/fund-requests/<request_id>/withdrawal")
@endpoint(["CorrespondingAuthor"])
def withdraw(request_id):
    request_row = resolve("fund_request", request_id)
    article = _article_of(request_row)
    require_owner(article["corresponding_author_id"])
    body = get_body()
    req_str(body, "reason")
    if request_row["status"] not in REVIEWABLE_WITHDRAWAL:
        raise ApiError("ERR_REQUEST_NOT_REVIEWABLE", 409)

    was_approved = request_row["status"] == "APPROVED"
    changes = {"status": "WITHDRAWN"}
    if was_approved:
        funding.release_allocations(request_row, "REQUEST_WITHDRAWN")
        changes["approved_cents"] = 0
        changes["fully_funded"] = False
    set_fields(request_row, _force=True, **changes)
    set_fields(article, funding_status="ELIGIBILITY_CHECKED")
    if was_approved:
        funding.recompute_author_totals(article["corresponding_author_id"])
    return object_response(schemas.serialize(request_row, schemas.FUND_REQUEST))


@bp.get("/fund-requests/<request_id>/allocations")
@endpoint(["ScholCommLibrarian", "FundManager", "CorrespondingAuthor"])
def list_request_allocations(request_id):
    resolve("fund_request", request_id)
    filter_request = resolve_filter("fund_request", "fund_request_id")
    status = filter_enum("status", C.ALLOCATION_STATUSES)
    rows = funding.allocations_of_request(request_id)
    if filter_request:
        rows = [a for a in rows if a["fund_request_id"] == filter_request]
    if status:
        rows = [a for a in rows if a["status"] == status]
    return paged(rows, schemas.ALLOCATION, sort=False)
