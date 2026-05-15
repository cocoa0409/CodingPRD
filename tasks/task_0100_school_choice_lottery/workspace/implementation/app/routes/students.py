"""Student endpoints."""
from flask import Blueprint, g, jsonify

from ..auth import require_auth
from ..errors import APIError
from ..responses import success_response
from ..services.lookups import fk_family, get_student_or_404
from ..store import get_lock, get_store, stamp_create
from ..validators import (get_json_body, optional_field, require_integer,
                          require_string)


bp = Blueprint("students", __name__, url_prefix="/enrollment/students")


def _serialize(s: dict) -> dict:
    return {
        "id": s["id"],
        "family_id": s["family_id"],
        "grade_level_next_year": s["grade_level_next_year"],
        "has_iep": s.get("has_iep", False),
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


@bp.route("", methods=["POST"])
@require_auth("FamilyUser")
def create_student():
    body = get_json_body()
    family_id = require_string(body, "family_id")
    grade_level_next_year = require_integer(body, "grade_level_next_year", minimum=0, maximum=12)
    has_iep = optional_field(body, "has_iep", False)
    if not isinstance(has_iep, bool):
        raise APIError("ERR_VALIDATION", "'has_iep' must be a boolean")
    with get_lock():
        fk_family(family_id)
        if g.user_id != family_id:
            raise APIError("ERR_FORBIDDEN", "FamilyUser may only add students to their own family")
        record = {
            "family_id": family_id,
            "grade_level_next_year": grade_level_next_year,
            "has_iep": has_iep,
        }
        stamp_create(record)
        get_store().students[record["id"]] = record
        resp, status = success_response(_serialize(record), status=201, response_type="object")
    return jsonify(resp), status


@bp.route("/<student_id>", methods=["GET"])
@require_auth("FamilyUser", "DistrictAdmin")
def get_student(student_id):
    rec = get_student_or_404(student_id)
    resp, status = success_response(_serialize(rec), status=200, response_type="object")
    return jsonify(resp), status
