"""BusinessUnit routes.  A unit id doubles as a BusinessUnitManager identity."""

from flask import Blueprint

import db
from errors import ApiError
from middleware import (BUSINESS_UNIT_MANAGER, COMPENSATION_COMMITTEE,
                        FINANCE_CONTROLLER, HR_BUSINESS_PARTNER, PLAN_ADMIN,
                        authenticate, get_body, query_param, req_string)
from response import object_response
from routes.common import paginated
from serialize import business_unit_out
from services import lookup

bp = Blueprint("business_units", __name__)

READ_ROLES = [PLAN_ADMIN, COMPENSATION_COMMITTEE, BUSINESS_UNIT_MANAGER,
              HR_BUSINESS_PARTNER, FINANCE_CONTROLLER]


@bp.route("/business-units", methods=["POST"])
def create_business_unit():
    authenticate([PLAN_ADMIN])
    body = get_body()
    unit_code = req_string(body, "unit_code")
    name = req_string(body, "name")

    for existing in db.ordered(db.business_units):
        if existing["unit_code"] == unit_code:
            raise ApiError("ERR_DUPLICATE_RESOURCE",
                           "Business unit code '%s' already exists" % unit_code)

    unit = db.base_record()
    unit.update({"unit_code": unit_code, "name": name})
    db.business_units[unit["id"]] = unit
    return object_response(business_unit_out(unit), 201)


@bp.route("/business-units/<unit_id>", methods=["GET"])
def get_business_unit(unit_id):
    authenticate(READ_ROLES)
    return object_response(business_unit_out(lookup.business_unit(unit_id)))


@bp.route("/business-units", methods=["GET"])
def list_business_units():
    authenticate(READ_ROLES)
    unit_code = query_param("unit_code")
    records = db.ordered(db.business_units)
    if unit_code is not None:
        records = [r for r in records if r["unit_code"] == unit_code]
    return paginated(records, business_unit_out)
