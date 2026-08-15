"""DeficiencyComment and CommentResponse endpoints."""

from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_CYCLE_NOT_FOUND,
    ERR_COMMENT_NOT_FOUND,
    ERR_CYCLE_NOT_IN_REVIEW,
    ERR_NOT_ASSIGNED_REVIEWER,
    ERR_CODE_EDITION_MISMATCH,
    ERR_NOT_ENGAGEMENT_APPLICANT,
    ERR_COMMENT_NOT_AWAITING_RESPONSE,
    ERR_COMMENT_NOT_ADDRESSED,
    ERR_NO_ACTIVE_REVIEW_CYCLE,
    ERR_CRITICAL_COMMENT_NOT_WAIVERABLE,
    ERR_WAIVER_SEGREGATION_VIOLATION,
    ERR_INVALID_REQUEST,
)
from middleware import (
    require_roles, get_json_body, require_fields, reject_unknown_fields,
    require_enum, require_string, parse_pagination, paginate,
)
from response import success_object, success_list
from services.core import (
    require_assigned_reviewer, current_nonterminal_cycle,
    refresh_engagement_counts,
)

bp = Blueprint("comments", __name__)

READ_ROLES = ("PlatformAdmin", "ReviewCoordinator", "Reviewer", "ChiefReviewer", "Applicant")
IBC_EDITIONS = ("IBC_2018", "IBC_2021", "IBC_2024")
SEVERITIES = ("MINOR", "MAJOR", "CRITICAL")
CATEGORIES = ("LOAD_PATH", "LATERAL_SYSTEM", "CALCULATION", "DETAILING", "DEFERRED_COORDINATION")


def get_comment_or_404(cid):
    c = db.comments.get(cid)
    if c is None:
        raise ApiError(ERR_COMMENT_NOT_FOUND, 404, "No deficiency comment with the given id")
    return c


@bp.post("/plan-review/comments")
def create_comment():
    uid, _role = require_roles("Reviewer")
    body = get_json_body(required=True)
    reject_unknown_fields(body, {
        "raised_in_cycle_id", "code_section_ref", "reference_edition",
        "severity", "category", "comment_text",
    })
    require_fields(body, [
        "raised_in_cycle_id", "code_section_ref", "reference_edition",
        "severity", "category", "comment_text",
    ])
    raised_in_cycle_id = require_string(body, "raised_in_cycle_id")
    code_section_ref = require_string(body, "code_section_ref")
    reference_edition = require_enum(body, "reference_edition", IBC_EDITIONS)
    severity = require_enum(body, "severity", SEVERITIES)
    category = require_enum(body, "category", CATEGORIES)
    comment_text = require_string(body, "comment_text")

    # existence
    cycle = db.cycles.get(raised_in_cycle_id)
    if cycle is None:
        raise ApiError(ERR_CYCLE_NOT_FOUND, 404, "No review cycle with the given id")
    engagement = db.engagements[cycle["engagement_id"]]

    # ownership: caller must be the reviewer on this cycle's ACTIVE assignment
    require_assigned_reviewer(cycle, uid)

    # state
    if cycle["status"] != "IN_REVIEW":
        raise ApiError(ERR_CYCLE_NOT_IN_REVIEW, 409, "Cycle is not IN_REVIEW")

    # business: reference edition must equal the engagement's pinned edition
    if reference_edition != engagement["pinned_ibc_edition"]:
        raise ApiError(ERR_CODE_EDITION_MISMATCH, 422,
                       "reference_edition differs from engagement.pinned_ibc_edition")

    entity = db.stamp_new({
        "engagement_id": cycle["engagement_id"],
        "raised_in_cycle_id": cycle["id"],
        "raised_by_reviewer_id": uid,
        "code_section_ref": code_section_ref,
        "reference_edition": reference_edition,
        "severity": severity,
        "category": category,
        "comment_text": comment_text,
        "response_count": 0,
        "status": "OPEN",
    })
    db.comments[entity["id"]] = entity

    refresh_engagement_counts(engagement)
    db.touch(engagement)

    return success_object(db.serialize(entity), status=201)


