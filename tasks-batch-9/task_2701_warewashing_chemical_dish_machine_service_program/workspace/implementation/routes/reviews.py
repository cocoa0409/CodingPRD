"""Usage-variance reviews and the investigation cases they escalate into."""

from flask import Blueprint

import db
import middleware
import response
from errors import ApiError
from middleware import ROLE_ACCOUNT_MANAGER, ROLE_QUALITY_AUDITOR
from routes import common
from services import calc, derive, reports
from util import midnight

bp = Blueprint("reviews", __name__)

BASES = ("NAMEPLATE", "AS_CALIBRATED")
CLAIMING_STATUSES = ("PUBLISHED", "ESCALATED", "CLOSED")
SUSPECT_CLASSIFICATIONS = ("THEFT_SUSPECT", "DILUTION_SUSPECT")


def _overlaps(site_id, product_id, start, end, skip_id=None):
    for other in db.rows("usage_variance_reviews"):
        if other["id"] == skip_id:
            continue
        if other["site_id"] != site_id or other["product_id"] != product_id:
            continue
        if other["status"] not in CLAIMING_STATUSES:
            continue
        if start < other["period_end"] and other["period_start"] < end:
            return True
    return False


@bp.route("/usage-variance-reviews", methods=["POST"])
def create_review():
    user_id, _role = middleware.require_roles(ROLE_QUALITY_AUDITOR)
    body = middleware.body_object()
    site_id = middleware.f_str(body, "site_id", required=True)
    product_id = middleware.f_str(body, "product_id", required=True)
    start = middleware.f_dt(body, "period_start", required=True)
    end = middleware.f_dt(body, "period_end", required=True)
    basis = middleware.f_enum(body, "basis", BASES, required=True)
    opening = middleware.f_int(
        body, "opening_inventory_ml", required=True, minimum=0
    )
    ending = middleware.f_int(
        body, "ending_inventory_ml", required=True, minimum=0
    )
    if not start < end:
        middleware.bad("period_start must be earlier than period_end")

    site = middleware.must_reference("sites", site_id, "site_id")
    product = middleware.must_reference(
        "chemical_products", product_id, "product_id"
    )

    agreement = derive.covering_agreement_of_site(site)
    inside = False
    if agreement is not None and agreement["term_end_date"] is not None:
        inside = (start >= midnight(agreement["start_date"])
                  and end <= midnight(agreement["term_end_date"]))
    if not inside:
        raise ApiError(
            "ERR_PERIOD_OUTSIDE_AGREEMENT_TERM",
            "The window is not inside the covering agreement's term",
        )
    if _overlaps(site_id, product_id, start, end):
        raise ApiError(
            "ERR_REVIEW_PERIOD_OVERLAP",
            "A claimed review window already covers part of this period",
        )

    row = db.insert("usage_variance_reviews", {
        "site_id": site_id,
        "product_id": product_id,
        "period_start": start,
        "period_end": end,
        "basis": basis,
        "opening_inventory_ml": opening,
        "ending_inventory_ml": ending,
        "status": "DRAFT",
        "created_by_user_id": user_id,
        "published_by_user_id": None,
    })
    row.update(reports.compute_review_figures(row, site, product))
    return response.created(response.serialize(row))


@bp.route("/usage-variance-reviews/<review_id>", methods=["GET"])
def read_review(review_id):
    middleware.require_roles(ROLE_QUALITY_AUDITOR, ROLE_ACCOUNT_MANAGER)
    row = middleware.must_exist(
        "usage_variance_reviews", review_id, "UsageVarianceReview"
    )
    return response.ok(response.serialize(row))


@bp.route("/usage-variance-reviews", methods=["GET"])
def list_reviews():
    middleware.require_roles(ROLE_QUALITY_AUDITOR, ROLE_ACCOUNT_MANAGER)
    limit, offset = middleware.pagination()
    rows = common.apply_filters(db.rows("usage_variance_reviews"), (
        ("site_id", "site_id"),
        ("product_id", "product_id"),
        ("status", "status"),
        ("classification", "classification"),
        ("basis", "basis"),
    ))
    return common.listing(rows, limit, offset)


