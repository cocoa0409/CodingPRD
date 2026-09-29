"""Market report shells, aggregation, disclosure review and release (PRD §3.6)."""

from flask import Blueprint

import clock
import constants
import db
import lookup
import response
import serializers
import validators as V
from errors import (
    ApiError,
    ERR_CONFIDENTIALITY_SUPPRESSION_REQUIRED,
    ERR_DISCLOSURE_NOT_REVIEWED,
    ERR_NO_ELIGIBLE_DATA,
    ERR_PUBLICATION_BEFORE_RELEASE_TIME,
    ERR_REPORT_ALREADY_PUBLISHED,
    ERR_REPORT_NOT_COMPUTED,
    ERR_REPORT_NOT_PUBLISHED,
    ERR_SPECIES_CLASS_MISMATCH,
    ERR_WINDOW_NOT_LOCKED,
)
from middleware import (
    ROLE_COMPLIANCE_AUDITOR,
    ROLE_MARKET_ANALYST,
    ROLE_PENALTY_OFFICER,
    ROLE_PROGRAM_ADMIN,
    ROLE_PUBLIC_USER,
    ROLE_REPORTER_AGENT,
    is_public_user,
    roles,
)
from numeric import pct
from services import calculations

bp = Blueprint("market_reports", __name__)

WRITE_ROLES = (ROLE_MARKET_ANALYST, ROLE_PROGRAM_ADMIN)
READ_ROLES = (
    ROLE_MARKET_ANALYST,
    ROLE_PROGRAM_ADMIN,
    ROLE_COMPLIANCE_AUDITOR,
    ROLE_PENALTY_OFFICER,
    ROLE_REPORTER_AGENT,
    ROLE_PUBLIC_USER,
)


def _require_category_compatible(category, window):
    expected = constants.CATEGORY_COMPATIBILITY[category]
    if (window["species"], window["report_class"]) != expected:
        raise ApiError(
            ERR_SPECIES_CLASS_MISMATCH,
            "Category %s requires a %s window of class %s." % (category, expected[0], expected[1]),
        )


@bp.post("/market-reports")
@roles(*WRITE_ROLES)
def create_market_report():
    payload = V.body()
    window_id = V.get_string(payload, "reporting_window_id")
    category = V.get_enum(payload, "category", V.CATEGORIES)
    weighting_variant = V.get_enum(payload, "weighting_variant", V.WEIGHTING_VARIANTS)
    purchase_type_filter = V.get_enum(
        payload,
        "purchase_type_filter",
        V.PURCHASE_TYPE_FILTERS,
        required=False,
        default="ALL_PRICED",
    )

    window = lookup.reporting_window(window_id)
    _require_category_compatible(category, window)

    rec = db.insert(
        db.market_reports,
        {
            "reporting_window_id": window_id,
            "category": category,
            "weighting_variant": weighting_variant,
            "purchase_type_filter": purchase_type_filter,
            "aggregation_state": "PENDING",
            "disclosure_state": "UNREVIEWED",
            "publication_state": "UNPUBLISHED",
            "weighted_average_price_per_cwt": None,
            "price_low_per_cwt": None,
            "price_high_per_cwt": None,
            "total_head": None,
            "total_pounds": None,
            "reporter_count": 0,
            "max_reporter_share_pct": pct(0),
            "source_submission_count": 0,
            "suppression_reason": None,
            "computed_at": None,
            "published_at": None,
        },
    )
    return response.object_response(serializers.market_report(rec), 201)


@bp.post("/market-reports/<report_id>/compute")
@roles(*WRITE_ROLES)
def compute(report_id):
    rec = lookup.market_report(report_id)
    window = db.reporting_windows[rec["reporting_window_id"]]

    has_data = any(
        s["reporting_window_id"] == window["id"] and s["status"] == "ACCEPTED"
        for s in db.submissions.values()
    )
    if not has_data:
        raise ApiError(
            ERR_NO_ELIGIBLE_DATA,
            "No submission of the window is in ACCEPTED status.",
        )

    _require_category_compatible(rec["category"], window)

    calculations.aggregate_market_report(rec, window)
    rec["aggregation_state"] = "COMPUTED"
    rec["disclosure_state"] = "UNREVIEWED"
    rec["suppression_reason"] = None
    db.touch(rec)
    return response.object_response(serializers.market_report(rec))


