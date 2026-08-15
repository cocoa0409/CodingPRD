"""MonitoringReview endpoints."""

from datetime import date
from flask import Blueprint, request

from db import store, new_id, parse_date
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_RESOURCE_NOT_FOUND, ERR_INVALID_STATE,
    ERR_REVIEW_INTERVAL_TOO_SHORT, ERR_REVIEW_NOT_CLOSABLE,
)
from middleware import require_auth, ALL_ROLES
from response import success, paginate
from services.core import stamp_new, touch, get_engagement_or_404, recompute_scope_creep

bp = Blueprint("reviews", __name__)

SEVERITIES = {"LOW", "MEDIUM", "HIGH"}


@bp.route("/api/engagements/<eid>/reviews", methods=["POST"])
def schedule_review(eid):
    require_auth(["ComplianceOfficer"])
    body = request.get_json(silent=True) or {}
    scheduled_date = body.get("scheduled_date")
    sd = parse_date(scheduled_date)
    if sd is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "scheduled_date must be an ISO date")

    eng = get_engagement_or_404(eid)
    if eng["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409, "Review scheduling requires ACTIVE engagement")

    for r in store.reviews.values():
        if r["engagement_id"] != eid:
            continue
        other = parse_date(r["scheduled_date"])
        if other is None:
            continue
        if abs((sd - other).days) < 30:
            raise ApiError(ERR_REVIEW_INTERVAL_TOO_SHORT, 409,
                           "Reviews must be at least 30 days apart")

    review = {
        "id": new_id(),
        "engagement_id": eid,
        "scheduled_date": scheduled_date,
        "findings": [],
        "remediation_action_ids": [],
        "findings_count": 0,
        "outcome": None,
        "status": "SCHEDULED",
    }
    stamp_new(review)
    store.reviews[review["id"]] = review
    return success(review, status=201)


@bp.route("/api/engagements/<eid>/reviews", methods=["GET"])
def list_reviews(eid):
    require_auth(ALL_ROLES)
    get_engagement_or_404(eid)
    items = [r for r in store.reviews.values() if r["engagement_id"] == eid]
    items.sort(key=lambda r: r["created_at"])
    page, pg = paginate(items, request.args)
    return success(page, pagination=pg)


@bp.route("/api/reviews/<rid>/close", methods=["POST"])
def close_review(rid):
    require_auth(["ComplianceOfficer"])
    body = request.get_json(silent=True) or {}
    findings = body.get("findings")
    remediation_action_ids = body.get("remediation_action_ids")
    if findings is None or not isinstance(findings, list):
        raise ApiError(ERR_INVALID_REQUEST, 400, "findings must be a list")
    for f in findings:
        if not isinstance(f, dict) or f.get("severity") not in SEVERITIES:
            raise ApiError(ERR_INVALID_REQUEST, 400, "invalid finding entry")
        if not isinstance(f.get("description"), str):
            raise ApiError(ERR_INVALID_REQUEST, 400, "finding description must be a string")
    if remediation_action_ids is None or not isinstance(remediation_action_ids, list):
        raise ApiError(ERR_INVALID_REQUEST, 400, "remediation_action_ids must be a list")

    review = store.reviews.get(rid)
    if review is None:
        raise ApiError(ERR_RESOURCE_NOT_FOUND, 404, "Review not found")
    if review["status"] != "SCHEDULED":
        raise ApiError(ERR_INVALID_STATE, 409, "Review is not SCHEDULED")

    if findings:
        if not remediation_action_ids:
            raise ApiError(ERR_REVIEW_NOT_CLOSABLE, 422,
                           "Findings require remediation_action_ids")
        eng = store.engagements.get(review["engagement_id"])
        contractor_id = eng["contractor_id"] if eng else None
        for ra_id in remediation_action_ids:
            ra = store.remediation_actions.get(ra_id)
            if ra is None:
                raise ApiError(ERR_REVIEW_NOT_CLOSABLE, 422,
                               "Referenced remediation action does not exist")
            if ra["status"] != "OPEN":
                raise ApiError(ERR_REVIEW_NOT_CLOSABLE, 422,
                               "Referenced remediation action is not OPEN")
            audit = store.audits.get(ra["audit_id"])
            if audit is None or audit["contractor_id"] != contractor_id:
                raise ApiError(ERR_REVIEW_NOT_CLOSABLE, 422,
                               "Remediation action belongs to a different contractor")

    review["findings"] = findings
    review["remediation_action_ids"] = remediation_action_ids
    review["findings_count"] = len(findings)
    review["outcome"] = "CLEARED" if len(findings) == 0 else "FINDINGS_FILED"
    review["status"] = "CLOSED"
    touch(review)
    eng = store.engagements.get(review["engagement_id"])
    if eng is not None:
        recompute_scope_creep(eng)
    return success(review)
