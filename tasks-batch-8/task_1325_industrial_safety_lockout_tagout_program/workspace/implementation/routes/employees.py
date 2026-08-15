"""Employee registry (PRD 3.4). EHSManager writes; all roles read."""

from flask import Blueprint

import db
from errors import ApiError
from middleware import auth, ALL_ROLES
from response import ok
from services import core

bp = Blueprint("employees", __name__)


@bp.route("/employees", methods=["POST"])
def create_employee():
    auth(["EHSManager"])
    body = core.body_json()
    employee_no = core.req_str(body, "employee_no")
    full_name = core.req_str(body, "full_name")
    qualification = core.req_enum(body, "qualification", ("AFFECTED", "AUTHORIZED"))
    # Uniqueness (PRD 2.8 stage 11): duplicate employee_no reports as ERR_VALIDATION.
    for e in db.DB["employees"].values():
        if e["employee_no"] == employee_no:
            raise ApiError("ERR_VALIDATION", 400, "employee_no must be unique across all employees")
    e = core.stamp_new({
        "id": core.new_id(),
        "employee_no": employee_no,
        "full_name": full_name,
        "qualification": qualification,
        "status": "ACTIVE",
    })
    db.DB["employees"][e["id"]] = e
    return ok(core.employee_view(e), 201)


@bp.route("/employees/<eid>", methods=["GET"])
def get_employee(eid):
    auth(ALL_ROLES)
    e = core.get_or_404("employees", eid, "Employee")
    return ok(core.employee_view(e))
