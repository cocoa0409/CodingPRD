"""AdopterGroup endpoints (PRD 3.1)."""
from flask import Blueprint

from db import db
from middleware import get_caller, check_role, check_ownership, COORD, LEADER
from response import success_object
from services.core import stamp_new, public
from validate import get_body, req_str, req_enum, require_resource
from errors import ERR_GROUP_NOT_FOUND

bp = Blueprint("groups", __name__)

ORG_TYPES = ["CIVIC", "BUSINESS", "SCHOOL", "FAITH", "OTHER"]


@bp.post("/program/groups")
def create_group():
    caller = get_caller()
    check_role(caller, [LEADER])
    body = get_body()
    rec = stamp_new({
        "name": req_str(body, "name"),
        "org_type": req_enum(body, "org_type", ORG_TYPES),
        "contact_name": req_str(body, "contact_name"),
        "contact_email": req_str(body, "contact_email"),
    })
    db["groups"][rec["id"]] = rec
    return success_object(public(rec), status=201)


@bp.get("/program/groups/<gid>")
def get_group(gid):
    caller = get_caller()
    check_role(caller, [COORD, LEADER])
    rec = require_resource("groups", gid, ERR_GROUP_NOT_FOUND)
    # The group record is the root of its own chain: a leader reads only their own.
    check_ownership(caller, rec["id"])
    return success_object(public(rec))
