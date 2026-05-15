"""Editor endpoints: register, fetch, list (filterable)."""
from __future__ import annotations

import re

from flask import Blueprint, request

from ..auth import require_auth
from ..errors import api_error
from ..response import list_envelope, success_envelope
from ..store import store
from ..utils import (
    get_json_body,
    optional_list,
    page_slice,
    parse_pagination,
    require_str,
)


editors_bp = Blueprint("editors", __name__)
_TAG_RE = re.compile(r"^[a-z0-9_]+$")
_EDITOR_ROLES = {"EDITOR_IN_CHIEF", "SECTION_EDITOR", "ASSOCIATE_EDITOR"}


@editors_bp.route("/editors", methods=["POST"])
@require_auth(["PlatformAdmin"])
def create_editor():
    body = get_json_body()
    full_name = require_str(body, "full_name")
    email = require_str(body, "email")
    institution = require_str(body, "institution")
    role = require_str(body, "role")
    topic_tags = optional_list(body, "topic_tags")
    recent_collab = optional_list(body, "recent_collaborator_ids")

    if role not in _EDITOR_ROLES:
        raise api_error("ERR_VALIDATION", "role must be one of EDITOR_IN_CHIEF, SECTION_EDITOR, ASSOCIATE_EDITOR")
    if role in ("SECTION_EDITOR", "ASSOCIATE_EDITOR"):
        if not topic_tags:
            raise api_error("ERR_VALIDATION", "topic_tags required for SECTION_EDITOR and ASSOCIATE_EDITOR")
    for tag in topic_tags:
        if not isinstance(tag, str) or not _TAG_RE.match(tag):
            raise api_error("ERR_VALIDATION", "Each topic_tag must match ^[a-z0-9_]+$")

    with store.lock:
        for e in store.editors.values():
            if e["email"] == email:
                raise api_error("ERR_VALIDATION", "Editor email must be unique")
        row = {
            "full_name": full_name,
            "email": email,
            "institution": institution,
            "role": role,
            "topic_tags": list(topic_tags),
            "recent_collaborator_ids": list(recent_collab),
        }
        store.stamp_create(row)
        store.editors[row["id"]] = row
        return success_envelope(row, status=201, response_type="object")


@editors_bp.route("/editors/<editor_id>", methods=["GET"])
@require_auth(["PlatformAdmin", "EditorInChief", "SectionEditor", "AssociateEditor"])
def get_editor(editor_id: str):
    editor = store.editors.get(editor_id)
    if not editor:
        raise api_error("ERR_NOT_FOUND", "Editor not found")
    return success_envelope(editor, status=200, response_type="object")


@editors_bp.route("/editors", methods=["GET"])
@require_auth(["PlatformAdmin", "EditorInChief", "SectionEditor"])
def list_editors():
    limit, offset = parse_pagination()
    role_filter = request.args.get("role")
    topic_tag = request.args.get("topic_tag")
    rows = sorted(store.editors.values(), key=lambda r: r["created_at"])
    if role_filter:
        rows = [r for r in rows if r.get("role") == role_filter]
    if topic_tag:
        rows = [r for r in rows if topic_tag in r.get("topic_tags", [])]
    page, total = page_slice(rows, limit, offset)
    return list_envelope(page, total=total, limit=limit, offset=offset)
