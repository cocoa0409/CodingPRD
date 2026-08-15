"""CDI review endpoints: open, list, activate / hold / resume / close."""
from flask import Blueprint, request

import db
from errors import raise_error
from helpers import (
    body_ref,
    get_or_404,
    list_page,
    make_record,
    require_program_active,
    touch,
)
from middleware import (
    check_known_fields,
    get_json_body,
    require_fields,
    require_roles,
    validate_enum,
    validate_integer,
)
from response import success_list, success_object
from serializers import query_out, review_out

bp = Blueprint("reviews", __name__)

ROLES = {"CDIManager", "CDISpecialist", "HIMCoder", "ComplianceAuditor"}
QUERY_LIST_ROLES = ROLES | {"Provider"}
CLOSE_REASONS = {"OPPORTUNITY_CAPTURED", "NO_OPPORTUNITY", "CASE_DISCHARGED"}


def _other_active_review(case_id, exclude_id):
    return any(
        r for r in db.reviews.values()
        if r["patient_case_id"] == case_id
        and r["id"] != exclude_id
        and r["status"] == "ACTIVE"
    )


@bp.route("/api/cdi-reviews", methods=["POST"])
def create_review():
    user_id, _ = require_roles({"CDISpecialist"})
    body = get_json_body()
    check_known_fields(body, {"patient_case_id"})
    require_fields(body, ["patient_case_id"])
    case = body_ref(body, "patient_case_id", db.cases, "case")
    program = db.programs.get(case["cdi_program_id"])
    require_program_active(program)
    review = make_record(db.reviews, {
        "patient_case_id": case["id"],
        "cdi_program_id": case["cdi_program_id"],
        "cdi_specialist_id": user_id,
        "opened_period": program["current_period_index"] if program else 0,
        "opportunity_weight_delta": 0.0,
        "opportunity_soi_delta": 0,
        "opportunity_rom_delta": 0,
        "closed_reason": None,
        "status": "DRAFT",
    })
    return success_object(review_out(review), status=201)


