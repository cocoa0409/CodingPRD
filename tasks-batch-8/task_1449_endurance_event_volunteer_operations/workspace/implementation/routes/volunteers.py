"""Volunteer endpoints: registration, profile PATCH (OCC), screen, reinstate, recognition."""
from flask import Blueprint, request

import errors
from db import store
from middleware import require_roles
from response import success_object, success_list
from util import (
    get_body, require_field, optional_field, as_string, as_int, as_bool, as_enum,
    parse_date, compute_age_years, parse_dt,
)
from services.core import (
    make_record, touch, paginate, sort_by_created, serialize_volunteer,
    get_event_or_404, get_group_or_404, get_volunteer_or_404,
)
from services.credit import recognition_summary

bp = Blueprint("volunteers", __name__)
ANY = ("Anonymous", "Volunteer", "Captain", "GroupLeader", "VolunteerCoordinator", "EventDirector")

SKILL_TAGS = {"MEDICAL", "BIKE_MARSHAL", "TIMING_TECH", "COURSE_MARSHAL"}


def _parse_skill_tags(value):
    if value is None:
        return []
    if not isinstance(value, list):
        raise errors.invalid_request("skill_tags must be an array.")
    out = []
    for v in value:
        out.append(as_enum(v, "skill_tags", SKILL_TAGS))
    return out


@bp.post("/volunteer-ops/volunteers")
def create_volunteer():
    require_roles("Anonymous", "VolunteerCoordinator")
    body = get_body()
    event_id = as_string(require_field(body, "event_id"), "event_id")
    ev = get_event_or_404(event_id)
    full_name = as_string(require_field(body, "full_name"), "full_name")
    dob_raw = as_string(require_field(body, "date_of_birth"), "date_of_birth")
    dob = parse_date(dob_raw)
    skill_tags = _parse_skill_tags(optional_field(body, "skill_tags", []))
    group_id = optional_field(body, "group_id", None)
    if group_id is not None:
        group_id = as_string(group_id, "group_id")
        grp = get_group_or_404(group_id)
        if grp["status"] != "ACTIVE":
            raise errors.group_suspended()
    float_opt_in = optional_field(body, "float_opt_in", False)
    float_opt_in = as_bool(float_opt_in, "float_opt_in")
    is_returning = optional_field(body, "is_returning", False)
    is_returning = as_bool(is_returning, "is_returning")

    age = compute_age_years(dob, parse_dt(ev["event_start_at"]))
    rec = make_record({
        "event_id": event_id,
        "group_id": group_id,
        "full_name": full_name,
        "date_of_birth": dob_raw,
        "skill_tags": skill_tags,
        "float_opt_in": float_opt_in,
        "is_returning": is_returning,
        "status": "REGISTERED",
        "age_years_on_event": age,
        "no_show_strikes": 0,
    })
    store.volunteers[rec["id"]] = rec
    return success_object(serialize_volunteer(rec), status=201)


@bp.get("/volunteer-ops/volunteers")
def list_volunteers():
    require_roles(*ANY)
    event_id = request.args.get("event_id")
    group_id = request.args.get("group_id")
    items = [
        v for v in store.volunteers.values()
        if (event_id is None or v["event_id"] == event_id)
        and (group_id is None or v.get("group_id") == group_id)
    ]
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items, request.args)
    return success_list([serialize_volunteer(v) for v in page], limit, offset, total)


@bp.get("/volunteer-ops/volunteers/<volunteerId>")
def get_volunteer(volunteerId):
    require_roles(*ANY)
    vol = get_volunteer_or_404(volunteerId)
    return success_object(serialize_volunteer(vol))


@bp.patch("/volunteer-ops/volunteers/<volunteerId>")
def update_volunteer(volunteerId):
    user_id, role = require_roles("Volunteer", "VolunteerCoordinator")
    vol = get_volunteer_or_404(volunteerId)
    body = get_body()
    expected = require_field(body, "expected_volunteer_version")
    expected = as_int(expected, "expected_volunteer_version")
    if expected != vol["version"]:
        raise errors.stale_version()
    if "skill_tags" in body and body["skill_tags"] is not None:
        vol["skill_tags"] = _parse_skill_tags(body["skill_tags"])
    if "group_id" in body:
        gid = body["group_id"]
        if gid is not None:
            gid = as_string(gid, "group_id")
            grp = get_group_or_404(gid)
            if grp["status"] != "ACTIVE":
                raise errors.group_suspended()
        vol["group_id"] = gid
    if "float_opt_in" in body and body["float_opt_in"] is not None:
        vol["float_opt_in"] = as_bool(body["float_opt_in"], "float_opt_in")
    if "is_returning" in body and body["is_returning"] is not None:
        vol["is_returning"] = as_bool(body["is_returning"], "is_returning")
    # ownership: Volunteer may only update own record
    if role == "Volunteer" and user_id != vol["id"]:
        raise errors.not_resource_owner()
    touch(vol)
    return success_object(serialize_volunteer(vol))


@bp.post("/volunteer-ops/volunteers/<volunteerId>/screen")
def screen_volunteer(volunteerId):
    require_roles("VolunteerCoordinator")
    vol = get_volunteer_or_404(volunteerId)
    if vol["status"] != "REGISTERED":
        raise errors.volunteer_not_screenable()
    if vol["age_years_on_event"] < 14:
        raise errors.min_age_not_met()
    vol["status"] = "ELIGIBLE"
    touch(vol)
    return success_object(serialize_volunteer(vol))


@bp.post("/volunteer-ops/volunteers/<volunteerId>/reinstate")
def reinstate_volunteer(volunteerId):
    require_roles("VolunteerCoordinator")
    vol = get_volunteer_or_404(volunteerId)
    if vol["status"] != "SUSPENDED":
        raise errors.volunteer_not_suspended()
    vol["status"] = "ELIGIBLE"
    vol["no_show_strikes"] = 0
    touch(vol)
    return success_object(serialize_volunteer(vol))


@bp.get("/volunteer-ops/volunteers/<volunteerId>/recognition-summary")
def get_recognition_summary(volunteerId):
    require_roles(*ANY)
    vol = get_volunteer_or_404(volunteerId)
    return success_object(recognition_summary(vol))
