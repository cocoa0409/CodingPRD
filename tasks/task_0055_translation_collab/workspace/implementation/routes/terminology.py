from flask import Blueprint, request

from db import store
from errors import err
from middleware import require_roles
from response import success, list_response, no_content
from services.common import (parse_pagination, serialize_terminology, sort_by_created_at,
                              stamp_create, touch, check_version)
from services.terminology import (detect_conflict_on_create, has_existing_approved)
from services.validation import (TERM_SCOPES, require_enum, require_field,
                                  require_string, validate_lang)

bp = Blueprint("terminology", __name__)


@bp.post("/terminology")
@require_roles("ProjectManager", "Translator")
def create_terminology():
    body = request.get_json(silent=True) or {}
    scope_type = require_enum(body, "scope_type", TERM_SCOPES)
    scope_id = require_string(body, "scope_id")
    # Validate scope exists
    if scope_type == "PROJECT" and scope_id not in store.projects:
        raise err("ERR_NOT_FOUND", "project scope not found")
    if scope_type == "CLIENT" and scope_id not in store.clients:
        raise err("ERR_NOT_FOUND", "client scope not found")
    source_lang = validate_lang(require_field(body, "source_lang"))
    target_lang = validate_lang(require_field(body, "target_lang"))
    source_term = require_string(body, "source_term", min_len=1, max_len=200)
    target_term = require_string(body, "target_term", min_len=1, max_len=200)

    t = {
        "scope_type": scope_type,
        "scope_id": scope_id,
        "source_lang": source_lang,
        "target_lang": target_lang,
        "source_term": source_term,
        "target_term": target_term,
        "state": "PROPOSED",
    }
    stamp_create(t)
    store.terminology[t["id"]] = t
    detect_conflict_on_create(t)
    return success(serialize_terminology(t), status=201)


@bp.post("/terminology/<id>/approve")
@require_roles("ProjectManager")
def approve_terminology(id):
    t = store.terminology.get(id)
    if not t:
        raise err("ERR_NOT_FOUND", "terminology not found")
    if t["state"] != "PROPOSED":
        raise err("ERR_INVALID_STATE", "only PROPOSED can be approved.")
    if has_existing_approved(t):
        raise err("ERR_INVALID_STATE", "existing APPROVED entry for same tuple.")
    t["state"] = "APPROVED"
    touch(t)
    return success(serialize_terminology(t))


@bp.post("/terminology/<id>/resolve")
@require_roles("ProjectManager")
def resolve_terminology(id):
    t = store.terminology.get(id)
    if not t:
        raise err("ERR_NOT_FOUND", "terminology not found")
    if t["state"] != "CONFLICT":
        raise err("ERR_INVALID_STATE", "only CONFLICT can be resolved.")
    body = request.get_json(silent=True) or {}
    loser_id = body.get("loser_id")
    if not isinstance(loser_id, str) or not loser_id:
        raise err("ERR_TERMINOLOGY_RESOLVE_REQUIRES_LOSER", "loser_id required.")
    loser = store.terminology.get(loser_id)
    if loser is None or loser["state"] != "CONFLICT":
        raise err("ERR_TERMINOLOGY_RESOLVE_REQUIRES_LOSER", "loser_id must refer to a CONFLICT entry.")
    # Ensure loser is in same scope & key (it must be the conflict counterpart)
    if not (
        loser["scope_type"] == t["scope_type"]
        and loser["scope_id"] == t["scope_id"]
        and loser["source_lang"] == t["source_lang"]
        and loser["target_lang"] == t["target_lang"]
        and loser["source_term"] == t["source_term"]
    ):
        raise err("ERR_TERMINOLOGY_RESOLVE_REQUIRES_LOSER", "loser_id is not the conflict counterpart.")

    loser["state"] = "ARCHIVED"
    touch(loser)
    t["state"] = "APPROVED"
    touch(t)
    return success(serialize_terminology(t))


@bp.delete("/terminology/<id>")
@require_roles("ProjectManager")
def archive_terminology(id):
    t = store.terminology.get(id)
    if not t:
        raise err("ERR_NOT_FOUND", "terminology not found")
    if t["state"] == "ARCHIVED":
        raise err("ERR_INVALID_STATE", "already archived.")
    if t["state"] == "APPROVED":
        # Parent project must not be PUBLISHED
        if t["scope_type"] == "PROJECT":
            project = store.projects.get(t["scope_id"])
            if project and project["state"] == "PUBLISHED":
                raise err("ERR_INVALID_STATE", "cannot archive APPROVED terminology in PUBLISHED project.")
    t["state"] = "ARCHIVED"
    touch(t)
    return no_content(status=204)


@bp.get("/terminology")
@require_roles("ProjectManager", "Translator")
def list_terminology():
    limit, offset = parse_pagination(request.args)
    scope_type = request.args.get("scope_type")
    scope_id = request.args.get("scope_id")
    state = request.args.get("state")
    items = list(store.terminology.values())
    if scope_type:
        items = [t for t in items if t["scope_type"] == scope_type]
    if scope_id:
        items = [t for t in items if t["scope_id"] == scope_id]
    if state:
        items = [t for t in items if t["state"] == state]
    items = sort_by_created_at(items)
    total = len(items)
    sliced = items[offset:offset + limit]
    return list_response([serialize_terminology(t) for t in sliced], total, limit, offset)