@bp.route("/usage-variance-reviews/<review_id>/publish", methods=["POST"])
def publish_review(review_id):
    user_id, _role = middleware.require_roles(ROLE_QUALITY_AUDITOR)
    middleware.body_object()
    review = middleware.must_exist(
        "usage_variance_reviews", review_id, "UsageVarianceReview"
    )
    if review["status"] != "DRAFT":
        raise ApiError(
            "ERR_REVIEW_NOT_DRAFT",
            "The review is %s, not DRAFT" % review["status"],
        )
    if user_id == review["created_by_user_id"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "The drafting auditor may not publish the review",
        )
    site = db.get("sites", review["site_id"])
    if site is not None and site["service_posture"] == "CRITICAL":
        raise ApiError(
            "ERR_SITE_POSTURE_CRITICAL",
            "The site's service posture is CRITICAL",
        )
    if (review["classification"] == "INSUFFICIENT_DATA"
            or not review["rack_count_in_period"]
            or not review["expected_consumption_ml"]):
        raise ApiError(
            "ERR_INSUFFICIENT_TELEMETRY",
            "The window carries no usable telemetry",
        )
    if _overlaps(review["site_id"], review["product_id"],
                 review["period_start"], review["period_end"], review["id"]):
        raise ApiError(
            "ERR_REVIEW_PERIOD_OVERLAP",
            "Another review has claimed this window since the draft was made",
        )

    review["status"] = "PUBLISHED"
    review["published_by_user_id"] = user_id
    db.mark(review)
    return response.ok(response.serialize(review))


@bp.route("/usage-variance-reviews/<review_id>/close", methods=["POST"])
def close_review(review_id):
    middleware.require_roles(ROLE_QUALITY_AUDITOR)
    middleware.body_object()
    review = middleware.must_exist(
        "usage_variance_reviews", review_id, "UsageVarianceReview"
    )
    if review["status"] != "PUBLISHED":
        raise ApiError(
            "ERR_REVIEW_NOT_PUBLISHED",
            "The review is %s, not PUBLISHED" % review["status"],
        )
    if review["classification"] in SUSPECT_CLASSIFICATIONS:
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "A %s review must be escalated, not closed"
            % review["classification"],
        )
    review["status"] = "CLOSED"
    db.mark(review)
    return response.ok(response.serialize(review))


# --------------------------------------------------------------------------
# investigation cases (PRD 3.8)
# --------------------------------------------------------------------------

OPEN_REASONS = ("SUSPECTED_THEFT", "SUSPECTED_DILUTION", "DISPENSER_FAULT")
EVIDENCE_TYPES = (
    "DELIVERY_LOG", "TELEMETRY_EXPORT", "CALIBRATION_HISTORY",
    "INVENTORY_COUNT", "CCTV_REVIEW", "STAFF_INTERVIEW",
)
DECISIONS = ("SUBSTANTIATE", "DISMISS", "RETURN")
REMEDIATIONS = ("TRAINING", "DISPENSER_REPLACEMENT", "CHARGEBACK")


def _case_of_review(review_id):
    for case in db.rows("investigation_cases"):
        if case["variance_review_id"] == review_id:
            return case
    return None


@bp.route("/investigation-cases", methods=["POST"])
def open_case():
    user_id, _role = middleware.require_roles(ROLE_QUALITY_AUDITOR)
    body = middleware.body_object()
    review_id = middleware.f_str(body, "variance_review_id", required=True)
    reason = middleware.f_enum(
        body, "opened_reason", OPEN_REASONS, required=True
    )

    review = middleware.must_reference(
        "usage_variance_reviews", review_id, "variance_review_id"
    )
    # The one-case-per-review guard has to precede the PUBLISHED test,
    # because opening the first case already moved the review to ESCALATED.
    if _case_of_review(review_id) is not None:
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "The review already has an investigation case",
        )
    if review["status"] != "PUBLISHED":
        raise ApiError(
            "ERR_REVIEW_NOT_PUBLISHED",
            "The review is %s, not PUBLISHED" % review["status"],
        )

    case = db.insert("investigation_cases", {
        "variance_review_id": review_id,
        "opened_reason": reason,
        "case_status": "EVIDENCE_GATHERING",
        "opened_by_user_id": user_id,
        "evidence_item_count": 0,
        "return_count": 0,
        "remediation": "NONE",
        "chargeback_cents": 0,
        "reviewed_by_user_id": None,
        "finding_note": None,
    })
    review["status"] = "ESCALATED"
    db.mark(review)
    return response.created(response.serialize(case))


