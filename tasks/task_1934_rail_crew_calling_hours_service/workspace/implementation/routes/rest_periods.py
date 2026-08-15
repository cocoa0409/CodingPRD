from flask import Blueprint, request

from db import store
from errors import ApiError, ERR_NOT_FOUND
from middleware import auth, require_roles
from response import paged, ok_obj
from services import refresh_rest

bp = Blueprint("rest_periods", __name__)

ALL_ROLES = ("CrewManager", "CrewCaller", "Employee")


@bp.get("/api/rest-periods")
def list_rest_periods():
    _, role = auth()
    require_roles(role, ALL_ROLES)
    rows = list(store.rest_periods.values())
    employee_id = request.args.get("employee_id")
    if employee_id is not None:
        rows = [r for r in rows if r["employee_id"] == employee_id]
    rs = request.args.get("rest_status")
    if rs is not None:
        rows = [r for r in rows if r["rest_status"] == rs]
    for r in rows:
        if r["rest_status"] == "OPEN":
            refresh_rest(r)
    return paged(rows, request.args)


@bp.get("/api/rest-periods/<rp_id>")
def get_rest_period(rp_id):
    _, role = auth()
    require_roles(role, ALL_ROLES)
    rp = store.rest_periods.get(rp_id)
    if rp is None:
        raise ApiError(ERR_NOT_FOUND, 404, "RestPeriod '%s' not found." % rp_id)
    if rp["rest_status"] == "OPEN":
        refresh_rest(rp)
    return ok_obj(rp)
