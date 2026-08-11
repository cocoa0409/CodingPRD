"""Union endpoints."""

from flask import Blueprint, request

from db import db
from errors import ERR_INVALID_REQUEST, ERR_INVALID_STATE, raise_err
from helpers import (
    ALL_ROLES, authenticate, get_body, lookup, new_entity, page, parse_pagination,
    req_enum, req_string, serialize, sort_items, touch,
)
from response import success_list, success_object
from services import decertify_cascade

bp = Blueprint("unions", __name__)

UNION_STATUSES = ("ACTIVE", "TRUSTEED", "DECERTIFIED")


@bp.post("/labor-relations/unions")
def create_union():
    authenticate(["LRAdmin"])
    body = get_body()
    name = req_string(body, "name")
    union_code = req_string(body, "union_code")
    # union_code must be unique across all unions (ERR_INVALID_REQUEST)
    for existing in db.unions.values():
        if existing["union_code"] == union_code:
            raise_err(ERR_INVALID_REQUEST, "union_code already exists: %s" % union_code)
    union = new_entity()
    union.update({
        "name": name,
        "union_code": union_code,
        "status": "ACTIVE",
        "open_information_request_count": 0,
    })
    db.unions[union["id"]] = union
    return success_object(serialize(union), status=201)


@bp.get("/labor-relations/unions")
def list_unions():
    authenticate(ALL_ROLES)
    limit, offset = parse_pagination()
    status_filter = request.args.get("status")
    items = [u for u in db.unions.values() if status_filter is None or u["status"] == status_filter]
    items = sort_items(items)
    slice_, total = page(items, limit, offset)
    return success_list([serialize(u) for u in slice_], limit, offset, total)


@bp.get("/labor-relations/unions/<union_id>")
def get_union(union_id):
    authenticate(ALL_ROLES)
    union = lookup(db.unions, union_id, "Union")
    return success_object(serialize(union))


@bp.post("/labor-relations/unions/<union_id>/state")
def transition_union(union_id):
    authenticate(["LRAdmin"])
    union = lookup(db.unions, union_id, "Union")
    body = get_body()
    to_status = req_enum(body, "to_status", UNION_STATUSES)

    if to_status == "TRUSTEED":
        if union["status"] != "ACTIVE":
            raise_err(ERR_INVALID_STATE, "Union must be ACTIVE to become TRUSTEED")
    elif to_status == "ACTIVE":
        if union["status"] != "TRUSTEED":
            raise_err(ERR_INVALID_STATE, "Union must be TRUSTEED to return to ACTIVE")
    else:  # DECERTIFIED
        if union["status"] not in ("ACTIVE", "TRUSTEED"):
            raise_err(ERR_INVALID_STATE, "Union must be ACTIVE or TRUSTEED to be DECERTIFIED")

    union["status"] = to_status
    touch(union)
    if to_status == "DECERTIFIED":
        decertify_cascade(union)
    return success_object(serialize(union))
