"""Submission routes: create, get, list, approve, reject, resubmit."""
from flask import Blueprint, request

from db import db, stamp_create, touch, sorted_by_created
from middleware import authenticate, authorize
from validators import (
    get_json_body, require, as_str, as_enum, parse_pagination,
)
from lookups import get_submission_path, get_ref
from response import success_object, success_array
import serializers as ser
from services.derive import recompute_page_counts, recompute_yearbook
from errors import (
    ApiError, ERR_INVALID_STATE, ERR_PAGE_LOCKED_FOR_SUBMISSIONS,
)

bp = Blueprint("submissions", __name__)

KINDS = {"PHOTO", "QUOTE"}
PAGE_OPEN_STATES = ("DRAFT", "IN_REVIEW", "CHANGES_REQUESTED")


def _page_open_guard(page):
    if page["status"] not in PAGE_OPEN_STATES:
        raise ApiError(ERR_PAGE_LOCKED_FOR_SUBMISSIONS, 409,
                       "parent page is locked for submissions")


@bp.route("/yearbooks/submissions", methods=["POST"])
def create_submission():
    _, role = authenticate()
    authorize(role, {"Contributor"})
    body = get_json_body()

    ladder_page_id = as_str(require(body, "ladder_page_id"), "ladder_page_id")
    page = get_ref(db.ladder_pages, ladder_page_id)
    kind = as_enum(require(body, "kind"), "kind", KINDS)
    contributor_id = as_str(require(body, "contributor_id"), "contributor_id")
    asset_ref = as_str(require(body, "asset_ref"), "asset_ref")

    sub = {
        "ladder_page_id": ladder_page_id,
        "kind": kind,
        "contributor_id": contributor_id,
        "asset_ref": asset_ref,
        "review_note": "",
        "status": "PENDING",
    }
    stamp_create(sub)
    db.submissions[sub["id"]] = sub
    return success_object(ser.submission(sub), 201)


@bp.route("/yearbooks/submissions/<submission_id>", methods=["GET"])
def get_submission(submission_id):
    _, role = authenticate()
    authorize(role, {"Adviser", "Staff", "Contributor"})
    sub = get_submission_path(submission_id)
    return success_object(ser.submission(sub), 200)


@bp.route("/yearbooks/submissions", methods=["GET"])
def list_submissions():
    _, role = authenticate()
    authorize(role, {"Adviser", "Staff", "Contributor"})
    limit, offset = parse_pagination()
    ladder_page_id = request.args.get("ladder_page_id")
    records = list(db.submissions.values())
    if ladder_page_id is not None:
        records = [r for r in records if r["ladder_page_id"] == ladder_page_id]
    records = sorted_by_created(records)
    total = len(records)
    page = records[offset:offset + limit]
    return success_array([ser.submission(r) for r in page], limit, offset, total, 200)


def _recompute_after_count_change(sub):
    page = db.ladder_pages.get(sub["ladder_page_id"])
    if page is not None:
        recompute_page_counts(page)
        yb = db.yearbooks.get(page["yearbook_id"])
        if yb is not None:
            recompute_yearbook(yb)


@bp.route("/yearbooks/submissions/<submission_id>/approve", methods=["POST"])
def approve_submission(submission_id):
    _, role = authenticate()
    authorize(role, {"Staff"})
    sub = get_submission_path(submission_id)
    body = get_json_body()

    # transition PENDING -> APPROVED defined only from PENDING
    if sub["status"] != "PENDING":
        raise ApiError(ERR_INVALID_STATE, 409, "submission is not pending")
    page = db.ladder_pages.get(sub["ladder_page_id"])
    _page_open_guard(page)

    if "review_note" in body and body["review_note"] is not None:
        sub["review_note"] = as_str(body["review_note"], "review_note")
    sub["status"] = "APPROVED"
    touch(sub)
    _recompute_after_count_change(sub)
    return success_object(ser.submission(sub), 200)


@bp.route("/yearbooks/submissions/<submission_id>/reject", methods=["POST"])
def reject_submission(submission_id):
    _, role = authenticate()
    authorize(role, {"Staff"})
    sub = get_submission_path(submission_id)
    body = get_json_body()

    # reject defined from PENDING and APPROVED
    if sub["status"] not in ("PENDING", "APPROVED"):
        raise ApiError(ERR_INVALID_STATE, 409, "submission cannot be rejected")
    # un-approving (APPROVED -> REJECTED) requires the parent page still open
    if sub["status"] == "APPROVED":
        page = db.ladder_pages.get(sub["ladder_page_id"])
        _page_open_guard(page)

    was_approved = sub["status"] == "APPROVED"
    if "review_note" in body and body["review_note"] is not None:
        sub["review_note"] = as_str(body["review_note"], "review_note")
    sub["status"] = "REJECTED"
    touch(sub)
    if was_approved:
        _recompute_after_count_change(sub)
    return success_object(ser.submission(sub), 200)


@bp.route("/yearbooks/submissions/<submission_id>/resubmit", methods=["POST"])
def resubmit_submission(submission_id):
    _, role = authenticate()
    authorize(role, {"Contributor"})
    sub = get_submission_path(submission_id)
    body = get_json_body()

    if sub["status"] != "REJECTED":
        raise ApiError(ERR_INVALID_STATE, 409, "submission is not rejected")
    page = db.ladder_pages.get(sub["ladder_page_id"])
    _page_open_guard(page)

    if "asset_ref" in body and body["asset_ref"] is not None:
        sub["asset_ref"] = as_str(body["asset_ref"], "asset_ref")
    sub["status"] = "PENDING"
    touch(sub)
    return success_object(ser.submission(sub), 200)
