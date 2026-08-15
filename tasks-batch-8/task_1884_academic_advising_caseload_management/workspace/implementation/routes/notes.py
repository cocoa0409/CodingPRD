"""Advising note endpoints (student sub-resource)."""
from flask import Blueprint, request

import db
import errors
from errors import ApiError
from middleware import get_auth_context, require_role
from response import success_object, success_list
from services.common import (
    body, get_pagination_params, paginate, require_fields, require_enum, stamp_new,
)
from services.calculations import get_assigned_advisor_id

bp = Blueprint("notes", __name__)

ROLE_ACCESS = ("Advisor", "AdvisingDirector")


def note_public(n):
    return {
        "id": n["id"],
        "student_id": n["student_id"],
        "author_user_id": n["author_user_id"],
        "visibility": n["visibility"],
        "body": n["body"],
        "created_at": n["created_at"],
        "updated_at": n["updated_at"],
        "version": n["version"],
    }


@bp.route("/advising/students/<id>/notes", methods=["POST"])
def create_note(id):
    user_id, role = get_auth_context()
    data = body()
    require_fields(data, ["visibility", "body"])
    require_enum(data["visibility"], ("SHARED", "CONFIDENTIAL"), "visibility")
    require_role(role, ROLE_ACCESS)
    student = db.students.get(id)
    if not student:
        raise ApiError(errors.ERR_STUDENT_NOT_FOUND, f"Student {id} not found", 404)
    # state gate: INACTIVE students may not receive notes
    if student["care_status"] == "INACTIVE":
        raise ApiError(errors.ERR_STUDENT_INACTIVE,
                       "Notes may not be created for an INACTIVE student", 409)
    # confidentiality: CONFIDENTIAL only by assigned advisor or director
    if data["visibility"] == "CONFIDENTIAL" and role == "Advisor":
        assigned = get_assigned_advisor_id(id)
        if assigned != user_id:
            raise ApiError(errors.ERR_NOTE_CONFIDENTIALITY_RESTRICTED,
                           "CONFIDENTIAL notes may be authored only by the assigned advisor or director",
                           403)

    note = stamp_new({
        "student_id": id,
        "author_user_id": user_id,
        "visibility": data["visibility"],
        "body": data["body"],
    })
    db.notes[note["id"]] = note
    return success_object(note_public(note), 201)


@bp.route("/advising/students/<id>/notes", methods=["GET"])
def list_notes(id):
    user_id, role = get_auth_context()
    require_role(role, ("AdvisingDirector", "Advisor"))
    student = db.students.get(id)
    if not student:
        raise ApiError(errors.ERR_STUDENT_NOT_FOUND, f"Student {id} not found", 404)
    limit, offset = get_pagination_params()
    items = [n for n in db.notes.values() if n["student_id"] == id]
    visibility = request.args.get("visibility")
    if visibility is not None:
        if visibility not in ("SHARED", "CONFIDENTIAL"):
            raise ApiError(errors.ERR_VALIDATION, f"Invalid visibility filter: {visibility}", 400)
        items = [n for n in items if n["visibility"] == visibility]
    # server-side confidentiality filter: CONFIDENTIAL visible only to author and director
    visible = []
    for n in items:
        if n["visibility"] == "CONFIDENTIAL":
            if role == "AdvisingDirector" or n["author_user_id"] == user_id:
                visible.append(n)
        else:
            visible.append(n)
    page, total = paginate(visible, limit, offset)
    return success_list([note_public(n) for n in page], limit, offset, total)
