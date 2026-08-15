"""StaffMember endpoints."""
from flask import Blueprint, request

from db import STORE
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_RESOURCE_IN_USE,
    ERR_STAFF_NOT_FOUND,
)
from helpers import (
    STAFF_ROLES,
    get_payload,
    new_id,
    opt_str_list,
    paginate,
    req_enum,
    req_str,
)
from middleware import ALL_ROLES, require_roles
from response import success
from services import (
    TERMINAL_CASE_STATUSES,
    assignment_out,
    new_entity,
    staff_out,
    touch,
)

bp = Blueprint("staff", __name__)


@bp.route("/cath-lab/staff", methods=["POST"])
@require_roles("CathLabScheduler")
def create_staff():
    data = get_payload()
    full_name = req_str(data, "full_name")
    staff_role = req_enum(data, "staff_role", STAFF_ROLES)
    credentials = opt_str_list(data, "credentials")
    is_active = data.get("is_active", True)
    if not isinstance(is_active, bool):
        raise ApiError(ERR_INVALID_REQUEST, "is_active must be a boolean", 400)
    member = new_entity()
    member["id"] = new_id()
    member.update(
        {
            "full_name": full_name,
            "staff_role": staff_role,
            "credentials": credentials,
            "is_active": is_active,
        }
    )
    STORE["staff"][member["id"]] = member
    return success(staff_out(member), 201)


@bp.route("/cath-lab/staff", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_staff():
    role = request.args.get("staff_role")
    is_active_raw = request.args.get("is_active")
    is_active = None
    if is_active_raw is not None:
        if is_active_raw.lower() == "true":
            is_active = True
        elif is_active_raw.lower() == "false":
            is_active = False
        else:
            is_active = "__no_match__"
    items = []
    for s in STORE["staff"].values():
        if role is not None and s["staff_role"] != role:
            continue
        if is_active is not None and s["is_active"] != is_active:
            continue
        items.append(s)
    items.sort(key=lambda s: s["_seq"])
    page, pg = paginate(items)
    return success([staff_out(s) for s in page], 200, is_list=True, pagination=pg)


@bp.route("/cath-lab/staff/<staff_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_staff(staff_id):
    member = STORE["staff"].get(staff_id)
    if member is None:
        raise ApiError(ERR_STAFF_NOT_FOUND, "No StaffMember with the given id", 404)
    return success(staff_out(member), 200)


@bp.route("/cath-lab/staff/<staff_id>", methods=["PATCH"])
@require_roles("CathLabScheduler")
def patch_staff(staff_id):
    member = STORE["staff"].get(staff_id)
    if member is None:
        raise ApiError(ERR_STAFF_NOT_FOUND, "No StaffMember with the given id", 404)
    data = get_payload()
    if "is_active" not in data or not isinstance(data["is_active"], bool):
        raise ApiError(ERR_INVALID_REQUEST, "is_active is required and must be a boolean", 400)
    target = data["is_active"]
    if target == member["is_active"]:
        return success(staff_out(member), 200)
    if target is False:
        for a in STORE["assignments"].values():
            if a["staff_id"] == staff_id and a["status"] == "ASSIGNED":
                case = STORE["cases"].get(a["case_id"])
                if case is not None and case["status"] not in TERMINAL_CASE_STATUSES:
                    raise ApiError(
                        ERR_RESOURCE_IN_USE,
                        "Staff member holds ASSIGNED assignments on non-terminal cases",
                        409,
                    )
    member["is_active"] = target
    touch(member)
    return success(staff_out(member), 200)


@bp.route("/cath-lab/staff/<staff_id>/assignments", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_staff_assignments(staff_id):
    member = STORE["staff"].get(staff_id)
    if member is None:
        raise ApiError(ERR_STAFF_NOT_FOUND, "No StaffMember with the given id", 404)
    items = [
        a for a in STORE["assignments"].values() if a["staff_id"] == staff_id
    ]
    items.sort(key=lambda a: a["_seq"])
    page, pg = paginate(items)
    return success([assignment_out(a) for a in page], 200, is_list=True, pagination=pg)