@bp.post("/market-reports/<report_id>/disclosure-review")
@roles(*WRITE_ROLES)
def disclosure_review(report_id):
    rec = lookup.market_report(report_id)

    if rec["aggregation_state"] != "COMPUTED":
        raise ApiError(
            ERR_REPORT_NOT_COMPUTED,
            "The report's arithmetic is not current; recompute before reviewing.",
        )

    window = db.reporting_windows[rec["reporting_window_id"]]
    reason = calculations.evaluate_confidentiality(rec, window)

    if reason is None:
        rec["suppression_reason"] = None
        rec["disclosure_state"] = "CLEARED"
    else:
        rec["suppression_reason"] = reason
        rec["disclosure_state"] = "WITHHELD"
        calculations.mask_withheld(rec)

    db.touch(rec)
    return response.object_response(serializers.market_report(rec))


@bp.post("/market-reports/<report_id>/publish")
@roles(*WRITE_ROLES)
def publish(report_id):
    rec = lookup.market_report(report_id)

    if rec["aggregation_state"] != "COMPUTED":
        raise ApiError(
            ERR_REPORT_NOT_COMPUTED,
            "Only a COMPUTED report may be released.",
        )
    if rec["disclosure_state"] == "UNREVIEWED":
        raise ApiError(
            ERR_DISCLOSURE_NOT_REVIEWED,
            "The confidentiality review has not been performed.",
        )
    if rec["publication_state"] != "UNPUBLISHED":
        raise ApiError(
            ERR_REPORT_ALREADY_PUBLISHED,
            "The report has already been released once; publication is not idempotent.",
        )
    if rec["disclosure_state"] == "WITHHELD":
        raise ApiError(
            ERR_CONFIDENTIALITY_SUPPRESSION_REQUIRED,
            "A withheld report may never be released.",
        )

    window = db.reporting_windows[rec["reporting_window_id"]]
    if clock.now() < window["_publication_release_utc"]:
        raise ApiError(
            ERR_PUBLICATION_BEFORE_RELEASE_TIME,
            "The window's publication release instant has not been reached.",
        )
    if window["status"] not in ("LOCKED", "PUBLISHED"):
        raise ApiError(
            ERR_WINDOW_NOT_LOCKED,
            "The window is still collecting; lock it before releasing a report.",
        )

    rec["publication_state"] = "PUBLISHED"
    rec["published_at"] = clock.iso_now()
    db.touch(rec)

    if window["status"] == "LOCKED":
        window["status"] = "PUBLISHED"
        db.touch(window)

    return response.object_response(serializers.market_report(rec))


@bp.get("/market-reports/<report_id>")
@roles(*READ_ROLES)
def get_market_report(report_id):
    rec = lookup.market_report(report_id)
    if is_public_user() and rec["publication_state"] != "PUBLISHED":
        raise ApiError(
            ERR_REPORT_NOT_PUBLISHED,
            "Only a published market report is visible to the public.",
        )
    return response.object_response(serializers.market_report(rec))


@bp.get("/market-reports")
@roles(*READ_ROLES)
def list_market_reports():
    limit, offset = V.pagination()
    window_id = V.query_str("reporting_window_id")
    category = V.query_str("category")
    weighting_variant = V.query_str("weighting_variant")
    publication_state = V.query_str("publication_state")
    disclosure_state = V.query_str("disclosure_state")

    if is_public_user() and publication_state is not None and publication_state != "PUBLISHED":
        raise ApiError(
            ERR_REPORT_NOT_PUBLISHED,
            "Only published market reports are visible to the public.",
        )

    records = db.ordered(db.market_reports.values())
    if is_public_user():
        records = [r for r in records if r["publication_state"] == "PUBLISHED"]
    if window_id is not None:
        records = [r for r in records if r["reporting_window_id"] == window_id]
    if category is not None:
        records = [r for r in records if r["category"] == category]
    if weighting_variant is not None:
        records = [r for r in records if r["weighting_variant"] == weighting_variant]
    if publication_state is not None:
        records = [r for r in records if r["publication_state"] == publication_state]
    if disclosure_state is not None:
        records = [r for r in records if r["disclosure_state"] == disclosure_state]

    page, total = V.paginate(records, limit, offset)
    return response.array_response(
        [serializers.market_report(r) for r in page], limit, offset, total
    )
