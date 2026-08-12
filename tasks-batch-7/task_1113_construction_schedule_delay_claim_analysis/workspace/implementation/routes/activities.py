"""Activity endpoints (PRD §3.2)."""

from flask import Blueprint, request

from db import store
from errors import ApiError, ERR_INVALID_STATE, ERR_INVALID_REQUEST
from middleware import (
    require_roles, json_body, req_field, as_str, as_int, paginate,
    sorted_items, touch, serialize, ANY_ROLE,
)
from response import ok_object, ok_list
from util import new_id, clock_iso
from routes.common import get_project, get_version, get_activity, activities_of

bp = Blueprint("activities", __name__)


def _parse_bool_query(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    v = raw.strip().lower()
    if v in ("true", "1", "yes"):
        return True
    if v in ("false", "0", "no"):
        return False
    raise ApiError(ERR_INVALID_REQUEST, 400,
                   "Query parameter '%s' must be a boolean" % name)


@bp.route("/construction-projects/<pid>/schedule-versions/<vid>/activities",
          methods=["POST"], strict_slashes=False)
def create_activity(pid, vid):
    require_roles("ContractorScheduler")
    project, version = get_version(pid, vid)
    data = json_body()
    code = as_str(req_field(data, "activity_code"), "activity_code")
    description = as_str(req_field(data, "description"), "description")
    od = as_int(req_field(data, "original_duration_days"),
                "original_duration_days")
    if od < 1:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "original_duration_days must be at least 1")
    rd = as_int(data.get("remaining_duration_days", od),
                "remaining_duration_days")
    if rd < 0 or rd > od:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "remaining_duration_days must be between 0 and "
                       "original_duration_days")
    if version["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Activities may only be added to a DRAFT schedule")
    for a in activities_of(version["id"]):
        if a["activity_code"] == code:
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "activity_code must be unique within the "
                           "schedule version")
    now = clock_iso()
    activity = {
        "id": new_id(),
        "schedule_version_id": version["id"],
        "activity_code": code,
        "description": description,
        "original_duration_days": od,
        "remaining_duration_days": rd,
        "percent_complete": 0,
        "actual_start": None,
        "actual_finish": None,
        "early_start": None,
        "early_finish": None,
        "late_start": None,
        "late_finish": None,
        "total_float_days": None,
        "is_critical": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": store.next_seq(),
    }
    store.activities[activity["id"]] = activity
    version["total_activities"] = len(activities_of(version["id"]))
    touch(version)
    return ok_object(serialize(activity), 201)


@bp.route("/construction-projects/<pid>/schedule-versions/<vid>/activities",
          methods=["GET"], strict_slashes=False)
def list_activities(pid, vid):
    require_roles(*ANY_ROLE)
    project, version = get_version(pid, vid)
    items = activities_of(version["id"])
    crit = _parse_bool_query("is_critical")
    if crit is not None:
        items = [a for a in items if bool(a.get("is_critical")) == crit]
    items = sorted_items(items)
    page, pg = paginate(items)
    return ok_list([serialize(a) for a in page], pg)


@bp.route(
    "/construction-projects/<pid>/schedule-versions/<vid>/activities/<aid>",
    methods=["GET"], strict_slashes=False)
def get_one_activity(pid, vid, aid):
    require_roles(*ANY_ROLE)
    _, _, activity = get_activity(pid, vid, aid)
    return ok_object(serialize(activity))
