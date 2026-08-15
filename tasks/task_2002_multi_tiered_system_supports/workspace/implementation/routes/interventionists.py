"""Interventionist endpoints (incl. flat aliases)."""

from flask import Blueprint

from db import DB
from errors import err, ERR_INTERVENTIONIST_NOT_FOUND, ERR_SCHOOL_NOT_FOUND
from middleware import (
    require_role, ALL_ROLES, get_json_body, check_unknown_fields, require_fields,
    req_string, req_int, req_enum_array, base_fields, paginate, sort_created,
)
from response import success_object, success_list
from services import (
    SUBJECTS, serialize_interventionist, serialize_plan,
    resolve_school, resolve_interventionist,
)

bp = Blueprint("interventionists", __name__)


@bp.post("/districts/<districtId>/schools/<schoolId>/interventionists")
def create_interventionist(districtId, schoolId):
    require_role("DistrictCoordinator", "SchoolRegistrar")
    body = get_json_body()
    check_unknown_fields(body, {"full_name", "weekly_minute_capacity", "subjects"})
    require_fields(body, ["full_name", "weekly_minute_capacity", "subjects"])
    full_name = req_string(body, "full_name")
    capacity = req_int(body, "weekly_minute_capacity")
    subjects = req_enum_array(body, "subjects", SUBJECTS)
    resolve_school(districtId, schoolId)
    i = base_fields()
    i.update({
        "school_id": schoolId,
        "full_name": full_name,
        "weekly_minute_capacity": capacity,
        "committed_minutes_per_week": 0,
        "subjects": subjects,
    })
    DB.interventionists[i["id"]] = i
    return success_object(serialize_interventionist(i), status=201)


def _list_interventionists(schoolId):
    items = sort_created(
        i for i in DB.interventionists.values() if i["school_id"] == schoolId
    )
    page, limit, offset, total = paginate(items)
    return success_list([serialize_interventionist(i) for i in page], limit, offset, total)


@bp.get("/districts/<districtId>/schools/<schoolId>/interventionists")
def list_interventionists(districtId, schoolId):
    require_role(*ALL_ROLES)
    resolve_school(districtId, schoolId)
    return _list_interventionists(schoolId)


@bp.get("/districts/<districtId>/schools/<schoolId>/interventionists/<interventionistId>")
def get_interventionist(districtId, schoolId, interventionistId):
    require_role(*ALL_ROLES)
    i = resolve_interventionist(districtId, schoolId, interventionistId)
    return success_object(serialize_interventionist(i))


@bp.get("/interventionists/<interventionistId>")
def get_interventionist_flat(interventionistId):
    require_role(*ALL_ROLES)
    i = DB.interventionists.get(interventionistId)
    if i is None:
        raise err(ERR_INTERVENTIONIST_NOT_FOUND, 404, "interventionistId does not exist")
    return success_object(serialize_interventionist(i))


@bp.get("/schools/<id>/interventionists")
def list_interventionists_flat(id):
    require_role(*ALL_ROLES)
    s = DB.schools.get(id)
    if s is None:
        raise err(ERR_SCHOOL_NOT_FOUND, 404, "school id does not exist")
    return _list_interventionists(id)


@bp.get("/interventionists/<id>/plans")
def list_plans_for_interventionist(id):
    require_role(*ALL_ROLES)
    i = DB.interventionists.get(id)
    if i is None:
        raise err(ERR_INTERVENTIONIST_NOT_FOUND, 404, "interventionist id does not exist")
    items = sort_created(
        p for p in DB.plans.values() if p["interventionist_id"] == id
    )
    page, limit, offset, total = paginate(items)
    return success_list([serialize_plan(p) for p in page], limit, offset, total)
