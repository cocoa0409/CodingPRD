"""RouteDriverProfile endpoints (PRD 3.4)."""
from flask import Blueprint

from common import get_json_body, get_or_404, list_response, require_str
from db import db, stamp_create
from middleware import require_roles
from response import object_response
from services import serialize

bp = Blueprint("drivers", __name__)

ALL_ROLES = ("FieldOps", "RouteDriver", "HostManager", "FinanceClerk")


@bp.route("/operations/drivers", methods=["POST"])
@require_roles("FieldOps")
def create_driver():
    body = get_json_body()
    full_name = require_str(body, "full_name")
    employee_code = require_str(body, "employee_code")
    obj = {
        "full_name": full_name,
        "employee_code": employee_code,
        "status": "ACTIVE",
    }
    stamp_create(obj)
    db.drivers[obj["id"]] = obj
    return object_response(serialize.driver(obj), 201)


@bp.route("/operations/drivers", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_drivers():
    return list_response(list(db.drivers.values()), serialize.driver)


@bp.route("/operations/drivers/<driver_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_driver(driver_id):
    obj = get_or_404("drivers", driver_id)
    return object_response(serialize.driver(obj))
