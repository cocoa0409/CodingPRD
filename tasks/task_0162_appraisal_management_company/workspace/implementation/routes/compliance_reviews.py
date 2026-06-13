"""Compliance review endpoints: fetch, finalize."""
from flask import Blueprint

import db
import errors
import middleware
import response
from services import cascade, firewall, serialize, validate

bp = Blueprint("compliance_reviews", __name__)


@bp.route("/amc/compliance-reviews/<cid>", methods=["GET"])
def get_review(cid):
    _, role = middleware.authenticate()
    middleware.require_roles(role, {"AMCCoordinator", "PlatformAdmin", "ComplianceReviewer"})
    review = db.compliance_reviews.get(cid)
    if review is None:
        raise errors.not_found("Compliance review not found.")
    return response.ok_object(serialize.public(review), 200)


@bp.route("/amc/compliance-reviews/<cid>/finalize", methods=["POST"])
def finalize_review(cid):
    _, role = middleware.authenticate()

    # Priority 2: AIR firewall — LenderUser blocked, FirewallEvent logged.
    if role == "LenderUser":
        order_id = _order_id_for_review(cid)
        firewall.block_and_log(order_id, role, "FINALIZE_COMPLIANCE")

    # Priority 3: generic authorization.
    middleware.require_roles(role, {"ComplianceReviewer", "PlatformAdmin"})

    # Priority 4: existence.
    review = db.compliance_reviews.get(cid)
    if review is None:
        raise errors.not_found("Compliance review not found.")

    data = validate.body()

    # State legality (priority 7): finalize defined only from PENDING.
    if review["outcome"] != "PENDING":
        raise errors.invalid_state("Compliance review is not PENDING.")

    # Field-shape (priority 14): finding_codes optional list of strings.
    finding_codes = data.get("finding_codes")
    if finding_codes is None:
        finding_codes = []
    if not isinstance(finding_codes, list) or not all(isinstance(x, str) for x in finding_codes):
        raise errors.invalid_request("finding_codes must be a list of strings.")

    report = db.reports.get(review["report_id"])

    uspap_met = review["uspap_comp_minimum_met"]
    uad_valid = review["uad_ratings_valid"]
    has_uspap_code = any(_is_uspap_code(c) for c in finding_codes)

    # Outcome determination (PRD §3.5), three mutually exclusive branches.
    if (not uspap_met) or (not uad_valid) or has_uspap_code:
        outcome = "FAIL"
    elif len(finding_codes) == 0:
        outcome = "PASS"
    else:
        # both booleans true, non-empty, all non-USPAP advisory codes.
        outcome = "CONDITIONAL"

    review["outcome"] = outcome
    review["finding_codes"] = list(finding_codes)
    db.touch(review)

    if outcome in ("PASS", "CONDITIONAL"):
        if report is not None:
            cascade.deliver_cascade(report)
    else:
        # FAIL: create RevisionRequest (origin COMPLIANCE, OPEN) then cascade.
        if report is not None:
            rr = {
                "report_id": report["id"],
                "reason_category": "USPAP_DEFICIENCY",
                "origin": "COMPLIANCE",
                "status": "OPEN",
            }
            db.stamp_create(rr)
            db.revision_requests[rr["id"]] = rr
            cascade.open_revision_cascade(report)

    return response.ok_object(serialize.public(review), 200)


def _is_uspap_code(code):
    """A USPAP code is identified by a 'USPAP' prefix (case-insensitive).
    Advisory/non-USPAP codes use any other prefix (e.g. UAD_, ADVISORY_)."""
    return isinstance(code, str) and code.upper().startswith("USPAP")


def _order_id_for_review(cid):
    review = db.compliance_reviews.get(cid)
    if review is None:
        return None
    report = db.reports.get(review.get("report_id"))
    if report is None:
        return None
    assignment = db.assignments.get(report.get("assignment_id"))
    if assignment is None:
        return None
    return assignment.get("order_id")
