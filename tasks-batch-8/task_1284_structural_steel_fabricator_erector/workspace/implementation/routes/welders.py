"""Welder endpoints."""

from flask import Blueprint

from envelope import ok_object
from errors import ApiError, ERR_INVALID_STATE, ERR_NOT_FOUND
from store import new_record, store, touch, public
from validate import authenticate, get_body, req_date, req_enum, req_str, require_role

bp = Blueprint("welders", __name__)

ADMIN = {"FABRICATOR_ADMIN"}


def view(w):
    return public(w)


@bp.post("/welders")
def create_welder():
    uid, role = authenticate()
    require_role(role, ADMIN)
    body = get_body()
    full_name = req_str(body, "full_name")
    qual_process = req_enum(body, "qual_process", ("SMAW", "FCAW", "GMAW"))
    qual_expires = req_date(body, "qual_expires_on")
    w = new_record()
    w.update(
        {
            "full_name": full_name,
            "qual_process": qual_process,
            "qual_expires_on": qual_expires.isoformat(),
            "status": "ACTIVE",
        }
    )
    store.welders[w["id"]] = w
    return ok_object(view(w), 201)


@bp.post("/welders/<wid>/suspend")
def suspend_welder(wid):
    uid, role = authenticate()
    require_role(role, ADMIN)
    w = store.welders.get(wid)
    if w is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Welder not found.")
    if w["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409, "Welder must be ACTIVE to suspend.")
    w["status"] = "SUSPENDED"
    touch(w)
    return ok_object(view(w))
