"""Member endpoints: register, get, lifecycle transitions."""
from flask import Blueprint

from db import store, new_common, touch
from errors import ApiError
from middleware import authenticate, require_roles, ANY_ROLE
from response import ok, created
from validation import get_body, req_string, req_enum

bp = Blueprint("members", __name__)

MEMBER_STATUSES = {"PENDING", "ACTIVE", "SUSPENDED", "WITHDRAWN"}
MEMBER_TRANSITIONS = {
    ("PENDING", "ACTIVE"),
    ("ACTIVE", "SUSPENDED"),
    ("SUSPENDED", "ACTIVE"),
    ("ACTIVE", "WITHDRAWN"),
}
IN_FLIGHT_DELIVERY = {"SCHEDULED", "RECEIVED", "GRADED", "DISPUTED"}


@bp.post("/coop/members")
def create_member():
    body = get_body()
    member_code = req_string(body, "member_code")
    full_name = req_string(body, "full_name")

    _, role = authenticate()
    require_roles(role, {"CoopAdmin"})

    if any(m["member_code"] == member_code for m in store.members.values()):
        raise ApiError("ERR_DUPLICATE_MEMBER_CODE", 409,
                       "A member with the same member_code already exists")

    member = new_common({
        "member_code": member_code,
        "full_name": full_name,
        "status": "PENDING",
    })
    store.members[member["id"]] = member
    return created(member)


@bp.get("/coop/members/<member_id>")
def get_member(member_id):
    _, role = authenticate()
    require_roles(role, ANY_ROLE)
    member = store.members.get(member_id)
    if member is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Member not found")
    return ok(member)


@bp.post("/coop/members/<member_id>/transition")
def transition_member(member_id):
    body = get_body()
    to = req_enum(body, "to", MEMBER_STATUSES)

    _, role = authenticate()
    require_roles(role, {"CoopAdmin"})

    member = store.members.get(member_id)
    if member is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Member not found")

    if (member["status"], to) not in MEMBER_TRANSITIONS:
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Member transition %s -> %s is not defined" % (member["status"], to))

    if to == "WITHDRAWN":
        for d in store.deliveries.values():
            if d["member_id"] == member_id and d["status"] in IN_FLIGHT_DELIVERY:
                raise ApiError("ERR_INVALID_STATE", 409,
                               "Member has deliveries still in flight")

    member["status"] = to
    touch(member)
    return ok(member)
