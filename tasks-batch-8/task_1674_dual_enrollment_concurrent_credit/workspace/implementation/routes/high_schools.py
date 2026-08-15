"""HighSchool endpoints (PRD 3.1). State machine: ACTIVE -> SUSPENDED."""
from flask import Blueprint

from errors import raise_error, ERR_INVALID_STATE
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response
from services.core import new_record, public, touch
from validate import get_body, req_str, require_path_resource

bp = Blueprint("high_schools", __name__)


@bp.post("/high-schools")
def create_high_school():
    authorized(["DualCreditAdmin"])
    body = get_body()
    rec = new_record(
        "high_schools",
        {
            "name": req_str(body, "name"),
            "district_code": req_str(body, "district_code"),
            "status": "ACTIVE",
        },
    )
    return success_object(public(rec), status=201)


@bp.get("/high-schools")
def list_high_schools():
    return list_response("high_schools")


@bp.get("/high-schools/<rid>")
def get_high_school(rid):
    return get_one("high_schools", rid)


@bp.post("/high-schools/<rid>/suspend")
def suspend_high_school(rid):
    authorized(["DualCreditAdmin"])
    rec = require_path_resource("high_schools", rid)
    if rec["status"] != "ACTIVE":
        raise_error(ERR_INVALID_STATE, "only an ACTIVE high school can be suspended")
    rec["status"] = "SUSPENDED"
    touch(rec)
    return success_object(public(rec))
