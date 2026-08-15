"""Diploma routes: list, get, issue, revoke."""

from flask import Blueprint, request

import db
from errors import ApiError
from middleware import get_auth, parse_pagination, require_owner, require_roles
from response import success_list, success_object
from util import json_body, paginate, require, touch

bp = Blueprint("diplomas", __name__)


def _get_diploma_or_404(diploma_id):
    d = db.diplomas.get(diploma_id)
    if d is None:
        raise ApiError("ERR_DIPLOMA_NOT_FOUND", "Diploma not found.")
    return d


def _check_owner(user_id, role, diploma):
    if role == "Student":
        app = db.graduation_applications[diploma["application_id"]]
        sp = db.student_programs[app["student_program_id"]]
        require_owner(user_id, sp["student_id"])


# ---------------------------------------------------------------------------
# GET /diplomas
# ---------------------------------------------------------------------------


@bp.route("/diplomas", methods=["GET"])
def list_diplomas():
    user_id, role = get_auth()
    require_roles(role, ("RegistrarStaff", "Advisor", "Student"))
    limit, offset = parse_pagination()

    items = list(db.diplomas.values())
    if role == "Student":
        # Scope to the student's own applications
        own_app_ids = set()
        for sp in db.student_programs.values():
            if sp["student_id"] == user_id:
                for a in db.graduation_applications.values():
                    if a["student_program_id"] == sp["id"]:
                        own_app_ids.add(a["id"])
        items = [d for d in items if d["application_id"] in own_app_ids]

    app_id = request.args.get("application_id")
    status = request.args.get("status")
    reissue_of = request.args.get("reissue_of_diploma_id")
    if app_id:
        items = [d for d in items if d["application_id"] == app_id]
    if status:
        items = [d for d in items if d["status"] == status]
    if reissue_of:
        items = [d for d in items if d["reissue_of_diploma_id"] == reissue_of]
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)


# ---------------------------------------------------------------------------
# GET /diplomas/{id}
# ---------------------------------------------------------------------------


@bp.route("/diplomas/<diploma_id>", methods=["GET"])
def get_diploma(diploma_id):
    user_id, role = get_auth()
    require_roles(role, ("RegistrarStaff", "Advisor", "Student"))
    d = _get_diploma_or_404(diploma_id)
    _check_owner(user_id, role, d)
    return success_object(d)


# ---------------------------------------------------------------------------
# POST /diplomas/{id}/issue
# ---------------------------------------------------------------------------


@bp.route("/diplomas/<diploma_id>/issue", methods=["POST"])
def issue_diploma(diploma_id):
    _, role = get_auth()
    require_roles(role, ("RegistrarStaff",))
    d = _get_diploma_or_404(diploma_id)
    if d["status"] != "PENDING":
        raise ApiError("ERR_DIPLOMA_INVALID_STATE", "Diploma must be PENDING to issue.")
    d["status"] = "ISSUED"
    touch(d)
    return success_object(d)


# ---------------------------------------------------------------------------
# POST /diplomas/{id}/revoke
# ---------------------------------------------------------------------------


@bp.route("/diplomas/<diploma_id>/revoke", methods=["POST"])
def revoke_diploma(diploma_id):
    _, role = get_auth()
    require_roles(role, ("RegistrarStaff",))
    d = _get_diploma_or_404(diploma_id)
    body = json_body()
    reason = require(body, "reason")
    if d["status"] not in ("PENDING", "ISSUED"):
        raise ApiError(
            "ERR_DIPLOMA_INVALID_STATE",
            "Diploma must be PENDING or ISSUED to revoke.",
        )
    d["status"] = "REVOKED"
    d["revocation_reason"] = reason
    touch(d)
    return success_object(d)