@bp.get("/plan-review/comments")
def list_comments():
    require_roles(*READ_ROLES)
    limit, offset = parse_pagination()
    items = list(db.comments.values())
    engagement_id = request.args.get("engagement_id")
    raised_in_cycle_id = request.args.get("raised_in_cycle_id")
    raised_by_reviewer_id = request.args.get("raised_by_reviewer_id")
    status = request.args.get("status")
    if engagement_id is not None:
        items = [c for c in items if c["engagement_id"] == engagement_id]
    if raised_in_cycle_id is not None:
        items = [c for c in items if c["raised_in_cycle_id"] == raised_in_cycle_id]
    if raised_by_reviewer_id is not None:
        items = [c for c in items if c["raised_by_reviewer_id"] == raised_by_reviewer_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    items.sort(key=lambda c: (c["created_at"], c["id"]))
    page, total = paginate(items, limit, offset)
    return success_list([db.serialize(c) for c in page], limit, offset, total)


@bp.get("/plan-review/comments/<cid>")
def get_comment(cid):
    require_roles(*READ_ROLES)
    c = get_comment_or_404(cid)
    return success_object(db.serialize(c))


@bp.post("/plan-review/comments/<cid>/responses")
def create_response(cid):
    uid, _role = require_roles("Applicant")
    body = get_json_body(required=True)
    reject_unknown_fields(body, {"response_text"})
    require_fields(body, ["response_text"])
    response_text = require_string(body, "response_text")

    comment = get_comment_or_404(cid)
    engagement = db.engagements[comment["engagement_id"]]

    # ownership
    if uid != engagement["applicant_contact_id"]:
        raise ApiError(ERR_NOT_ENGAGEMENT_APPLICANT, 403,
                       "X-User-ID does not equal engagement.applicant_contact_id")

    # state: comment OPEN/REOPENED and current non-terminal cycle COMMENTS_ISSUED
    current = current_nonterminal_cycle(engagement["id"])
    if comment["status"] not in ("OPEN", "REOPENED") or current is None \
            or current["status"] != "COMMENTS_ISSUED":
        raise ApiError(ERR_COMMENT_NOT_AWAITING_RESPONSE, 409,
                       "Comment is not awaiting a response")

    now = db.clock_now()
    response = {
        "id": db.new_id(),
        "comment_id": comment["id"],
        "responder_contact_id": uid,
        "response_text": response_text,
        "created_at": now,
    }
    db.responses[response["id"]] = response

    comment["status"] = "ADDRESSED"
    comment["response_count"] += 1
    db.touch(comment)
    # unresolved count unchanged (ADDRESSED still unresolved) but refresh anyway
    refresh_engagement_counts(engagement)
    db.touch(engagement)

    return success_object(db.serialize(response), status=201)


@bp.get("/plan-review/comments/<cid>/responses")
def list_responses(cid):
    require_roles(*READ_ROLES)
    get_comment_or_404(cid)
    limit, offset = parse_pagination()
    items = [r for r in db.responses.values() if r["comment_id"] == cid]
    items.sort(key=lambda r: (r["created_at"], r["id"]))
    page, total = paginate(items, limit, offset)
    return success_list([db.serialize(r) for r in page], limit, offset, total)


def _verify_reopen_common(cid, uid):
    """Shared checks for verify/reopen: existence, ADDRESSED state (layer 7),
    current cycle IN_REVIEW (ERR_NO_ACTIVE_REVIEW_CYCLE), assigned-reviewer
    identity (ERR_NOT_ASSIGNED_REVIEWER)."""
    comment = get_comment_or_404(cid)
    engagement = db.engagements[comment["engagement_id"]]

    current = current_nonterminal_cycle(engagement["id"])
    if current is None or current["status"] != "IN_REVIEW":
        raise ApiError(ERR_NO_ACTIVE_REVIEW_CYCLE, 409,
                       "The engagement's current cycle is not IN_REVIEW")
    require_assigned_reviewer(current, uid)
    if comment["status"] != "ADDRESSED":
        raise ApiError(ERR_COMMENT_NOT_ADDRESSED, 409,
                       "Comment is not ADDRESSED")
    return comment, engagement


@bp.post("/plan-review/comments/<cid>/verify")
def verify_comment(cid):
    uid, _role = require_roles("Reviewer")
    get_json_body(required=False)
    comment, engagement = _verify_reopen_common(cid, uid)

    comment["status"] = "VERIFIED"
    db.touch(comment)
    refresh_engagement_counts(engagement)
    db.touch(engagement)
    return success_object(db.serialize(comment))


@bp.post("/plan-review/comments/<cid>/reopen")
def reopen_comment(cid):
    uid, _role = require_roles("Reviewer")
    body = get_json_body(required=True)
    reject_unknown_fields(body, {"reopen_note"})
    require_fields(body, ["reopen_note"])
    require_string(body, "reopen_note")

    comment, engagement = _verify_reopen_common(cid, uid)

    comment["status"] = "REOPENED"
    db.touch(comment)
    refresh_engagement_counts(engagement)
    db.touch(engagement)
    return success_object(db.serialize(comment))


@bp.post("/plan-review/comments/<cid>/waive")
def waive_comment(cid):
    uid, _role = require_roles("ChiefReviewer")
    body = get_json_body(required=True)
    reject_unknown_fields(body, {"justification"})
    require_fields(body, ["justification"])
    require_string(body, "justification")

    comment = get_comment_or_404(cid)
    engagement = db.engagements[comment["engagement_id"]]

    # state: only OPEN / ADDRESSED / REOPENED can be waived
    if comment["status"] not in ("OPEN", "ADDRESSED", "REOPENED"):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "Comment is not in a waivable state")

    # regulatory bars
    if comment["severity"] == "CRITICAL":
        raise ApiError(ERR_CRITICAL_COMMENT_NOT_WAIVERABLE, 422,
                       "CRITICAL comments cannot be waived")
    if uid == engagement["reviewer_of_record_id"]:
        raise ApiError(ERR_WAIVER_SEGREGATION_VIOLATION, 403,
                       "The reviewer of record may not waive findings on their own engagement")

    comment["status"] = "WAIVED"
    db.touch(comment)
    refresh_engagement_counts(engagement)
    db.touch(engagement)
    return success_object(db.serialize(comment))
