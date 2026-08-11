"""Attorney endpoints (PRD §3.1)."""
from flask import Blueprint, request

from db import STORE
from errors import ApiError
from middleware import get_auth, require_roles
from response import success_object, success_list
from services.core import (
    get_body, req_str, req_str_list, new_entity, paginate, path_attorney,
)

bp = Blueprint("attorneys", __name__)

ALL = ("CourtAdmin", "Attorney", "CourtClerk", "ParalegalStaff")


@bp.post("/appellate/attorneys")
def create_attorney():
    auth = get_auth()
    require_roles(auth, ("CourtAdmin",))
    body = get_body()
    bar = req_str(body, "bar_number")
    full_name = req_str(body, "full_name")
    email = req_str(body, "email")
    admitted = req_str_list(body, "admitted_court_ids")

    for a in STORE.attorneys.values():
        if a["bar_number"] == bar:
            raise ApiError("ERR_DUPLICATE", "bar_number already registered", 409)

    att = new_entity({
        "bar_number": bar,
        "full_name": full_name,
        "email": email,
        "admitted_court_ids": admitted,
    })
    STORE.attorneys[att["id"]] = att
    att.pop("_seq", None)
    return success_object(att, 201)


@bp.get("/appellate/attorneys/<aid>")
def get_attorney(aid):
    auth = get_auth()
    require_roles(auth, ALL)
    att = path_attorney(aid)
    out = dict(att)
    out.pop("_seq", None)
    return success_object(out)


@bp.get("/appellate/attorneys")
def list_attorneys():
    auth = get_auth()
    require_roles(auth, ALL)
    items = list(STORE.attorneys.values())
    bar = request.args.get("bar_number")
    if bar is not None:
        items = [a for a in items if a["bar_number"] == bar]
    page, limit, offset, total = paginate(items)
    return success_list(page, limit, offset, total)
