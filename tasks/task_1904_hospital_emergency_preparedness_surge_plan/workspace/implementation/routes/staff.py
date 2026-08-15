"""Staff roster endpoints."""

from flask import Blueprint, request

from db import store
from domain import COMMAND_ROLES, DEPARTMENTS, get_or_404, list_response, ser_staff
from envelope import success
from errors import ApiError
from security import ALL_ROLES, authorize
from util import (bool_filter_param, field_bool, field_enum, field_enum_list,
                  field_int, field_str, new_entity, require_body, touch)

bp = Blueprint("staff", __name__)


@bp.post("/staff-members")
@authorize(["HospitalAdministrator"])
def create_staff():
    body = require_body()
    full_name = field_str(body, "full_name", required=True)
    badge_number = field_str(body, "badge_number", required=True)
    department = field_enum(body, "department", DEPARTMENTS, required=True)
    role_qualifications = field_enum_list(body, "role_qualifications", COMMAND_ROLES,
                                          required=True)
    is_active = field_bool(body, "is_active", default=True)
    callback_eligible = field_bool(body, "callback_eligible", default=False)
    seniority = field_int(body, "callback_seniority_score", default=0)

    if any(s["badge_number"] == badge_number for s in store["staff_members"].values()):
        raise ApiError("ERR_BADGE_NUMBER_EXISTS", 409,
                       "badge_number %s is already in use" % badge_number)

    member = new_entity()
    member.update({
        "full_name": full_name,
        "badge_number": badge_number,
        "department": department,
        "role_qualifications": role_qualifications,
        "is_active": is_active,
        "callback_eligible": callback_eligible,
        "callback_seniority_score": seniority,
    })
    store["staff_members"][member["id"]] = member
    return success(ser_staff(member), "object", 201)


@bp.get("/staff-members")
@authorize(ALL_ROLES)
def list_staff():
    department = request.args.get("department")
    is_active = bool_filter_param("is_active")
    callback_eligible = bool_filter_param("callback_eligible")

    def predicate(s):
        if department is not None and s["department"] != department:
            return False
        if is_active is not None and s["is_active"] != is_active:
            return False
        if callback_eligible is not None and s["callback_eligible"] != callback_eligible:
            return False
        return True

    return list_response("staff_members", ser_staff, predicate)


@bp.get("/staff-members/<member_id>")
@authorize(ALL_ROLES)
def get_staff(member_id):
    return success(ser_staff(get_or_404("staff_members", member_id)), "object", 200)


@bp.patch("/staff-members/<member_id>")
@authorize(["HospitalAdministrator"])
def patch_staff(member_id):
    member = get_or_404("staff_members", member_id)
    body = require_body()

    department = field_enum(body, "department", DEPARTMENTS)
    role_qualifications = field_enum_list(body, "role_qualifications", COMMAND_ROLES)
    is_active = field_bool(body, "is_active")
    callback_eligible = field_bool(body, "callback_eligible")
    seniority = field_int(body, "callback_seniority_score")

    if department is not None:
        member["department"] = department
    if role_qualifications is not None:
        member["role_qualifications"] = role_qualifications
    if is_active is not None:
        member["is_active"] = is_active
    if callback_eligible is not None:
        member["callback_eligible"] = callback_eligible
    if seniority is not None:
        member["callback_seniority_score"] = seniority
    touch(member)
    return success(ser_staff(member), "object", 200)
