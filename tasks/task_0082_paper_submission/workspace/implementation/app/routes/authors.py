"""Author endpoints: register, fetch, list."""
from __future__ import annotations

from flask import Blueprint

from ..auth import require_auth
from ..errors import api_error
from ..response import success_envelope, list_envelope
from ..store import store
from ..utils import (
    get_json_body,
    optional_list,
    optional_str,
    parse_pagination,
    require_str,
    validate_orcid,
    page_slice,
)


authors_bp = Blueprint("authors", __name__)


@authors_bp.route("/authors", methods=["POST"])
@require_auth(["PlatformAdmin", "Author"])
def create_author():
    body = get_json_body()
    full_name = require_str(body, "full_name")
    email = require_str(body, "email")
    institution = require_str(body, "institution")
    orcid_id = optional_str(body, "orcid_id")
    recent_collab = optional_list(body, "recent_collaborator_ids")

    if orcid_id is not None and orcid_id != "":
        validate_orcid(orcid_id)
    else:
        orcid_id = None

    with store.lock:
        # email uniqueness
        for a in store.authors.values():
            if a["email"] == email:
                raise api_error("ERR_VALIDATION", "Author email must be unique")
        # orcid_id uniqueness (only when supplied)
        if orcid_id is not None:
            for a in store.authors.values():
                if a.get("orcid_id") == orcid_id:
                    raise api_error("ERR_VALIDATION", "orcid_id must be unique among authors")

        # validate recent_collaborator_ids exist as authors? Spec doesn't enforce
        # foreign-key existence here at registration time, so we just accept them.
        if not all(isinstance(x, str) for x in recent_collab):
            raise api_error("ERR_VALIDATION", "recent_collaborator_ids must be strings")

        row = {
            "full_name": full_name,
            "email": email,
            "orcid_id": orcid_id,
            "orcid_verified": False,
            "institution": institution,
            "recent_collaborator_ids": list(recent_collab),
        }
        store.stamp_create(row)
        store.authors[row["id"]] = row
        return success_envelope(row, status=201, response_type="object")


@authors_bp.route("/authors/<author_id>", methods=["GET"])
@require_auth(["PlatformAdmin", "Author", "EditorInChief", "SectionEditor", "AssociateEditor"])
def get_author(author_id: str):
    author = store.authors.get(author_id)
    if not author:
        raise api_error("ERR_NOT_FOUND", "Author not found")
    return success_envelope(author, status=200, response_type="object")


@authors_bp.route("/authors", methods=["GET"])
@require_auth(["PlatformAdmin", "EditorInChief", "SectionEditor", "AssociateEditor"])
def list_authors():
    limit, offset = parse_pagination()
    rows = sorted(store.authors.values(), key=lambda r: r["created_at"])
    page, total = page_slice(rows, limit, offset)
    return list_envelope(page, total=total, limit=limit, offset=offset)
