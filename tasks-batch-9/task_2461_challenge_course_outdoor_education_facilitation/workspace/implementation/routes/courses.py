"""Course sites, the daily opening checkpoint and the per-course sub-lists."""
from flask import Blueprint

from db import store, base_row
from middleware import authorize, ALL_ROLES
from response import object_response, created_response, list_response, pagination, paginate
from validation import body, req_str, req_int
from services import derive, serialize, checkpoint
from services.lookup import get_course, apply_filters

bp = Blueprint("courses", __name__)

PREFIX = "/challenge-course"


@bp.post(PREFIX + "/courses")
def create_course():
    # Course registration is reachable before any staff record exists, so identity
    # resolution is not applied (PRD 2.1 / 2.12 step 3).
    authorize(["ProgramDirector"], identity=False)
    payload = body()

    course_name = req_str(payload, "course_name")
    ems_response_minutes = req_int(payload, "ems_response_minutes", minimum=1, maximum=240)
    ems_access_note = req_str(payload, "ems_access_note")

    row = base_row()
    row.update({
        "course_name": course_name,
        "ems_response_minutes": ems_response_minutes,
        "ems_access_note": ems_access_note,
        "posture": "OPEN",
        "posture_reason": "NONE",
        "lightning_hold_until": None,
        "daily_open_index": 0,
        "last_daily_open_date": None,
    })
    store.courses[row["id"]] = row
    return created_response(serialize.course(row))


@bp.get(PREFIX + "/courses/<course_id>")
def read_course(course_id):
    authorize(ALL_ROLES)
    course = get_course(course_id)
    return object_response(serialize.course(course))


@bp.post(PREFIX + "/courses/<course_id>/daily-open")
def daily_open(course_id):
    authorize(["ProgramDirector"])
    body()
    course = get_course(course_id)
    checkpoint.run_daily_open(course)
    return object_response(serialize.course(course))


@bp.get(PREFIX + "/courses/<course_id>/facilitators")
def list_course_facilitators(course_id):
    authorize(["ProgramDirector", "SafetyOfficer"])
    limit, offset = pagination()
    course = get_course(course_id)
    rows = derive.facilitators_of_course(course["id"])
    rows = apply_filters(rows, {"cert_status": ("str", "cert_status")})
    window, total = paginate(rows, limit, offset)
    return list_response([serialize.facilitator(r) for r in window], limit, offset, total)


@bp.get(PREFIX + "/courses/<course_id>/weather-observations")
def list_course_observations(course_id):
    authorize(["ProgramDirector", "SafetyOfficer", "Facilitator"])
    limit, offset = pagination()
    course = get_course(course_id)
    rows = derive.observations_of_course(course["id"])
    # The one exception to the default ordering: newest first (PRD 2.3).
    rows = list(reversed(rows))
    window, total = paginate(rows, limit, offset)
    return list_response([serialize.weather_observation(r) for r in window], limit, offset, total)
