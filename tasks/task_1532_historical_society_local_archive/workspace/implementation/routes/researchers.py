"""Researcher routes (PRD §3.6)."""

from __future__ import annotations

from flask import Blueprint, request

import db
from errors import raise_err, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_DUPLICATE_EMAIL
from middleware import require_roles, ANY_ROLE
from response import success_object, success_list
from services.rollup import serialize_researcher
from util import get_json_body, as_str, paginate

bp = Blueprint("researchers", __name__)


def get_researcher(rid: str) -> dict:
    r = db.researchers.get(rid)
    if r is None:
        raise_err(ERR_NOT_FOUND, f"Researcher not found: {rid}")
    return r


@bp.route("/researchers", methods=["POST"])
@require_roles("ReadingRoomStaff")
def create_researcher(_user_id: str, _role: str):
    body = get_json_body()
    full_name = as_str(body, "full_name", required=True)
    email = as_str(body, "email", required=True)
    affiliation = as_str(body, "affiliation", required=False, default=None)

    if any(r["email"] == email for r in db.researchers.values()):
        raise_err(ERR_DUPLICATE_EMAIL, f"email already registered: {email}")

    researcher = {
        **db.make_common_fields(),
        "full_name": full_name,
        "email": email,
        "affiliation": affiliation,
        "status": "ACTIVE",
        "total_charged_cents": 0,
    }
    db.researchers[researcher["id"]] = researcher
    return success_object(serialize_researcher(researcher), 201)


@bp.route("/researchers", methods=["GET"])
@require_roles(*ANY_ROLE)
def list_researchers(_user_id: str, _role: str):
    status = request.args.get("status")
    rows = list(db.researchers.values())
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, limit, offset, total = paginate(rows)
    return success_list([serialize_researcher(r) for r in page], limit, offset, total)


@bp.route("/researchers/<rid>", methods=["GET"])
@require_roles(*ANY_ROLE)
def get_one_researcher(rid: str, _user_id: str, _role: str):
    return success_object(serialize_researcher(get_researcher(rid)))


@bp.route("/researchers/<rid>/reinstate", methods=["POST"])
@require_roles("ReadingRoomStaff")
def reinstate(rid: str, _user_id: str, _role: str):
    r = get_researcher(rid)
    if r["status"] != "SUSPENDED":
        raise_err(ERR_INVALID_STATE, "Only a SUSPENDED researcher may be reinstated")
    r["status"] = "ACTIVE"
    db.touch(r)
    return success_object(serialize_researcher(r))
