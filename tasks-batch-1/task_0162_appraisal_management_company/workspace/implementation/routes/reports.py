"""Report endpoints: fetch, open compliance review, open revision request, lists."""
from flask import Blueprint

import db
import errors
import middleware
import response
from services import calculations as calc
from services import cascade, firewall, pagination, serialize, validate

bp = Blueprint("reports", __name__)

REASON_CATEGORIES = {"USPAP_DEFICIENCY", "UAD_DEFICIENCY", "DATA_CORRECTION", "VALUE_DISPUTE"}


# ---------------------------------------------------------------------------
# GET /amc/reports/{id}
# ---------------------------------------------------------------------------
@bp.route("/amc/reports/<rid>", methods=["GET"])
def get_report(rid):
    _, role = middleware.authenticate()
    middleware.require_roles(
        role, {"AMCCoordinator", "PlatformAdmin", "ComplianceReviewer", "Appraiser"})
    report = db.reports.get(rid)
    if report is None:
        raise errors.not_found("Report not found.")
    return response.ok_object(serialize.public(report), 200)


# ---------------------------------------------------------------------------
# POST /amc/reports/{id}/compliance-reviews
# ---------------------------------------------------------------------------
@bp.route("/amc/reports/<rid>/compliance-reviews", methods=["POST"])
def open_compliance_review(rid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"ComplianceReviewer", "PlatformAdmin"})
    report = db.reports.get(rid)
    if report is None:
        raise errors.not_found("Report not found.")

    # State legality (priority 7): report in SUBMITTED or RESUBMITTED.
    if report["status"] not in ("SUBMITTED", "RESUBMITTED"):
        raise errors.invalid_state("Report is not awaiting compliance review.")

    uspap_met = report["comparable_count"] >= calc.USPAP_MIN_COMPARABLES
    uad_valid = (report["uad_condition_rating"] in calc.UAD_CONDITION_SET
                 and report["uad_quality_rating"] in calc.UAD_QUALITY_SET)

    review = {
        "report_id": rid,
        "uspap_comp_minimum_met": bool(uspap_met),
        "uad_ratings_valid": bool(uad_valid),
        "outcome": "PENDING",
        "finding_codes": [],
    }
    db.stamp_create(review)
    db.compliance_reviews[review["id"]] = review

    report["status"] = "UNDER_REVIEW"
    db.touch(report)

    return response.ok_object(serialize.public(review), 201)


# ---------------------------------------------------------------------------
# GET /amc/reports/{id}/compliance-reviews
# ---------------------------------------------------------------------------
@bp.route("/amc/reports/<rid>/compliance-reviews", methods=["GET"])
def list_compliance_reviews(rid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"AMCCoordinator", "PlatformAdmin", "ComplianceReviewer"})
    report = db.reports.get(rid)
    if report is None:
        raise errors.not_found("Report not found.")
    limit, offset = pagination.parse()
    items = [c for c in db.compliance_reviews.values() if c.get("report_id") == rid]
    page, total = pagination.apply(items, limit, offset)
    return response.ok_array([serialize.public(c) for c in page], limit, offset, total)


# ---------------------------------------------------------------------------
# POST /amc/reports/{id}/revision-requests  — manual revision request
# ---------------------------------------------------------------------------
@bp.route("/amc/reports/<rid>/revision-requests", methods=["POST"])
def open_revision_request(rid):
    _, role = middleware.authenticate()

    # Peek at reason_category for the firewall decision (priority 2).
    data = validate.body()
    reason_peek = data.get("reason_category")

    # Priority 2: AIR firewall. LenderUser opening a VALUE_DISPUTE is firewalled.
    if role == "LenderUser" and reason_peek == "VALUE_DISPUTE":
        order_id = _order_id_for_report(rid)
        firewall.block_and_log(order_id, role, "OPEN_VALUE_DISPUTE")

    # Priority 3: generic authorization (LenderUser not permitted otherwise).
    middleware.require_roles(role, {"AMCCoordinator", "ComplianceReviewer", "PlatformAdmin"})

    # Priority 4: existence.
    report = db.reports.get(rid)
    if report is None:
        raise errors.not_found("Report not found.")

    # State legality (priority 7): a manual revision can be opened on a report
    # that is under review (the head-of-cascade drives it to REVISION_REQUESTED).
    if report["status"] not in ("SUBMITTED", "RESUBMITTED", "UNDER_REVIEW"):
        raise errors.invalid_state("Report is not in a state that accepts a revision request.")

    # Field-shape (priority 14).
    reason_category = validate.require_enum(data, "reason_category", REASON_CATEGORIES)

    rr = {
        "report_id": rid,
        "reason_category": reason_category,
        "origin": "MANUAL",
        "status": "OPEN",
    }
    db.stamp_create(rr)
    db.revision_requests[rr["id"]] = rr

    # Head-of-cascade: Report -> REVISION_REQUESTED -> Assignment REVISION ->
    # Order IN_QC -> IN_PROGRESS (FeeSplit penalty recompute).
    cascade.open_revision_cascade(report)

    return response.ok_object(serialize.public(rr), 201)


# ---------------------------------------------------------------------------
# GET /amc/reports/{id}/revision-requests
# ---------------------------------------------------------------------------
@bp.route("/amc/reports/<rid>/revision-requests", methods=["GET"])
def list_revision_requests(rid):
    _, role = middleware.authenticate()
    middleware.require_roles(
        role, {"AMCCoordinator", "PlatformAdmin", "ComplianceReviewer", "Appraiser"})
    report = db.reports.get(rid)
    if report is None:
        raise errors.not_found("Report not found.")
    limit, offset = pagination.parse()
    items = [r for r in db.revision_requests.values() if r.get("report_id") == rid]
    page, total = pagination.apply(items, limit, offset)
    return response.ok_array([serialize.public(r) for r in page], limit, offset, total)


def _order_id_for_report(rid):
    report = db.reports.get(rid)
    if report is None:
        return None
    assignment = db.assignments.get(report.get("assignment_id"))
    if assignment is None:
        return None
    return assignment.get("order_id")