@bp.route("/investigation-cases/<case_id>", methods=["GET"])
def read_case(case_id):
    middleware.require_roles(ROLE_QUALITY_AUDITOR, ROLE_ACCOUNT_MANAGER)
    row = middleware.must_exist(
        "investigation_cases", case_id, "InvestigationCase"
    )
    return response.ok(response.serialize(row))


@bp.route("/investigation-cases", methods=["GET"])
def list_cases():
    middleware.require_roles(ROLE_QUALITY_AUDITOR, ROLE_ACCOUNT_MANAGER)
    limit, offset = middleware.pagination()
    rows = common.apply_filters(db.rows("investigation_cases"), (
        ("variance_review_id", "variance_review_id"),
        ("case_status", "case_status"),
        ("status", "case_status"),
        ("opened_reason", "opened_reason"),
        ("remediation", "remediation"),
    ))
    return common.listing(rows, limit, offset)


@bp.route("/investigation-cases/<case_id>/submit-for-review", methods=["POST"])
def submit_case(case_id):
    middleware.require_roles(ROLE_QUALITY_AUDITOR)
    body = middleware.body_object()
    types = middleware.f_str_list(body, "evidence_types", required=True)
    for item in types:
        if item not in EVIDENCE_TYPES:
            middleware.bad("%s is not a declared evidence type" % item)

    case = middleware.must_exist(
        "investigation_cases", case_id, "InvestigationCase"
    )
    if case["case_status"] != "EVIDENCE_GATHERING":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "The case is %s, not EVIDENCE_GATHERING" % case["case_status"],
        )

    case["case_status"] = "PENDING_REVIEW"
    case["evidence_item_count"] = case["evidence_item_count"] + len(types)
    db.mark(case)
    return response.ok(response.serialize(case))


@bp.route("/investigation-cases/<case_id>/review", methods=["POST"])
def adjudicate_case(case_id):
    user_id, _role = middleware.require_roles(ROLE_QUALITY_AUDITOR)
    body = middleware.body_object()
    decision = middleware.f_enum(body, "decision", DECISIONS, required=True)
    remediation = middleware.f_enum(body, "remediation", REMEDIATIONS)
    note = middleware.f_str(body, "finding_note", max_len=1000)
    if decision == "SUBSTANTIATE" and remediation is None:
        middleware.bad("remediation is required to substantiate a case")

    case = middleware.must_exist(
        "investigation_cases", case_id, "InvestigationCase"
    )
    if case["case_status"] != "PENDING_REVIEW":
        raise ApiError(
            "ERR_CASE_NOT_IN_REVIEW",
            "The case is %s, not PENDING_REVIEW" % case["case_status"],
        )
    if decision == "SUBSTANTIATE" and case["evidence_item_count"] < 2:
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "A single evidence item cannot substantiate a finding",
        )

    review = db.get("usage_variance_reviews", case["variance_review_id"])
    published_by = review["published_by_user_id"] if review else None
    if user_id == case["opened_by_user_id"] or user_id == published_by:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "Adjudication needs an auditor independent of this case",
        )

    if note is not None:
        case["finding_note"] = note

    if decision == "RETURN":
        case["case_status"] = "EVIDENCE_GATHERING"
        case["return_count"] = case["return_count"] + 1
        db.mark(case)
        return response.ok(response.serialize(case))

    case["reviewed_by_user_id"] = user_id
    if decision == "DISMISS":
        case["case_status"] = "UNSUBSTANTIATED"
        case["remediation"] = "NONE"
        case["chargeback_cents"] = 0
    else:
        case["case_status"] = "SUBSTANTIATED"
        case["remediation"] = remediation
        chargeback = 0
        if remediation == "CHARGEBACK" and review is not None:
            product = db.get("chemical_products", review["product_id"])
            if product is not None:
                chargeback = calc.theft_chargeback(review, product)
        case["chargeback_cents"] = chargeback
    db.mark(case)
    if review is not None:
        derive.cascade_gamma(case, review)
    return response.ok(response.serialize(case))
