"""Methodology change docket, public comment and restatement (PRD §3.9)."""

from datetime import timedelta

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
    ERR_COMMENT_PERIOD_NOT_ENDED,
    ERR_COMMENT_PERIOD_TOO_SHORT,
    ERR_EFFECTIVE_DATE_TOO_SOON,
    ERR_INVALID_METHODOLOGY_STATE,
    ERR_NO_PUBLIC_COMMENTS,
)
from middleware import (
    ROLE_COMPLIANCE_AUDITOR,
    ROLE_MARKET_ANALYST,
    ROLE_PENALTY_OFFICER,
    ROLE_PROGRAM_ADMIN,
    ROLE_PUBLIC_USER,
    ROLE_REPORTER_AGENT,
    roles,
)
from services import cascades

bp = Blueprint("methodology", __name__)

READ_ROLES = (
    ROLE_PROGRAM_ADMIN,
    ROLE_MARKET_ANALYST,
    ROLE_COMPLIANCE_AUDITOR,
    ROLE_PENALTY_OFFICER,
    ROLE_REPORTER_AGENT,
    ROLE_PUBLIC_USER,
)
COMMENT_ROLES = (ROLE_PUBLIC_USER, ROLE_REPORTER_AGENT, ROLE_PROGRAM_ADMIN)


def _require_state(change, *allowed):
    if change["status"] not in allowed:
        raise ApiError(
            ERR_INVALID_METHODOLOGY_STATE,
            "A docket in status %s does not permit this action." % change["status"],
        )


@bp.post("/methodology-changes")
@roles(ROLE_PROGRAM_ADMIN)
def create_change():
    payload = V.body()
    change_code = V.get_string(payload, "change_code", max_len=200)
    affected_category = V.get_enum(payload, "affected_category", V.CATEGORIES)
    proposed_variant = V.get_enum(
        payload, "proposed_weighting_variant", V.WEIGHTING_VARIANTS
    )
    comment_end_raw, comment_end = V.get_datetime(payload, "comment_period_end")
    effective_raw, effective_from = V.get_datetime(payload, "effective_from")

    duplicate = any(c["change_code"] == change_code for c in db.methodology_changes.values())
    if duplicate:
        raise V.bad("change_code must be unique across all methodology changes.")

    if comment_end < clock.now() + timedelta(days=constants.MIN_COMMENT_DAYS):
        raise ApiError(
            ERR_COMMENT_PERIOD_TOO_SHORT,
            "comment_period_end must be at least 30 days after the logical clock.",
        )
    if effective_from < comment_end + timedelta(days=constants.MIN_NOTICE_DAYS):
        raise ApiError(
            ERR_EFFECTIVE_DATE_TOO_SOON,
            "effective_from must be at least 30 days after comment_period_end.",
        )

    rec = db.insert(
        db.methodology_changes,
        {
            "change_code": change_code,
            "affected_category": affected_category,
            "proposed_weighting_variant": proposed_variant,
            "comment_period_end": comment_end_raw,
            "_comment_period_end": comment_end,
            "effective_from": effective_raw,
            "_effective_from": effective_from,
            "status": "COMMENT_OPEN",
            "comment_count": 0,
            "industry_notice_issued_at": None,
            "restated_report_count": 0,
        },
    )
    return response.object_response(serializers.methodology_change(rec), 201)


@bp.post("/methodology-changes/<change_id>/comments")
@roles(*COMMENT_ROLES)
def add_comment(change_id):
    payload = V.body()
    commenter_reference = V.get_string(payload, "commenter_reference", max_len=120)
    comment_text = V.get_string(payload, "comment_text", max_len=4000)
    stance = V.get_enum(payload, "stance", V.STANCES)

    change = lookup.methodology_change(change_id)
    _require_state(change, "COMMENT_OPEN")

    rec = db.insert(
        db.public_comments,
        {
            "methodology_change_id": change["id"],
            "commenter_reference": commenter_reference,
            "comment_text": comment_text,
            "stance": stance,
            "received_at": clock.iso_now(),
        },
        versioned=False,
    )

    change["comment_count"] = int(change["comment_count"] or 0) + 1
    db.touch(change)
    return response.object_response(serializers.public_comment(rec), 201)


@bp.get("/methodology-changes/<change_id>/comments")
@roles(*READ_ROLES)
def list_comments(change_id):
    limit, offset = V.pagination()
    stance = V.query_str("stance")

    change = lookup.methodology_change(change_id)
    records = db.ordered(
        [c for c in db.public_comments.values() if c["methodology_change_id"] == change["id"]]
    )
    if stance is not None:
        records = [c for c in records if c["stance"] == stance]

    page, total = V.paginate(records, limit, offset)
    return response.array_response(
        [serializers.public_comment(r) for r in page], limit, offset, total
    )


@bp.post("/methodology-changes/<change_id>/close-comment")
@roles(ROLE_PROGRAM_ADMIN)
def close_comment(change_id):
    change = lookup.methodology_change(change_id)
    _require_state(change, "COMMENT_OPEN")

    if clock.now() < change["_comment_period_end"]:
        raise ApiError(
            ERR_COMMENT_PERIOD_NOT_ENDED,
            "The public comment period has not ended yet.",
        )

    change["status"] = "COMMENT_CLOSED"
    db.touch(change)
    return response.object_response(serializers.methodology_change(change))


@bp.post("/methodology-changes/<change_id>/adopt")
@roles(ROLE_PROGRAM_ADMIN)
def adopt(change_id):
    change = lookup.methodology_change(change_id)
    _require_state(change, "COMMENT_CLOSED")

    if int(change["comment_count"] or 0) == 0:
        raise ApiError(
            ERR_NO_PUBLIC_COMMENTS,
            "A methodology change may not be adopted over silence.",
        )

    change["industry_notice_issued_at"] = clock.iso_now()

    affected = db.ordered(
        [
            r
            for r in db.market_reports.values()
            if r["category"] == change["affected_category"]
            and r["publication_state"] != "WITHDRAWN"
        ]
    )
    touched_window_ids = []
    for report in affected:
        report["weighting_variant"] = change["proposed_weighting_variant"]
        if report["aggregation_state"] == "COMPUTED":
            report["aggregation_state"] = "STALE"
            report["disclosure_state"] = "UNREVIEWED"
            report["suppression_reason"] = None
            if report["publication_state"] == "PUBLISHED":
                report["publication_state"] = "WITHDRAWN"
        db.touch(report)
        if report["reporting_window_id"] not in touched_window_ids:
            touched_window_ids.append(report["reporting_window_id"])

    for window_id in touched_window_ids:
        cascades.settle_window_publication(db.reporting_windows.get(window_id))

    change["restated_report_count"] = len(affected)
    change["status"] = "ADOPTED"
    db.touch(change)
    return response.object_response(serializers.methodology_change(change))


@bp.get("/methodology-changes/<change_id>")
@roles(*READ_ROLES)
def get_change(change_id):
    rec = lookup.methodology_change(change_id)
    return response.object_response(serializers.methodology_change(rec))


@bp.get("/methodology-changes")
@roles(*READ_ROLES)
def list_changes():
    limit, offset = V.pagination()
    status = V.query_str("status")
    affected_category = V.query_str("affected_category")

    records = db.ordered(db.methodology_changes.values())
    if status is not None:
        records = [r for r in records if r["status"] == status]
    if affected_category is not None:
        records = [r for r in records if r["affected_category"] == affected_category]

    page, total = V.paginate(records, limit, offset)
    return response.array_response(
        [serializers.methodology_change(r) for r in page], limit, offset, total
    )