@bp.route("/api/cdi-reviews", methods=["GET"])
def list_reviews():
    require_roles(ROLES)
    case_id = request.args.get("patient_case_id")
    program_id = request.args.get("cdi_program_id")
    status = request.args.get("status")
    items = list(db.reviews.values())
    if case_id is not None:
        items = [r for r in items if r["patient_case_id"] == case_id]
    if program_id is not None:
        items = [r for r in items if r["cdi_program_id"] == program_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    page, limit, offset, total = list_page(items)
    return success_list([review_out(r) for r in page], limit, offset, total)


@bp.route("/api/cdi-reviews/<reviewId>", methods=["GET"])
def get_review(reviewId):
    require_roles(ROLES)
    review = get_or_404(db.reviews, reviewId, "review")
    return success_object(review_out(review))


@bp.route("/api/cdi-reviews/<reviewId>/queries", methods=["GET"])
def list_review_queries(reviewId):
    require_roles(QUERY_LIST_ROLES)
    get_or_404(db.reviews, reviewId, "review")
    status = request.args.get("status")
    items = [q for q in db.queries.values() if q["cdi_review_id"] == reviewId]
    if status is not None:
        items = [q for q in items if q["status"] == status]
    page, limit, offset, total = list_page(items)
    return success_list([query_out(q) for q in page], limit, offset, total)


@bp.route("/api/cdi-reviews/<reviewId>/activate", methods=["POST"])
def activate_review(reviewId):
    require_roles({"CDISpecialist"})
    review = get_or_404(db.reviews, reviewId, "review")
    get_json_body()
    program = db.programs.get(review["cdi_program_id"])
    require_program_active(program)
    if review["status"] != "DRAFT":
        raise_error("ERR_INVALID_STATE", "Only a DRAFT review can be activated")
    case = db.cases.get(review["patient_case_id"])
    if case is None or case["status"] not in ("OPEN", "UNDER_REVIEW"):
        raise_error(
            "ERR_CASE_NOT_REVIEWABLE",
            "Parent case is not in OPEN or UNDER_REVIEW",
        )
    if _other_active_review(case["id"], review["id"]):
        raise_error(
            "ERR_REVIEW_ALREADY_ACTIVE",
            "Another review on this case is already ACTIVE",
        )
    review["status"] = "ACTIVE"
    touch(review)
    if case["status"] == "OPEN":
        # Cascade up: first activated review moves the case to UNDER_REVIEW.
        case["status"] = "UNDER_REVIEW"
        touch(case)
    return success_object(review_out(review))


@bp.route("/api/cdi-reviews/<reviewId>/hold", methods=["POST"])
def hold_review(reviewId):
    require_roles({"CDISpecialist"})
    review = get_or_404(db.reviews, reviewId, "review")
    get_json_body()
    program = db.programs.get(review["cdi_program_id"])
    require_program_active(program)
    if review["status"] != "ACTIVE":
        raise_error("ERR_INVALID_STATE", "Only an ACTIVE review can be held")
    for q in db.queries.values():
        if q["cdi_review_id"] == review["id"] and q["status"] in ("SENT", "ESCALATED"):
            raise_error(
                "ERR_UNRESOLVED_QUERY_EXISTS",
                "A pending provider query blocks holding the review",
            )
    review["status"] = "ON_HOLD"
    touch(review)
    return success_object(review_out(review))


@bp.route("/api/cdi-reviews/<reviewId>/resume", methods=["POST"])
def resume_review(reviewId):
    require_roles({"CDISpecialist"})
    review = get_or_404(db.reviews, reviewId, "review")
    get_json_body()
    program = db.programs.get(review["cdi_program_id"])
    require_program_active(program)
    if review["status"] != "ON_HOLD":
        raise_error("ERR_INVALID_STATE", "Only an ON_HOLD review can be resumed")
    case = db.cases.get(review["patient_case_id"])
    if case is None or case["status"] not in ("OPEN", "UNDER_REVIEW"):
        raise_error(
            "ERR_CASE_NOT_REVIEWABLE",
            "Parent case is not in OPEN or UNDER_REVIEW",
        )
    if _other_active_review(case["id"], review["id"]):
        raise_error(
            "ERR_REVIEW_ALREADY_ACTIVE",
            "Another review on this case is already ACTIVE",
        )
    review["status"] = "ACTIVE"
    touch(review)
    return success_object(review_out(review))


@bp.route("/api/cdi-reviews/<reviewId>/close", methods=["POST"])
def close_review(reviewId):
    require_roles({"CDISpecialist"})
    review = get_or_404(db.reviews, reviewId, "review")
    program = db.programs.get(review["cdi_program_id"])
    require_program_active(program)
    if review["status"] not in ("ACTIVE", "ON_HOLD"):
        raise_error(
            "ERR_INVALID_STATE",
            "Only an ACTIVE or ON_HOLD review can be closed",
        )
    body = get_json_body()
    check_known_fields(body, {"closed_reason", "expected_review_version"})
    # OCC (PRD 2.8): expected_review_version is non-optional.
    if "expected_review_version" not in body or body["expected_review_version"] is None:
        raise_error("ERR_INVALID_REQUEST", "expected_review_version is required")
    expected = validate_integer(body["expected_review_version"], "expected_review_version")
    if expected != review["version"]:
        raise_error(
            "ERR_STALE_VERSION",
            "expected_review_version does not match the review's current version",
        )
    require_fields(body, ["closed_reason"])
    reason = validate_enum(body["closed_reason"], CLOSE_REASONS, "closed_reason")
    for q in db.queries.values():
        if q["cdi_review_id"] == review["id"] and q["status"] in (
            "DRAFT", "SENT", "ESCALATED",
        ):
            raise_error(
                "ERR_UNRESOLVED_QUERY_EXISTS",
                "A query in DRAFT/SENT/ESCALATED blocks closing the review",
            )
    review["status"] = "CLOSED"
    review["closed_reason"] = reason
    touch(review)
    case = db.cases.get(review["patient_case_id"])
    if case is not None and case["status"] == "UNDER_REVIEW":
        open_recon = any(
            e for e in db.reconciliations.values()
            if e["patient_case_id"] == case["id"] and e["status"] == "OPEN"
        )
        if not _other_active_review(case["id"], review["id"]) and not open_recon:
            # Cascade up: last ACTIVE review closed, no open reconciliation.
            case["status"] = "OPEN"
            touch(case)
    return success_object(review_out(review))
