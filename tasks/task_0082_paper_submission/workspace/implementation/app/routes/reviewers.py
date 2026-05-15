"""Reviewer endpoints: add, fetch, list (filterable)."""
from __future__ import annotations

import re

from flask import Blueprint, request

from ..auth import require_auth
from ..errors import api_error
from ..response import success_envelope, list_envelope
from ..store import store
from ..utils import (
    get_json_body,
    optional_list,
    page_slice,
    parse_pagination,
    require_str,
)


reviewers_bp = Blueprint("reviewers", __name__)
_TAG_RE = re.compile(r"^[a-z0-9_]+$")


@reviewers_bp.route("/reviewers", methods=["POST"])
@require_auth(["PlatformAdmin"])
def create_reviewer():
    body = get_json_body()
    full_name = require_str(body, "full_name")
    email = require_str(body, "email")
    institution = require_str(body, "institution")
    expertise = optional_list(body, "expertise_tags")
    recent_collab = optional_list(body, "recent_collaborator_ids")

    if not expertise:
        raise api_error("ERR_VALIDATION", "expertise_tags must be non-empty")
    for tag in expertise:
        if not isinstance(tag, str) or not _TAG_RE.match(tag):
            raise api_error("ERR_VALIDATION", "Each expertise_tag must match ^[a-z0-9_]+$")

    with store.lock:
        for r in store.reviewers.values():
            if r["email"] == email:
                raise api_error("ERR_VALIDATION", "Reviewer email must be unique")
        row = {
            "full_name": full_name,
            "email": email,
            "institution": institution,
            "expertise_tags": list(expertise),
            "recent_collaborator_ids": list(recent_collab),
            "active_assignments": 0,
            "status": "ACTIVE",
        }
        store.stamp_create(row)
        store.reviewers[row["id"]] = row
        return success_envelope(row, status=201, response_type="object")


@reviewers_bp.route("/reviewers/<reviewer_id>", methods=["GET"])
@require_auth(["PlatformAdmin", "EditorInChief", "SectionEditor", "AssociateEditor", "Reviewer"])
def get_reviewer(reviewer_id: str):
    reviewer = store.reviewers.get(reviewer_id)
    if not reviewer:
        raise api_error("ERR_NOT_FOUND", "Reviewer not found")
    return success_envelope(reviewer, status=200, response_type="object")


@reviewers_bp.route("/reviewers", methods=["GET"])
@require_auth(["PlatformAdmin", "EditorInChief", "SectionEditor", "AssociateEditor"])
def list_reviewers():
    limit, offset = parse_pagination()
    expertise_tag = request.args.get("expertise_tag")
    status_filter = request.args.get("status")
    rows = sorted(store.reviewers.values(), key=lambda r: r["created_at"])
    if expertise_tag:
        rows = [r for r in rows if expertise_tag in r.get("expertise_tags", [])]
    if status_filter:
        rows = [r for r in rows if r.get("status") == status_filter]
    page, total = page_slice(rows, limit, offset)
    return list_envelope(page, total=total, limit=limit, offset=offset)
