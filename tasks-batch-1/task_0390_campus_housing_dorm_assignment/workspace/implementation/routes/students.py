"""Student routes."""

from flask import Blueprint

import db
import errors
import response
import common
from middleware import authenticate, require_role
from services import core

bp = Blueprint("students", __name__)

ALL_ROLES = ("HousingOfficer", "Student", "ResidentAdvisor")
CLASS_YEARS = {"FRESHMAN", "SOPHOMORE", "JUNIOR", "SENIOR"}
GENDERS = {"MALE", "FEMALE", "NONBINARY"}


@bp.route("/students", methods=["POST"])
def create_student():
    principal = authenticate()
    require_role(principal, ("HousingOfficer",))
    body = common.get_body()

    common.require_fields(body, ["full_name", "class_year", "gender_identity", "lottery_number"])
    full_name = body["full_name"]
    class_year = common.require_enum(body, "class_year", CLASS_YEARS)
    gender = common.require_enum(body, "gender_identity", GENDERS)
    lottery_number = common.require_int(body, "lottery_number", min_value=1)

    with db.LOCK:
        rec = core.init_record({
            "full_name": full_name,
            "class_year": class_year,
            "gender_identity": gender,
            "lottery_number": lottery_number,
            "account_balance_cents": 0,
            "status": "ACTIVE",
        })
        db.students[rec["id"]] = rec
        return response.object_response(core.serialize(rec), status=201)


@bp.route("/students/<student_id>", methods=["GET"])
def get_student(student_id):
    principal = authenticate()
    require_role(principal, ALL_ROLES)
    with db.LOCK:
        rec = core.get_or_404(db.students, student_id)
        return response.object_response(core.serialize(rec))


@bp.route("/students/<student_id>/place-hold", methods=["POST"])
def place_hold(student_id):
    principal = authenticate()
    require_role(principal, ("HousingOfficer",))
    with db.LOCK:
        rec = core.get_or_404(db.students, student_id)
        if rec["status"] != "ACTIVE":
            raise errors.invalid_state("Student is not ACTIVE.")
        rec["status"] = "HOLD"
        core.touch(rec)
        return response.object_response(core.serialize(rec))


@bp.route("/students/<student_id>/release-hold", methods=["POST"])
def release_hold(student_id):
    principal = authenticate()
    require_role(principal, ("HousingOfficer",))
    with db.LOCK:
        rec = core.get_or_404(db.students, student_id)
        if rec["status"] != "HOLD":
            raise errors.invalid_state("Student is not on HOLD.")
        rec["status"] = "ACTIVE"
        core.touch(rec)
        return response.object_response(core.serialize(rec))
