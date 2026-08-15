"""Student endpoints."""

from flask import Blueprint, request
import db
from db import new_id, now_iso
from middleware import get_auth, require_role, check_student_ownership
from response import success_object
from utils import require_string, require_number, require_enum
from errors import not_found, invalid_request

bp = Blueprint("students", __name__)

CONDUCT_STANDINGS = {"GOOD_STANDING", "CONDUCT_REVIEW", "CONDUCT_HOLD"}


@bp.route("/api/v1/students", methods=["POST"])
def create_student():
    user_id, role = get_auth()
    require_role(role, ["ProgramCoordinator"])

    body = request.get_json(silent=True) or {}
    full_name = require_string(body, "full_name")
    email = require_string(body, "email")
    gpa = require_number(body, "gpa")
    conduct_standing = require_enum(body, "conduct_standing", CONDUCT_STANDINGS)

    aid_award_cents = body.get("aid_award_cents", 0)
    if isinstance(aid_award_cents, bool) or not isinstance(aid_award_cents, int):
        raise invalid_request("aid_award_cents must be an integer")

    if not (0.0 <= gpa <= 4.0):
        raise invalid_request("gpa must be between 0.0 and 4.0")
    if aid_award_cents < 0:
        raise invalid_request("aid_award_cents must be >= 0")

    ts = now_iso()
    rec = {
        "id": new_id(),
        "full_name": full_name,
        "email": email,
        "gpa": gpa,
        "conduct_standing": conduct_standing,
        "aid_award_cents": aid_award_cents,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db.students[rec["id"]] = rec
    return success_object(rec, 201)


@bp.route("/api/v1/students/<id>", methods=["GET"])
def get_student(id):
    user_id, role = get_auth()
    require_role(role, ["ProgramCoordinator", "Student"])

    rec = db.students.get(id)
    if not rec:
        raise not_found("Student not found")

    check_student_ownership(user_id, role, rec["id"])
    return success_object(dict(rec), 200)
