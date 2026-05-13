"""Submission routes: create, list, get, patch, withdraw."""
import re

from flask import Blueprint, request

from clock import format_iso, get_now, parse_iso
from common import check_version, get_json_body, paginate, stamp_new, stamp_update
from db import db
from errors import api_error
from middleware import require_roles
from response import success
from services.anonymity import submission_view_for


bp = Blueprint("submissions", __name__)


HTTPS_RE = re.compile(r"^https://[^\s]+$")


def _compute_modify_window(project, prelim):
    sub_dl = parse_iso(project["submission_deadline"])
    prelim_start = parse_iso(prelim["starts_at"]) if prelim else None
    if prelim_start and prelim_start < sub_dl:
        return format_iso(prelim_start)
    return format_iso(sub_dl)


def _designer_active_count(project_id, designer_id):
    return sum(
        1 for s in db.submissions.values()
        if s.get("project_id") == project_id
        and s.get("designer_id") == designer_id
        and s.get("status") != "WITHDRAWN"
    )


@bp.route("/projects/<project_id>/submissions", methods=["POST"])
def create_submission(project_id):
    user_id, _ = require_roles({"Designer"})
    project = db.projects.get(project_id)
    if not project:
        raise api_error("ERR_NOT_FOUND", "project not found")
    body = get_json_body()
    designer_id = body.get("designer_id")
    if designer_id not in db.designers:
        raise api_error("ERR_FK_NOT_FOUND", "designer_id not found")
    if user_id != designer_id:
        raise api_error("ERR_FORBIDDEN", "Designers can only create submissions for themselves")
    if project.get("status") != "ON_SHELF":
        raise api_error("ERR_INVALID_STATE", "submissions are only accepted while project is ON_SHELF")

    title = body.get("title")
    asset_urls = body.get("asset_urls")
    declared = body.get("original_work_declared")

    if not isinstance(title, str) or not (1 <= len(title) <= 120):
        raise api_error("ERR_VALIDATION", "title length 1..120")
    if not isinstance(asset_urls, list) or not (1 <= len(asset_urls) <= 10):
        raise api_error("ERR_VALIDATION", "asset_urls must be 1..10 items")
    for u in asset_urls:
        if not (isinstance(u, str) and HTTPS_RE.match(u)):
            raise api_error("ERR_VALIDATION", "each asset_url must be HTTPS")
    if declared is not True:
        raise api_error("ERR_ORIGINAL_DECLARATION_REQUIRED", "original_work_declared must be true")

    # Per-designer cap
    if _designer_active_count(project_id, designer_id) >= project["max_submissions_per_designer"]:
        raise api_error("ERR_SUBMISSION_LIMIT_REACHED",
                        "designer has reached max_submissions_per_designer on this project")

    prelim = None
    for s in db.review_stages.values():
        if s.get("project_id") == project_id and s.get("stage_kind") == "PRELIMINARY":
            prelim = s
            break

    sub = stamp_new({
        "project_id": project_id,
        "designer_id": designer_id,
        "title": title,
        "asset_urls": list(asset_urls),
        "original_work_declared": True,
        "status": "DRAFT",
        "modify_window_closes_at": _compute_modify_window(project, prelim),
        "originality_score": None,
        "originality_variant": None,
        "aggregate_score_by_stage": {},
        "prize_tier_id": None,
    })
    db.submissions[sub["id"]] = sub
    return success(sub, status=201)


@bp.route("/projects/<project_id>/submissions", methods=["GET"])
def list_submissions(project_id):
    user_id, role = require_roles({"PlatformOps", "Client", "Designer", "Reviewer"})
    if project_id not in db.projects:
        raise api_error("ERR_NOT_FOUND", "project not found")
    items = [s for s in db.submissions.values() if s.get("project_id") == project_id]
    status = request.args.get("status")
    designer_id = request.args.get("designer_id")
    if status:
        items = [s for s in items if s.get("status") == status]
    if designer_id:
        items = [s for s in items if s.get("designer_id") == designer_id]
    # Apply anonymity view
    items = [submission_view_for(s, role) for s in items]
    page, meta = paginate(items)
    return success(page, response_type="array", pagination=meta)


@bp.route("/submissions/<submission_id>", methods=["GET"])
def get_submission(submission_id):
    user_id, role = require_roles({"PlatformOps", "Client", "Designer", "Reviewer"})
    sub = db.submissions.get(submission_id)
    if not sub:
        raise api_error("ERR_NOT_FOUND", "submission not found")
    return success(submission_view_for(sub, role))


@bp.route("/submissions/<submission_id>", methods=["PATCH"])
def patch_submission(submission_id):
    user_id, _ = require_roles({"Designer"})
    sub = db.submissions.get(submission_id)
    if not sub:
        raise api_error("ERR_NOT_FOUND", "submission not found")
    if sub.get("designer_id") != user_id:
        raise api_error("ERR_FORBIDDEN", "Designers can only modify their own submissions")
    if sub.get("status") != "DRAFT":
        raise api_error("ERR_INVALID_STATE", "submission can only be modified while DRAFT")
    body = get_json_body()
    check_version(sub, body)
    mw = sub.get("modify_window_closes_at")
    if mw and get_now() >= parse_iso(mw):
        raise api_error("ERR_MODIFY_WINDOW_CLOSED", "modify window has closed")
    changed = False
    if "title" in body:
        t = body["title"]
        if not isinstance(t, str) or not (1 <= len(t) <= 120):
            raise api_error("ERR_VALIDATION", "title length 1..120")
        sub["title"] = t
        changed = True
    if "asset_urls" in body:
        arr = body["asset_urls"]
        if not isinstance(arr, list) or not (1 <= len(arr) <= 10):
            raise api_error("ERR_VALIDATION", "asset_urls must be 1..10 items")
        for u in arr:
            if not (isinstance(u, str) and HTTPS_RE.match(u)):
                raise api_error("ERR_VALIDATION", "each asset_url must be HTTPS")
        sub["asset_urls"] = list(arr)
        changed = True
    if changed:
        stamp_update(sub)
    return success(sub)


@bp.route("/submissions/<submission_id>", methods=["DELETE"])
def withdraw_submission(submission_id):
    user_id, _ = require_roles({"Designer"})
    sub = db.submissions.get(submission_id)
    if not sub:
        raise api_error("ERR_NOT_FOUND", "submission not found")
    if sub.get("designer_id") != user_id:
        raise api_error("ERR_FORBIDDEN", "Designers can only withdraw their own submissions")
    body = get_json_body()
    check_version(sub, body)
    if sub.get("status") != "DRAFT":
        raise api_error("ERR_INVALID_STATE", "only DRAFT submissions can be withdrawn")
    mw = sub.get("modify_window_closes_at")
    if mw and get_now() >= parse_iso(mw):
        raise api_error("ERR_MODIFY_WINDOW_CLOSED", "modify window has closed")
    sub["status"] = "WITHDRAWN"
    stamp_update(sub)
    return success(sub)
