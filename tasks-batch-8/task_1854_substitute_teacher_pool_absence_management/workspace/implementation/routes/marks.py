"""SchoolSubstituteMark endpoints: create (DNR cascade), lift, list."""

from flask import Blueprint, request

import domain
from db import STORE, new_entity, touch, public
from errors import (
    raise_err, ERR_SCHOOL_NOT_FOUND, ERR_SUBSTITUTE_NOT_FOUND,
    ERR_MARK_NOT_FOUND, ERR_MARK_INVALID_STATE, ERR_INVALID_REQUEST,
    ERR_DUPLICATE_MARK,
)
from middleware import auth_context, require_role, require_coordinator_school, ALL_ROLES
from response import ok, paginated
from validate import body, req_str, req_enum, opt_int, opt_str

bp = Blueprint("marks", __name__)

MARK_TYPES = ("PREFERRED", "DO_NOT_RETURN")


@bp.route("/marks", methods=["POST"])
def create_mark():
    user_id, role = auth_context()
    data = body()
    school_id = req_str(data, "school_id")
    substitute_id = req_str(data, "substitute_id")
    mark_type = req_enum(data, "mark_type", MARK_TYPES)
    priority_rank = opt_int(data, "priority_rank")
    reason = opt_str(data, "reason")
    if mark_type == "DO_NOT_RETURN" and reason is None:
        raise_err(ERR_INVALID_REQUEST, "reason is required for DO_NOT_RETURN marks")
    require_role(role, ["SchoolCoordinator", "DistrictAdmin"])
    if role == "SchoolCoordinator":
        require_coordinator_school(user_id, school_id)
    if school_id not in STORE.schools:
        raise_err(ERR_SCHOOL_NOT_FOUND, "school id does not exist")
    if substitute_id not in STORE.substitutes:
        raise_err(ERR_SUBSTITUTE_NOT_FOUND, "substitute id does not exist")
    if domain.active_mark(school_id, substitute_id, mark_type) is not None:
        raise_err(ERR_DUPLICATE_MARK,
                  "an ACTIVE mark of this type already exists for (school, substitute)")
    m = new_entity(STORE.marks, {
        "school_id": school_id,
        "substitute_id": substitute_id,
        "mark_type": mark_type,
        "priority_rank": priority_rank,
        "reason": reason,
        "status": "ACTIVE",
        "source_flag_id": None,
    })
    if mark_type == "DO_NOT_RETURN":
        domain.dnr_cascade(school_id, substitute_id)
    return ok(public(m), status=201)


@bp.route("/marks/<mid>/lift", methods=["POST"])
def lift_mark(mid):
    user_id, role = auth_context()
    body()
    require_role(role, ["SchoolCoordinator", "DistrictAdmin"])
    m = STORE.marks.get(mid)
    if role == "SchoolCoordinator":
        require_coordinator_school(user_id, m["school_id"] if m else None)
    if m is None:
        raise_err(ERR_MARK_NOT_FOUND, "mark id does not exist")
    if m["status"] != "ACTIVE":
        raise_err(ERR_MARK_INVALID_STATE, "lift requires status ACTIVE")
    m["status"] = "LIFTED"
    touch(m)
    return ok(public(m))


def _list_marks(items):
    mark_type = request.args.get("mark_type")
    status = request.args.get("status")
    items = sorted(items, key=lambda m: (m["created_at"], m["_seq"]))
    if mark_type is not None:
        items = [m for m in items if m["mark_type"] == mark_type]
    if status is not None:
        items = [m for m in items if m["status"] == status]
    page, meta = paginated(items)
    return ok([public(m) for m in page], pagination=meta)


@bp.route("/schools/<sid>/marks", methods=["GET"])
def list_school_marks(sid):
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    if sid not in STORE.schools:
        raise_err(ERR_SCHOOL_NOT_FOUND, "school id does not exist")
    return _list_marks([m for m in STORE.marks.values() if m["school_id"] == sid])


@bp.route("/substitutes/<sid>/marks", methods=["GET"])
def list_substitute_marks(sid):
    _, role = auth_context()
    require_role(role, ALL_ROLES)
    if sid not in STORE.substitutes:
        raise_err(ERR_SUBSTITUTE_NOT_FOUND, "substitute id does not exist")
    return _list_marks([m for m in STORE.marks.values() if m["substitute_id"] == sid])
