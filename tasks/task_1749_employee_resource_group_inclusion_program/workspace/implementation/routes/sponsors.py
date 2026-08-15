"""ExecutiveSponsor endpoints."""
from flask import Blueprint

from db import STORE
from errors import ApiError, ERR_NOT_FOUND
from middleware import authenticate, body, req_enum, req_int, req_str
from services import new_entity, sponsor_json, touch
from util import ok_object

bp = Blueprint("sponsors", __name__)

ALL_ROLES = ("DeiAdmin", "ExecutiveSponsor", "GroupLeader", "Employee")
SPONSOR_STATUSES = ("ACTIVE", "ON_LEAVE", "INACTIVE")


def get_sponsor(sponsor_id):
    s = STORE["sponsors"].get(sponsor_id)
    if s is None:
        raise ApiError(ERR_NOT_FOUND, 404, "sponsor not found")
    return s


@bp.post("/v1/sponsors")
def create_sponsor():
    authenticate(("DeiAdmin",))
    data = body()
    employee_id = req_str(data, "employee_id")
    max_groups = req_int(data, "max_groups", min_v=1)
    max_mentees = req_int(data, "max_mentees", min_v=1)
    s = new_entity("sponsors", {
        "employee_id": employee_id,
        "max_groups": max_groups,
        "max_mentees": max_mentees,
        "status": "ACTIVE",
    })
    return ok_object(sponsor_json(s), 201)


@bp.get("/v1/sponsors/<sponsor_id>")
def read_sponsor(sponsor_id):
    authenticate(ALL_ROLES)
    return ok_object(sponsor_json(get_sponsor(sponsor_id)))


@bp.post("/v1/sponsors/<sponsor_id>/set-status")
def set_sponsor_status(sponsor_id):
    authenticate(("DeiAdmin",))
    data = body()
    to_status = req_enum(data, "to_status", SPONSOR_STATUSES)
    s = get_sponsor(sponsor_id)
    s["status"] = to_status
    touch(s)
    return ok_object(sponsor_json(s))
