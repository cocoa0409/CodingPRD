"""ClinicalNote endpoints — confidentiality-walled."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
    ERR_CONFIDENTIALITY_VIOLATION,
    ERR_UNAUTHORIZED,
)
from middleware import require_roles
from response import success_object, success_list
from services.serializers import serialize, serialize_list
from util import (
    apply_filters,
    get_json_body,
    paginate,
    parse_pagination,
    require_string,
    sort_by_created_at,
)

bp = Blueprint("notes", __name__)


@bp.route("/ucc/clinical-notes", methods=["POST"])
@require_roles("Counselor")
def create_note(_user_id: str, _role: str):
    body = get_json_body()
    session_id = require_string(body, "session_id")
    author_id = require_string(body, "author_id")
    note_body = require_string(body, "body")

    if db.sessions.get(session_id) is None:
        raise_err(ERR_NOT_FOUND, "session_id does not resolve")
    if db.counselors.get(author_id) is None:
        raise_err(ERR_NOT_FOUND, "author_id does not resolve")

    note = {
        "session_id": session_id,
        "author_id": author_id,
        "body": note_body,
    }
    db.stamp_new_light(note)
    db.clinical_notes[note["id"]] = note
    return success_object(serialize(note), 201)


@bp.route("/ucc/clinical-notes/<note_id>", methods=["GET"])
@require_roles("Counselor", "ClinicalDirector")
def get_note(note_id: str, _user_id: str, _role: str):
    note = db.clinical_notes.get(note_id)
    if note is None:
        raise_err(ERR_NOT_FOUND, "ClinicalNote id does not exist")
    # Confidentiality wall: only author or ClinicalDirector.
    if _role == "Counselor" and note.get("author_id") != _user_id:
        raise_err(ERR_CONFIDENTIALITY_VIOLATION, "ClinicalNote readable only by author or ClinicalDirector")
    return success_object(serialize(note))


@bp.route("/ucc/clinical-notes", methods=["GET"])
@require_roles("Counselor", "ClinicalDirector")
def list_notes(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = sort_by_created_at(list(db.clinical_notes.values()))
    items = apply_filters(items, ["session_id", "author_id"])
    page, total = paginate(items, limit, offset)
    return success_list(serialize_list(page), limit, offset, total)
