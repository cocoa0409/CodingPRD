"""BoardGrade endpoints."""
from flask import Blueprint

from db import db
from errors import (
    err_duplicate_code,
    err_invalid_request,
    err_invalid_state,
    err_not_found,
)
from middleware import require_roles
from response import success_object
from services.calcs import bump
from services.serialize import serialize_board_grade
from util import D, is_int, is_num, new_id, utcnow_iso
from ._helpers import get_json_body, require_fields

bp = Blueprint("board_grades", __name__)

ALL_ROLES = ("PlantAdmin", "SalesRep", "ProductionPlanner", "CustomerService", "ClaimsAdjuster", "Customer")
FLUTES = {"B", "C", "E", "BC"}


@bp.route("/api/board-grades", methods=["POST"])
@require_roles("PlantAdmin")
def create_board_grade(_user_id, _role):
    body = get_json_body()
    require_fields(body, [
        "grade_code", "liner_combo", "flute",
        "ect_rating_lbs_per_in", "burst_rating_psi", "basis_weight_lbs_per_msf",
    ])

    grade_code = body["grade_code"]
    liner_combo = body["liner_combo"]
    flute = body["flute"]
    ect = body["ect_rating_lbs_per_in"]
    burst = body["burst_rating_psi"]
    bw = body["basis_weight_lbs_per_msf"]

    if not isinstance(grade_code, str) or not grade_code.strip():
        raise err_invalid_request("grade_code must be a non-empty string")
    if not isinstance(liner_combo, str) or not liner_combo.strip():
        raise err_invalid_request("liner_combo must be a non-empty string")
    if flute not in FLUTES:
        raise err_invalid_request("flute must be one of B, C, E, BC")
    if not is_int(ect) or ect <= 0:
        raise err_invalid_request("ect_rating_lbs_per_in must be an integer > 0")
    if not is_int(burst) or burst <= 0:
        raise err_invalid_request("burst_rating_psi must be an integer > 0")
    if not is_num(bw) or D(bw) <= 0:
        raise err_invalid_request("basis_weight_lbs_per_msf must be > 0")

    # Uniqueness across all BoardGrades
    for g in db.board_grades.values():
        if g["grade_code"] == grade_code:
            raise err_duplicate_code(f"grade_code {grade_code} already exists")

    now = utcnow_iso()
    gid = new_id()
    grade = {
        "id": gid,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "grade_code": grade_code,
        "liner_combo": liner_combo,
        "flute": flute,
        "ect_rating_lbs_per_in": ect,
        "burst_rating_psi": burst,
        "basis_weight_lbs_per_msf": D(bw),
        "status": "ACTIVE",
    }
    db.board_grades[gid] = grade
    return success_object(serialize_board_grade(grade), 201)


@bp.route("/api/board-grades/<gid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_board_grade(gid, _user_id, _role):
    g = db.board_grades.get(gid)
    if g is None:
        raise err_not_found("board grade not found")
    return success_object(serialize_board_grade(g), 200)


@bp.route("/api/board-grades/<gid>/discontinue", methods=["POST"])
@require_roles("PlantAdmin")
def discontinue_board_grade(gid, _user_id, _role):
    g = db.board_grades.get(gid)
    if g is None:
        raise err_not_found("board grade not found")
    if g["status"] != "ACTIVE":
        raise err_invalid_state("grade is not ACTIVE")
    g["status"] = "DISCONTINUED"
    bump(g)
    return success_object(serialize_board_grade(g), 200)
