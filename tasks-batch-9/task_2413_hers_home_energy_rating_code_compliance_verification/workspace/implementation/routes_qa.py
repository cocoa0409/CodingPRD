"""Quality assurance, remediation and the commercial documentation packages."""

from flask import Blueprint

import calc
import validation as v
from auth import check_cert_level, check_certification_valid, endpoint, require_owner
from cascades import cascade_qa_major_failure, create_corrective_action, step_rater_discipline
from db import clock_now_iso, db, new_row, ordered, touch
from errors import ApiError
from graph import (
    builder_of_rating,
    governing_final,
    has_unresolved_corrective_action,
    packages_of_rating,
    plan_of_rating,
    rating_of_corrective_action,
    rating_of_package,
    rating_of_qa_review,
    require_corrective_action,
    require_document_package,
    require_qa_review,
    require_rater,
    require_rating,
)
from ops import check_not_void, invalid_state
from response import Result
from serializers import corrective_action_out, document_package_out, qa_review_out

bp = Blueprint("qa", __name__)

REVIEW_TYPES = ("FILE_REVIEW", "FIELD_REVIEW")
REVIEW_RESULTS = ("PASS", "FAIL_MINOR", "FAIL_MAJOR")
REVIEW_STATUSES = ("ASSIGNED", "COMPLETED")
PACKAGE_TYPES = ("TAX_CREDIT_45L", "UTILITY_PROGRAM")
QA_READ_ROLES = ("RatingProviderAdmin", "CertifiedRater", "QADesignee")


