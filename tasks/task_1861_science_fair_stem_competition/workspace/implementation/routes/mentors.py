"""Mentor routes."""

from flask import Blueprint
import db
import validators as V
from middleware import require_roles
from response import success_object, success_list
from pagination import parse_pagination, paginate
from serializers import mentor_out
from errors import raise_err, ERR_NOT_FOUND

bp = Blueprint("mentors", __name__)

_ALL_ROLES = ("FairDirector", "Mentor", "EthicsReviewer", "Judge",
              "OperationsLead", "SafetyInspector")


@bp.route("/science-fair/mentors", methods=["POST"])
def create_mentor():
    body = V.get_json_body()
    V.require_fields(body, ["full_name", "email"])
    full_name = V.req_str(body, "full_name")
    email = V.req_str(body, "email")

    require_roles("FairDirector")

    now = db.now_display_iso()
    m = {
        "id": db.new_id(),
        "full_name": full_name,
        "email": email,
        "recognition_points": 0,
        "leaderboard_points": 0,
        "recognition_tier": "NONE",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.mentors[m["id"]] = m
    return success_object(mentor_out(m), 201)


@bp.route("/science-fair/mentors", methods=["GET"])
def list_mentors():
    require_roles(*_ALL_ROLES)
    limit, offset = parse_pagination()
    data, total = paginate(list(db.mentors.values()), mentor_out,
                           limit, offset)
    return success_list(data, limit, offset, total)


@bp.route("/science-fair/mentors/<mid>", methods=["GET"])
def get_mentor(mid):
    require_roles(*_ALL_ROLES)
    m = db.mentors.get(mid)
    if m is None:
        raise_err(ERR_NOT_FOUND, f"Mentor not found: {mid}")
    return success_object(mentor_out(m))
