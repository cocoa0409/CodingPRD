"""Training content: author / list / get / edit (OCC) / submit / approve /
reject / retire."""

from flask import Blueprint, g, request

from db import store, base_record, touch, audit
from errors import (ApiError, ERR_INVALID_REQUEST,
                    ERR_DUPLICATE_CONTENT_CODE, ERR_STALE_VERSION,
                    ERR_CONTENT_NOT_EDITABLE, ERR_CONTENT_NOT_PENDING_APPROVAL,
                    ERR_CONTENT_NOT_RETIRABLE, ERR_SOD_AUTHOR_CANNOT_APPROVE)
from middleware import require_roles, actor, json_body, require_fields
from response import success, paginate
from services import get_or_404, by_seq, retire_content
from util import (to_decimal, require_str, require_enum, require_int, view,
                  decimal_places)

bp = Blueprint("contents", __name__)

CE_CATEGORIES = ("REGULATORY_ELEMENT", "FIRM_ELEMENT", "PRODUCT", "STATE_INSURANCE")
DELIVERY_FORMATS = ("ELEARNING", "INSTRUCTOR_LED")

ANY = ("TrainingAdmin", "ComplianceOfficer", "RegisteredRep", "Auditor")


def _validate_credit_hours(value):
    hours = to_decimal(value, "credit_hours")
    if hours <= 0:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "Field 'credit_hours' must be greater than 0")
    if decimal_places(hours) > 2:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "Field 'credit_hours' supports at most 2 decimal places")
    return hours


def _validate_min_passing_score(value):
    score = require_int(value, "min_passing_score")
    if score < 0 or score > 100:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "Field 'min_passing_score' must be between 0 and 100")
    return score


@bp.post("/contents")
@require_roles("TrainingAdmin")
def create_content():
    body = json_body()
    require_fields(body, "code", "title", "ce_category", "delivery_format",
                   "credit_hours", "min_passing_score")
    code = require_str(body["code"], "code")
    title = require_str(body["title"], "title")
    ce_category = require_enum(body["ce_category"], "ce_category", CE_CATEGORIES)
    delivery_format = require_enum(body["delivery_format"], "delivery_format",
                                   DELIVERY_FORMATS)
    credit_hours = _validate_credit_hours(body["credit_hours"])
    min_passing_score = _validate_min_passing_score(body["min_passing_score"])
    for c in store.contents.values():
        if c["code"] == code:
            raise ApiError(ERR_DUPLICATE_CONTENT_CODE, 409,
                           "Content code '%s' already exists" % code)
    rec = base_record()
    rec.update({
        "code": code,
        "title": title,
        "ce_category": ce_category,
        "delivery_format": delivery_format,
        "credit_hours": credit_hours,
        "min_passing_score": min_passing_score,
        "content_status": "DRAFT",
        "author_user_id": g.actor_user_id,
        "approved_by_user_id": None,
        "rejection_reason": None,
    })
    store.contents[rec["id"]] = rec
    return success(view(rec), status=201)


@bp.get("/contents")
@require_roles(*ANY)
def list_contents():
    items = by_seq(store.contents.values())
    ce_category = request.args.get("ce_category")
    if ce_category is not None:
        items = [c for c in items if c["ce_category"] == ce_category]
    content_status = request.args.get("content_status")
    if content_status is not None:
        items = [c for c in items if c["content_status"] == content_status]
    items = sorted(items, key=lambda c: (c["created_at"], c["_seq"]))
    page, pagination = paginate(items)
    return success([view(c) for c in page], is_list=True, pagination=pagination)


@bp.get("/contents/<contentId>")
@require_roles(*ANY)
def get_content(contentId):
    rec = get_or_404(store.contents, contentId, "TrainingContent")
    return success(view(rec))


