"""Clinical evidence reviews (PRD section 3.2)."""

from decimal import Decimal

from flask import Blueprint

from db import db, ordered
from enums import REVIEW_STATUSES
from errors import ApiError
from middleware import ALL_ROLES, CLINICAL_REVIEWER, authenticate
from response import list_response, object_response
from services.calc import (
    EVIDENCE_THRESHOLD,
    conversion_recommendation,
    weighted_evidence_score,
)
from services.cascade import recompute_contract_evidence_endorsed
from services.lookup import get_review, resolve_body_fks
from validation import (
    body_json,
    field_decimal,
    field_string,
    paginate,
    pagination,
    query_enum,
    query_string,
)

reviews_bp = Blueprint("reviews", __name__)

SCORE_FIELDS = ("clinical_efficacy_score", "safety_score", "supply_resilience_score")


def _parse_scores(body):
    return tuple(
        field_decimal(
            body,
            name,
            minimum=Decimal("0.00"),
            maximum=Decimal("10.00"),
            scale=2,
        )
        for name in SCORE_FIELDS
    )


def _apply_scores(review, scores):
    review["clinical_efficacy_score"] = scores[0]
    review["safety_score"] = scores[1]
    review["supply_resilience_score"] = scores[2]
    review["weighted_score"] = weighted_evidence_score(*scores)
    review["conversion_recommendation"] = conversion_recommendation(review["weighted_score"])


@reviews_bp.route("/gpo/clinical-evidence-reviews", methods=["POST"])
def create_review():
    acting_user_id, _ = authenticate((CLINICAL_REVIEWER,))
    body = body_json()
    resolved = resolve_body_fks(body, ("contract_id",))
    contract = resolved["contract_id"]
    if contract is None:
        raise ApiError("ERR_INVALID_REQUEST", "Field 'contract_id' is required.")
    scores = _parse_scores(body)
    summary = field_string(body, "summary", 0, 500, required=False, default="")
    if contract["status"] not in ("DRAFT", "ACTIVE"):
        raise ApiError(
            "ERR_CONTRACT_NOT_ACTIVE",
            "Evidence can only be filed against a DRAFT or ACTIVE contract.",
        )

    row = db.new_row()
    row.update(
        {
            "contract_id": contract["id"],
            "summary": summary,
            "status": "UNDER_REVIEW",
            "revision_round": 0,
            "submitted_by_user_id": acting_user_id,
            "endorsed_by_user_id": None,
        }
    )
    _apply_scores(row, scores)
    db.reviews[row["id"]] = row
    return object_response(row, 201)


@reviews_bp.route("/gpo/clinical-evidence-reviews/<review_id>", methods=["GET"])
def read_review(review_id):
    authenticate(ALL_ROLES)
    return object_response(get_review(review_id))


@reviews_bp.route("/gpo/clinical-evidence-reviews", methods=["GET"])
def list_reviews():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    status = query_enum("status", REVIEW_STATUSES)
    contract_id = query_string("contract_id")
    rows = [
        row
        for row in ordered(db.reviews.values())
        if (status is None or row["status"] == status)
        and (contract_id is None or row["contract_id"] == contract_id)
    ]
    page, total = paginate(rows, limit, offset)
    return list_response(page, limit, offset, total)


@reviews_bp.route("/gpo/clinical-evidence-reviews/<review_id>/scores", methods=["PATCH"])
def update_scores(review_id):
    authenticate((CLINICAL_REVIEWER,))
    review = get_review(review_id)
    body = body_json()
    scores = _parse_scores(body)
    if review["status"] not in ("UNDER_REVIEW", "REVISION_REQUESTED"):
        raise ApiError(
            "ERR_INVALID_REVIEW_STATE",
            "Scores may only be corrected while UNDER_REVIEW or REVISION_REQUESTED.",
        )
    _apply_scores(review, scores)
    db.touch(review)
    return object_response(review)


@reviews_bp.route(
    "/gpo/clinical-evidence-reviews/<review_id>/request-revision", methods=["POST"]
)
def request_revision(review_id):
    authenticate((CLINICAL_REVIEWER,))
    review = get_review(review_id)
    body = body_json()
    field_string(body, "reason", 0, None, required=False, default=None)
    if review["status"] != "UNDER_REVIEW":
        raise ApiError(
            "ERR_INVALID_REVIEW_STATE", "Only an UNDER_REVIEW dossier can be sent back."
        )
    if review["revision_round"] not in (0, 1):
        raise ApiError(
            "ERR_REVISION_LIMIT_REACHED", "A dossier may be sent back at most twice."
        )
    review["status"] = "REVISION_REQUESTED"
    review["revision_round"] = review["revision_round"] + 1
    db.touch(review)
    return object_response(review)


@reviews_bp.route("/gpo/clinical-evidence-reviews/<review_id>/resubmit", methods=["POST"])
def resubmit_review(review_id):
    acting_user_id, _ = authenticate((CLINICAL_REVIEWER,))
    review = get_review(review_id)
    body = body_json()
    scores = _parse_scores(body)
    summary = field_string(body, "summary", 0, 500, required=False, default=None)
    if review["status"] != "REVISION_REQUESTED":
        raise ApiError(
            "ERR_INVALID_REVIEW_STATE", "Only a REVISION_REQUESTED dossier can be resubmitted."
        )
    _apply_scores(review, scores)
    if summary is not None:
        review["summary"] = summary
    review["status"] = "UNDER_REVIEW"
    review["submitted_by_user_id"] = acting_user_id
    db.touch(review)
    return object_response(review)


@reviews_bp.route("/gpo/clinical-evidence-reviews/<review_id>/endorse", methods=["POST"])
def endorse_review(review_id):
    acting_user_id, _ = authenticate((CLINICAL_REVIEWER,))
    review = get_review(review_id)
    if review["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_REVIEW_STATE", "Only an UNDER_REVIEW dossier can be endorsed.")
    if str(acting_user_id) == str(review["submitted_by_user_id"]):
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES", "The submitter may not endorse their own dossier."
        )
    if review["weighted_score"] < EVIDENCE_THRESHOLD:
        raise ApiError(
            "ERR_EVIDENCE_SCORE_BELOW_THRESHOLD",
            "weighted_score must reach 7.00 to endorse.",
        )
    review["status"] = "ENDORSED"
    review["endorsed_by_user_id"] = acting_user_id
    db.touch(review)
    contract = db.contracts.get(review["contract_id"])
    if contract is not None:
        recompute_contract_evidence_endorsed(contract)
    return object_response(review)


@reviews_bp.route("/gpo/clinical-evidence-reviews/<review_id>/reject", methods=["POST"])
def reject_review(review_id):
    acting_user_id, _ = authenticate((CLINICAL_REVIEWER,))
    review = get_review(review_id)
    body = body_json()
    field_string(body, "reason", 0, None, required=False, default=None)
    if review["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_REVIEW_STATE", "Only an UNDER_REVIEW dossier can be rejected.")
    if str(acting_user_id) == str(review["submitted_by_user_id"]):
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES", "The submitter may not reject their own dossier."
        )
    review["status"] = "REJECTED"
    db.touch(review)
    contract = db.contracts.get(review["contract_id"])
    if contract is not None:
        recompute_contract_evidence_endorsed(contract)
    return object_response(review)