def _check_segregation(rating, reviewer_id, review_type):
    """PRD §2.11 — the reviewer is never the rater, nor the governing final inspector."""
    if reviewer_id == rating["rater_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if review_type == "FIELD_REVIEW":
        governing = governing_final(rating)
        if governing is not None and governing[0]["inspector_id"] == reviewer_id:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES")


# --- QA reviews -----------------------------------------------------------
@bp.post("/qa-reviews")
@endpoint(["RatingProviderAdmin"])
def create_qa_review():
    data = v.body()
    rating_id = v.req_str(data, "rating_id")
    reviewer_id = v.req_str(data, "reviewer_id")
    review_type = v.req_enum(data, "review_type", REVIEW_TYPES)

    rating = require_rating(rating_id)
    require_rater(reviewer_id)

    # §3.8: a voided rating blocks review assignment with ERR_RATING_VOID, so the
    # void answer is decided ahead of general state admissibility.
    check_not_void(rating)

    if rating["stage"] not in ("CONFIRMED", "REGISTERED"):
        invalid_state("Only a CONFIRMED or REGISTERED rating can be selected for QA.")
    if rating["qa_status"] != "NOT_SELECTED":
        invalid_state("The rating has already been selected for quality assurance.")

    check_certification_valid(reviewer_id)

    _check_segregation(rating, reviewer_id, review_type)

    row = new_row(
        "QAReview",
        {
            "rating_id": rating_id,
            "reviewer_id": reviewer_id,
            "review_type": review_type,
            "status": "ASSIGNED",
            "result": None,
            "findings_note": None,
        },
    )
    db.qa_reviews[row["id"]] = row

    rating["qa_status"] = "QA_SELECTED"
    touch(rating)
    return Result(row, qa_review_out, status=201)


@bp.get("/qa-reviews/<qa_review_id>")
@endpoint(list(QA_READ_ROLES))
def get_qa_review(qa_review_id):
    return Result(require_qa_review(qa_review_id), qa_review_out)


@bp.get("/qa-reviews")
@endpoint(list(QA_READ_ROLES))
def list_qa_reviews():
    limit, offset = v.pagination()
    rating_id = v.query_str("rating_id")
    reviewer_id = v.query_str("reviewer_id")
    status = v.query_enum("status", REVIEW_STATUSES)

    rows = []
    for review in db.qa_reviews.values():
        if rating_id is not None and review["rating_id"] != rating_id:
            continue
        if reviewer_id is not None and review["reviewer_id"] != reviewer_id:
            continue
        if status is not None and review["status"] != status:
            continue
        rows.append(review)
    rows = ordered(rows)
    page, total = v.paginate(rows, limit, offset)
    return Result(page, qa_review_out, page=(limit, offset, total))


@bp.post("/qa-reviews/<qa_review_id>/complete")
@endpoint(["QADesignee"])
def complete_qa_review(qa_review_id):
    data = v.body()
    result = v.req_enum(data, "result", REVIEW_RESULTS)
    findings_note = v.req_str(data, "findings_note")

    review = require_qa_review(qa_review_id)
    require_owner(review["reviewer_id"])

    if review["status"] != "ASSIGNED":
        invalid_state("Only an ASSIGNED review can be completed.")

    check_certification_valid(review["reviewer_id"])
    check_cert_level(review["reviewer_id"], ("QA_DESIGNEE",))

    rating = rating_of_qa_review(review)
    _check_segregation(rating, review["reviewer_id"], review["review_type"])

    review["status"] = "COMPLETED"
    review["result"] = result
    review["findings_note"] = findings_note
    touch(review)

    reviewee = db.raters.get(rating["rater_id"])

    if result == "PASS":
        rating["qa_status"] = "QA_PASSED"
        touch(rating)
    elif result == "FAIL_MINOR":
        # The qa dimension deliberately stays QA_SELECTED on a minor finding.
        create_corrective_action(rating, "QA_FINDING")
        if reviewee is not None:
            step_rater_discipline(reviewee)
    else:
        rating["qa_status"] = "QA_FAILED"
        touch(rating)
        if reviewee is not None:
            step_rater_discipline(reviewee)
        cascade_qa_major_failure(rating)

    return Result(review, qa_review_out)


# --- Corrective actions ---------------------------------------------------
@bp.post("/corrective-actions/<action_id>/submit")
@endpoint(["BuilderRep"])
def submit_corrective_action(action_id):
    data = v.body()
    remediation_note = v.req_str(data, "remediation_note")

    action = require_corrective_action(action_id)
    rating = rating_of_corrective_action(action)
    builder = builder_of_rating(rating) if rating is not None else None
    require_owner(builder["id"] if builder is not None else None)

    check_not_void(rating)

    if action["status"] not in ("OPEN", "REJECTED"):
        invalid_state("Only an OPEN or REJECTED corrective action can be submitted.")

    action["status"] = "SUBMITTED"
    action["attempt_count"] = action["attempt_count"] + 1
    action["remediation_note"] = remediation_note
    touch(action)
    return Result(action, corrective_action_out)


@bp.post("/corrective-actions/<action_id>/review")
@endpoint(["RatingProviderAdmin"])
def review_corrective_action(action_id):
    data = v.body()
    decision = v.req_enum(data, "decision", ("ACCEPT", "REJECT"))
    v.opt_str(data, "note")

    action = require_corrective_action(action_id)
    if action["status"] != "SUBMITTED":
        invalid_state("Only a SUBMITTED corrective action can be adjudicated.")

    rating = rating_of_corrective_action(action)

    if decision == "ACCEPT":
        action["status"] = "ACCEPTED"
        touch(action)
        if rating is not None and rating["compliance_status"] == "FAILING":
            rating["compliance_status"] = "REMEDIATION_PENDING"
            touch(rating)
    else:
        if action["attempt_count"] >= 3:
            action["status"] = "ESCALATED"
            touch(action)
            builder = builder_of_rating(rating) if rating is not None else None
            if builder is not None and builder["status"] != "SAMPLING_SUSPENDED":
                builder["status"] = "SAMPLING_SUSPENDED"
                touch(builder)
        else:
            action["status"] = "REJECTED"
            touch(action)

    return Result(action, corrective_action_out)


# --- Document packages ----------------------------------------------------
@bp.post("/document-packages")
@endpoint(["BuilderRep"])
def create_document_package():
    data = v.body()
    rating_id = v.req_str(data, "rating_id")
    package_type = v.req_enum(data, "package_type", PACKAGE_TYPES)
    expected_version = v.req_int(data, "expected_rating_version")

    rating = require_rating(rating_id)
    builder = builder_of_rating(rating)
    require_owner(builder["id"] if builder is not None else None)

    check_not_void(rating)

    if expected_version != rating["version"]:
        raise ApiError("ERR_STALE_RATING_VERSION")

    plan = plan_of_rating(rating)
    amount, line_items = calc.incentive_amount(
        package_type,
        rating["projected_index"],
        plan["design_ach50"],
        plan["design_duct_leakage_cfm25_per_100sqft"],
        plan,
    )

    for package in packages_of_rating(rating_id):
        if package["status"] == "DRAFT" and package["package_type"] == package_type:
            package["status"] = "SUPERSEDED"
            touch(package)

    row = new_row(
        "DocumentPackage",
        {
            "rating_id": rating_id,
            "package_type": package_type,
            "status": "DRAFT",
            "provisional_amount_cents": amount,
            "certified_amount_cents": None,
            "line_items": line_items,
            "revocation_reason": None,
            "issued_at": None,
        },
    )
    db.document_packages[row["id"]] = row

    # Drafting itself advances the rating's optimistic-concurrency token.
    touch(rating)
    return Result(row, document_package_out, status=201)


@bp.post("/document-packages/<package_id>/issue")
@endpoint(["RatingProviderAdmin"])
def issue_document_package(package_id):
    package = require_document_package(package_id)
    rating = rating_of_package(package)

    check_not_void(rating)

    if package["status"] != "DRAFT":
        invalid_state("Only a DRAFT package can be issued.")

    if (
        rating is None
        or rating["stage"] not in ("CONFIRMED", "REGISTERED")
        or rating["compliance_status"] != "PASSING"
        or rating["qa_status"] == "QA_FAILED"
    ):
        raise ApiError("ERR_RATING_NOT_COMPLIANT")

    if has_unresolved_corrective_action(rating["id"]):
        raise ApiError("ERR_OPEN_CORRECTIVE_ACTION")

    index = rating["confirmed_index"]
    ceiling = (
        calc.TAX_CREDIT_MAX_INDEX
        if package["package_type"] == "TAX_CREDIT_45L"
        else calc.UTILITY_PROGRAM_MAX_INDEX
    )
    if index is None or index > ceiling:
        raise ApiError("ERR_PACKAGE_NOT_ELIGIBLE")

    plan = plan_of_rating(rating)
    amount, line_items = calc.incentive_amount(
        package["package_type"],
        index,
        rating["confirmed_ach50"],
        rating["confirmed_duct_leakage_cfm25_per_100sqft"],
        plan,
    )

    builder = builder_of_rating(rating)
    if package["package_type"] == "UTILITY_PROGRAM" and builder is not None:
        if (
            builder["certified_incentive_cents"] + amount
            > builder["utility_program_budget_cents"]
        ):
            raise ApiError("ERR_PROGRAM_BUDGET_EXCEEDED")

    package["certified_amount_cents"] = amount
    package["line_items"] = line_items
    package["status"] = "ISSUED"
    package["issued_at"] = clock_now_iso()
    touch(package)
    return Result(package, document_package_out)
