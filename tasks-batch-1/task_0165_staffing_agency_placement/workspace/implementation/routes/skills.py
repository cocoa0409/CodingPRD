"""Skill catalog routes (PRD 3.1)."""

from flask import Blueprint

import db
import errors
from errors import ApiError
from middleware import get_user_context, require_role, get_json_body
from response import object_response
from services import common, serialize

bp = Blueprint("skills", __name__)

SKILL_CATEGORIES = {"TECH", "CLINICAL", "INDUSTRIAL", "CLERICAL"}


@bp.route("/staffing/skills", methods=["POST"])
def create_skill():
    _, role = get_user_context()
    require_role(role, {"Recruiter", "AccountManager"})
    body = get_json_body()

    code = common.require_str(body, "code")
    category = common.require_enum(body, "category", SKILL_CATEGORIES)

    code = code.upper()
    # Unique across the catalog (after uppercasing).
    for s in db.skills.values():
        if s["code"] == code:
            raise ApiError(errors.ERR_SKILL_CODE_DUPLICATE, 409, "Skill code already exists.")

    rec = common.init_immutable({
        "code": code,
        "category": category,
    })
    db.skills[rec["id"]] = rec
    return object_response(serialize.skill(rec), 201)


@bp.route("/staffing/skills/<sid>", methods=["GET"])
def get_skill(sid):
    _, role = get_user_context()
    require_role(role, {"AccountManager", "Recruiter"})
    rec = common.get_or_404(db.skills, sid, errors.ERR_SKILL_NOT_FOUND)
    return object_response(serialize.skill(rec), 200)
