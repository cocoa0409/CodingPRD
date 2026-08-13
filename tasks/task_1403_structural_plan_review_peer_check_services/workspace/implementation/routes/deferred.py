"""DeferredSubmittal endpoints."""

from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_ENGAGEMENT_NOT_FOUND,
    ERR_DEFERRED_SUBMITTAL_NOT_FOUND,
    ERR_NOT_ENGAGEMENT_APPLICANT,
    ERR_ENGAGEMENT_NOT_ACTIVE,
    ERR_DEFERRED_NOT_PERMITTED,
    ERR_NOT_RESPONSIBLE_CHARGE,
    ERR_INVALID_STATE_TRANSITION,
)
from middleware import (
    require_roles, get_json_body, require_fields, reject_unknown_fields,
    require_enum, require_string, parse_pagination, paginate,
)
from response import success_object, success_list
from services.core import refresh_engagement_counts

bp = Blueprint("deferred", __name__)

READ_ROLES = ("PlatformAdmin", "ReviewCoordinator", "Reviewer", "ChiefReviewer", "Applicant")
ITEM_TYPES = ("TRUSS", "ANCHOR", "STEEL_CONNECTION", "CURTAIN_WALL", "OTHER_DELEGATED")


def get_deferred_or_404(did):
    d = db.deferred_submittals.get(did)
    if d is None:
        raise ApiError(ERR_DEFERRED_SUBMITTAL_NOT_FOUND, 404,
                       "No deferred submittal with the given id")
    return d


@bp.post("/plan-review/deferred-submittals")
def create_deferred():
    uid, _role = require_roles("Applicant")
    body = get_json_body(required=True)
    reject_unknown_fields(body, {"engagement_id", "item_type", "description"})
    require_fields(body, ["engagement_id", "item_type", "description"])
    engagement_id = require_string(body, "engagement_id")
    item_type = require_enum(body, "item_type", ITEM_TYPES)
    description = require_string(body, "description")

    engagement = db.engagements.get(engagement_id)
    if engagement is None:
        raise ApiError(ERR_ENGAGEMENT_NOT_FOUND, 404, "No engagement with the given id")

    # ownership
    if uid != engagement["applicant_contact_id"]:
        raise ApiError(ERR_NOT_ENGAGEMENT_APPLICANT, 403,
                       "X-User-ID does not equal engagement.applicant_contact_id")

    # state
    if engagement["status"] not in ("IN_PROGRESS", "APPROVED"):
        raise ApiError(ERR_ENGAGEMENT_NOT_ACTIVE, 409,
                       "Engagement must be IN_PROGRESS or APPROVED to register deferred submittals")

    # business
    if not engagement["pinned_allows_deferred_submittals"]:
        raise ApiError(ERR_DEFERRED_NOT_PERMITTED, 422,
                       "Deferred submittals are not permitted in this jurisdiction")

    entity = db.stamp_new({
        "engagement_id": engagement["id"],
        "item_type": item_type,
        "description": description,
        "documents_ref": None,
        "rejection_reason": None,
        "status": "REGISTERED",
    })
    db.deferred_submittals[entity["id"]] = entity

    refresh_engagement_counts(engagement)
    db.touch(engagement)

    return success_object(db.serialize(entity), status=201)


@bp.get("/plan-review/deferred-submittals")
def list_deferred():
    require_roles(*READ_ROLES)
    limit, offset = parse_pagination()
    items = list(db.deferred_submittals.values())
    engagement_id = request.args.get("engagement_id")
    status = request.args.get("status")
    if engagement_id is not None:
        items = [d for d in items if d["engagement_id"] == engagement_id]
    if status is not None:
        items = [d for d in items if d["status"] == status]
    items.sort(key=lambda d: (d["created_at"], d["id"]))
    page, total = paginate(items, limit, offset)
    return success_list([db.serialize(d) for d in page], limit, offset, total)


@bp.get("/plan-review/deferred-submittals/<did>")
def get_deferred(did):
    require_roles(*READ_ROLES)
    d = get_deferred_or_404(did)
    return success_object(db.serialize(d))


@bp.post("/plan-review/deferred-submittals/<did>/submit")
def submit_deferred(did):
    uid, _role = require_roles("Applicant")
    body = get_json_body(required=True)
    reject_unknown_fields(body, {"documents_ref"})
    require_fields(body, ["documents_ref"])
    documents_ref = require_string(body, "documents_ref")

    d = get_deferred_or_404(did)
    engagement = db.engagements[d["engagement_id"]]

    if uid != engagement["applicant_contact_id"]:
        raise ApiError(ERR_NOT_ENGAGEMENT_APPLICANT, 403,
                       "X-User-ID does not equal engagement.applicant_contact_id")

    if d["status"] not in ("REGISTERED", "REJECTED"):
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "Deferred submittal is not in REGISTERED or REJECTED")

    d["documents_ref"] = documents_ref
    if d["status"] == "REJECTED":
        d["rejection_reason"] = None
    d["status"] = "SUBMITTED"
    db.touch(d)
    refresh_engagement_counts(engagement)
    db.touch(engagement)
    return success_object(db.serialize(d))


@bp.post("/plan-review/deferred-submittals/<did>/approve")
def approve_deferred(did):
    uid, _role = require_roles("Reviewer")
    get_json_body(required=False)
    d = get_deferred_or_404(did)
    engagement = db.engagements[d["engagement_id"]]

    if uid != engagement["reviewer_of_record_id"]:
        raise ApiError(ERR_NOT_RESPONSIBLE_CHARGE, 403,
                       "X-User-ID does not equal engagement.reviewer_of_record_id")

    if d["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "Deferred submittal is not SUBMITTED")

    d["status"] = "APPROVED"
    db.touch(d)
    refresh_engagement_counts(engagement)
    db.touch(engagement)
    return success_object(db.serialize(d))


@bp.post("/plan-review/deferred-submittals/<did>/reject")
def reject_deferred(did):
    uid, _role = require_roles("Reviewer")
    body = get_json_body(required=True)
    reject_unknown_fields(body, {"rejection_reason"})
    require_fields(body, ["rejection_reason"])
    rejection_reason = require_string(body, "rejection_reason")

    d = get_deferred_or_404(did)
    engagement = db.engagements[d["engagement_id"]]

    if uid != engagement["reviewer_of_record_id"]:
        raise ApiError(ERR_NOT_RESPONSIBLE_CHARGE, 403,
                       "X-User-ID does not equal engagement.reviewer_of_record_id")

    if d["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "Deferred submittal is not SUBMITTED")

    d["status"] = "REJECTED"
    d["rejection_reason"] = rejection_reason
    db.touch(d)
    refresh_engagement_counts(engagement)
    db.touch(engagement)
    return success_object(db.serialize(d))