@bp.put("/contents/<contentId>")
@require_roles("TrainingAdmin")
def edit_content(contentId):
    rec = get_or_404(store.contents, contentId, "TrainingContent")
    body = json_body()
    # Shape: the OCC field is mandatory; editable fields validated if present.
    require_fields(body, "expected_content_version")
    expected = require_int(body["expected_content_version"],
                           "expected_content_version")
    new_title = None
    new_hours = None
    new_score = None
    if "title" in body and body["title"] is not None:
        new_title = require_str(body["title"], "title")
    if "credit_hours" in body and body["credit_hours"] is not None:
        new_hours = _validate_credit_hours(body["credit_hours"])
    if "min_passing_score" in body and body["min_passing_score"] is not None:
        new_score = _validate_min_passing_score(body["min_passing_score"])
    # OCC before any business-state check.
    if expected != rec["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected_content_version does not match current version")
    if rec["content_status"] not in ("DRAFT", "REJECTED"):
        raise ApiError(ERR_CONTENT_NOT_EDITABLE, 409,
                       "Content in status %s cannot be edited"
                       % rec["content_status"])
    if new_title is not None:
        rec["title"] = new_title
    if new_hours is not None:
        rec["credit_hours"] = new_hours
    if new_score is not None:
        rec["min_passing_score"] = new_score
    if rec["content_status"] == "REJECTED":
        # Rework loop: REJECTED returns to DRAFT, clearing rejection markers.
        rec["content_status"] = "DRAFT"
        rec["rejection_reason"] = None
        rec["approved_by_user_id"] = None
    touch(rec)
    return success(view(rec))


@bp.post("/contents/<contentId>/submit")
@require_roles("TrainingAdmin")
def submit_content(contentId):
    rec = get_or_404(store.contents, contentId, "TrainingContent")
    if rec["content_status"] != "DRAFT":
        raise ApiError(ERR_CONTENT_NOT_EDITABLE, 409,
                       "Only DRAFT content can be submitted for approval")
    rec["content_status"] = "PENDING_APPROVAL"
    touch(rec)
    return success(view(rec))


@bp.post("/contents/<contentId>/approve")
@require_roles("ComplianceOfficer")
def approve_content(contentId):
    rec = get_or_404(store.contents, contentId, "TrainingContent")
    if rec["content_status"] != "PENDING_APPROVAL":
        raise ApiError(ERR_CONTENT_NOT_PENDING_APPROVAL, 409,
                       "approve requires content_status == PENDING_APPROVAL")
    if g.actor_user_id == rec["author_user_id"]:
        raise ApiError(ERR_SOD_AUTHOR_CANNOT_APPROVE, 403,
                       "The content author cannot approve their own content")
    rec["content_status"] = "APPROVED"
    rec["approved_by_user_id"] = g.actor_user_id
    touch(rec)
    a = actor()
    audit("CONTENT_APPROVED", "TrainingContent", rec["id"], a[0], a[1],
          "content_status: PENDING_APPROVAL -> APPROVED")
    return success(view(rec))


@bp.post("/contents/<contentId>/reject")
@require_roles("ComplianceOfficer")
def reject_content(contentId):
    rec = get_or_404(store.contents, contentId, "TrainingContent")
    body = json_body()
    require_fields(body, "reason")
    reason = require_str(body["reason"], "reason")
    if rec["content_status"] != "PENDING_APPROVAL":
        raise ApiError(ERR_CONTENT_NOT_PENDING_APPROVAL, 409,
                       "reject requires content_status == PENDING_APPROVAL")
    rec["content_status"] = "REJECTED"
    rec["rejection_reason"] = reason
    touch(rec)
    a = actor()
    audit("CONTENT_REJECTED", "TrainingContent", rec["id"], a[0], a[1],
          "content_status: PENDING_APPROVAL -> REJECTED; reason: %s" % reason)
    return success(view(rec))


@bp.post("/contents/<contentId>/retire")
@require_roles("ComplianceOfficer")
def retire_content_route(contentId):
    rec = get_or_404(store.contents, contentId, "TrainingContent")
    if rec["content_status"] != "APPROVED":
        raise ApiError(ERR_CONTENT_NOT_RETIRABLE, 409,
                       "retire requires content_status == APPROVED")
    retire_content(rec, actor())
    return success(view(rec))
