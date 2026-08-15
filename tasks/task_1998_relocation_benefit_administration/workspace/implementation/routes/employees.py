from flask import Blueprint, request

from db import DB
from errors import err_not_found, err_already_terminal
from middleware import get_actor, require_role
from response import success_object
from serializers import serialize_employee
from util import require_fields, require_enum, require_string
from services.ledger import touch_entity

bp = Blueprint("employees", __name__)

JOB_LEVELS = {"ASSOCIATE", "MANAGER", "DIRECTOR", "EXECUTIVE"}
HOME_OWNERSHIP = {"HOMEOWNER", "RENTER"}

ALL_ROLES = ["MobilityCoordinator", "FinanceSpecialist", "ProgramManager", "Employee", "Vendor"]


@bp.route("/employees", methods=["POST"])
def create_employee():
    actor = get_actor()
    require_role(actor, ["MobilityCoordinator"])
    payload = request.get_json(silent=True) or {}
    require_fields(payload, ["full_name", "job_level", "home_ownership"])
    full_name = require_string(payload, "full_name")
    job_level = require_enum(payload, "job_level", JOB_LEVELS)
    home_ownership = require_enum(payload, "home_ownership", HOME_OWNERSHIP)

    with DB.lock:
        now = DB.now()
        e = {
            "id": DB.new_id(),
            "full_name": full_name,
            "job_level": job_level,
            "home_ownership": home_ownership,
            "employment_status": "ACTIVE",
            "termination_date": None,
            "created_at": now,
            "updated_at": now,
            "version": 0,
            "_seq": DB.next_seq(),
        }
        DB.employees[e["id"]] = e
        return success_object(serialize_employee(e), status=201)


@bp.route("/employees/<id>", methods=["GET"])
def get_employee(id):
    actor = get_actor()
    require_role(actor, ALL_ROLES)
    with DB.lock:
        e = DB.employees.get(id)
        if e is None:
            raise err_not_found("Employee not found")
        return success_object(serialize_employee(e))


@bp.route("/employees/<id>/terminate", methods=["POST"])
def terminate_employee(id):
    actor = get_actor()
    require_role(actor, ["MobilityCoordinator"])
    with DB.lock:
        e = DB.employees.get(id)
        if e is None:
            raise err_not_found("Employee not found")
        if e["employment_status"] == "TERMINATED":
            raise err_already_terminal("Employee already TERMINATED")
        e["employment_status"] = "TERMINATED"
        e["termination_date"] = DB.now()
        touch_entity(e)
        return success_object(serialize_employee(e))
