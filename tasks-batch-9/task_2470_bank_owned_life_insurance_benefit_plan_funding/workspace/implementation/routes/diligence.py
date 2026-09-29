"""Due diligence files and the financial strength score (PRD 3.1)."""

from decimal import Decimal

from flask import Blueprint

import calc
from errors import ApiError
from response import collection_response, resource_response
from store import create_record, db, touch
from validation import (
    actor,
    authorize,
    find_carrier,
    find_review,
    get_id,
    get_int,
    guard_terminal,
    guard_transition,
    json_body,
    pagination,
    query_enum,
    query_int,
    query_str,
)

bp = Blueprint("diligence", __name__)

REVIEW_STATUSES = ("DRAFT", "UNDER_REVIEW", "INFO_REQUESTED", "APPROVED", "DECLINED")
TERMINAL = ("APPROVED", "DECLINED")
READ_ROLES = ("BenefitsAnalyst", "RiskOfficer", "BoardSecretary")


@bp.post("/diligence-reviews")
def open_review():
    authorize(("BenefitsAnalyst",))
    body = json_body()
    carrier_id = get_id(body, "carrier_id")
    review_year = get_int(body, "review_year")
    find_carrier(carrier_id)
    review = create_record(
        db.diligence_reviews,
        {
            "carrier_id": carrier_id,
            "review_year": review_year,
            "rating_points": 0,
            "surplus_points": 0,
            "concentration_points": Decimal("0.0"),
            "financial_strength_score": 0,
            "status": "DRAFT",
            "info_request_count": 0,
            "submitted_by_user_id": None,
            "decided_by_user_id": None,
        },
    )
    return resource_response(review, 201)


@bp.get("/diligence-reviews")
def list_reviews():
    authorize(READ_ROLES)
    limit, offset = pagination()
    carrier_id = query_str("carrier_id")
    status = query_enum("status", REVIEW_STATUSES)
    review_year = query_int("review_year")
    rows = []
    for review in db.diligence_reviews.values():
        if carrier_id is not None and review["carrier_id"] != carrier_id:
            continue
        if status is not None and review["status"] != status:
            continue
        if review_year is not None and review["review_year"] != review_year:
            continue
        rows.append(review)
    return collection_response(rows, limit, offset)


@bp.get("/diligence-reviews/<review_id>")
def read_review(review_id):
    authorize(READ_ROLES)
    return resource_response(find_review(review_id))


@bp.post("/diligence-reviews/<review_id>/submit")
def submit_review(review_id):
    authorize(("BenefitsAnalyst",))
    review = find_review(review_id)
    guard_terminal(review["status"], TERMINAL)
    guard_transition(review["status"] in ("DRAFT", "INFO_REQUESTED"))
    carrier = db.carriers.get(review["carrier_id"])
    if carrier is None:
        raise ApiError("ERR_CARRIER_NOT_FOUND")
    guard_transition(carrier["status"] in ("PENDING_DILIGENCE", "AUTHORIZED", "RESTRICTED"))
    calc.tier1_capital(required=True)

    scored = calc.carrier_financial_strength_score(carrier)
    review.update(scored)
    review["status"] = "UNDER_REVIEW"
    review["submitted_by_user_id"] = actor()
    touch(review)
    return resource_response(review)


@bp.post("/diligence-reviews/<review_id>/request-info")
def request_info(review_id):
    authorize(("RiskOfficer",))
    review = find_review(review_id)
    guard_terminal(review["status"], TERMINAL)
    guard_transition(review["status"] == "UNDER_REVIEW")
    if int(review["info_request_count"]) >= calc.INFO_REQUEST_LIMIT:
        raise ApiError("ERR_INFO_REQUEST_LIMIT_REACHED")
    review["status"] = "INFO_REQUESTED"
    review["info_request_count"] = int(review["info_request_count"]) + 1
    touch(review)
    return resource_response(review)


@bp.post("/diligence-reviews/<review_id>/approve")
def approve_review(review_id):
    authorize(("RiskOfficer",))
    review = find_review(review_id)
    guard_terminal(review["status"], TERMINAL)
    guard_transition(review["status"] == "UNDER_REVIEW")
    if actor() == review["submitted_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if int(review["financial_strength_score"]) < calc.MIN_APPROVAL_SCORE:
        raise ApiError("ERR_FINANCIAL_STRENGTH_BELOW_MINIMUM")

    review["status"] = "APPROVED"
    review["decided_by_user_id"] = actor()
    touch(review)

    carrier = db.carriers.get(review["carrier_id"])
    if carrier is not None:
        if carrier["status"] == "PENDING_DILIGENCE":
            carrier["status"] = "AUTHORIZED"
        carrier["last_approved_review_year"] = review["review_year"]
        touch(carrier)
    return resource_response(review)


@bp.post("/diligence-reviews/<review_id>/decline")
def decline_review(review_id):
    authorize(("RiskOfficer",))
    review = find_review(review_id)
    guard_terminal(review["status"], TERMINAL)
    guard_transition(review["status"] in ("UNDER_REVIEW", "INFO_REQUESTED"))
    if actor() == review["submitted_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    review["status"] = "DECLINED"
    review["decided_by_user_id"] = actor()
    touch(review)
    return resource_response(review)
