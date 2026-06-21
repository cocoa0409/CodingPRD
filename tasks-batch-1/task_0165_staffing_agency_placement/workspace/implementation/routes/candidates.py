"""Candidate routes (PRD 3.1)."""

from flask import Blueprint

import db
import errors
from errors import ApiError
from middleware import get_user_context, require_role, get_json_body
from response import object_response
from services import common, serialize

bp = Blueprint("candidates", __name__)


@bp.route("/staffing/candidates", methods=["POST"])
def create_candidate():
    _, role = get_user_context()
    require_role(role, {"Recruiter"})
    body = get_json_body()

    full_name = common.require_str(body, "full_name")
    skill_codes = common.require(body, "skill_codes")
    if not isinstance(skill_codes, list) or not all(isinstance(c, str) for c in skill_codes):
        raise ApiError(errors.ERR_VALIDATION, 422, "skill_codes must be an array of strings.")
    base_pay_rate_cents = common.require_int(body, "base_pay_rate_cents")

    # Existence (priority 3): each skill_code must resolve in the catalog.
    catalog = {s["code"] for s in db.skills.values()}
    for c in skill_codes:
        if c not in catalog:
            raise ApiError(errors.ERR_SKILL_NOT_FOUND, 404, "Skill code not in catalog.")

    rec = common.init_mutable({
        "full_name": full_name,
        "skill_codes": list(skill_codes),
        "base_pay_rate_cents": base_pay_rate_cents,
        "status": "AVAILABLE",
    })
    db.candidates[rec["id"]] = rec
    return object_response(serialize.candidate(rec), 201)


@bp.route("/staffing/candidates/<cid>", methods=["GET"])
def get_candidate(cid):
    user_id, role = get_user_context()
    require_role(role, {"Recruiter", "AccountManager", "Candidate"})
    rec = common.get_or_404(db.candidates, cid, errors.ERR_CANDIDATE_NOT_FOUND)
    if role == "Candidate" and rec["id"] != user_id:
        raise ApiError(errors.ERR_UNAUTHORIZED, 403, "Candidate may only read its own record.")
    return object_response(serialize.candidate(rec), 200)


@bp.route("/staffing/candidates/<cid>", methods=["PATCH"])
def patch_candidate(cid):
    _, role = get_user_context()
    require_role(role, {"Recruiter"})
    rec = common.get_or_404(db.candidates, cid, errors.ERR_CANDIDATE_NOT_FOUND)
    body = get_json_body()
    target = common.require_enum(body, "target_status", {"AVAILABLE", "ON_ASSIGNMENT", "INACTIVE"})

    # Only the AVAILABLE -> INACTIVE transition is operator-driven (PRD 3.1).
    if target == "INACTIVE":
        if rec["status"] != "AVAILABLE":
            raise ApiError(errors.ERR_CANDIDATE_NOT_AVAILABLE, 409, "Candidate is not AVAILABLE.")
        rec["status"] = "INACTIVE"
        common.touch(rec)
        return object_response(serialize.candidate(rec), 200)

    # Any other target is not a permitted operator transition for this endpoint.
    raise ApiError(errors.ERR_CANDIDATE_NOT_AVAILABLE, 409, "Unsupported candidate transition.")
