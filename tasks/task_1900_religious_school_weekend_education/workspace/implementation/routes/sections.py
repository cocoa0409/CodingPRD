"""Section endpoints."""

from flask import Blueprint, request

from db import store
from middleware import require_roles
from response import success_object, success_list, parse_pagination
from errors import (
    ApiError, invalid_request, invalid_state, not_found,
    ERR_TEACHER_NOT_HIRED, ERR_ROOM_TIME_CONFLICT, ERR_CAPACITY_BELOW_ENROLLED,
)
from services.core import (
    base_record, touch, public, get_year, get_section, parse_time,
    serialize_section,
)

bp = Blueprint("sections", __name__)


@bp.route("/school/school-years/<year_id>/sections", methods=["POST"])
def create_section(year_id):
    require_roles(["SchoolAdmin"])
    year = get_year(year_id)
    body = request.get_json(silent=True) or {}

    grade = body.get("grade")
    hebrew_level = body.get("hebrew_level")
    capacity = body.get("capacity")
    room = body.get("room")
    day_of_week = body.get("day_of_week")
    start_time = body.get("start_time")
    end_time = body.get("end_time")
    teacher_id = body.get("teacher_id")

    if grade not in ("K", "G1", "G2", "G3", "G4", "G5", "G6", "G7"):
        raise invalid_request("grade must be one of K, G1..G7")
    if hebrew_level not in ("BEGINNER", "INTERMEDIATE", "ADVANCED"):
        raise invalid_request("hebrew_level must be BEGINNER, INTERMEDIATE, or ADVANCED")
    if isinstance(capacity, bool) or not isinstance(capacity, int) or capacity < 1:
        raise invalid_request("capacity must be an integer >= 1")
    if not isinstance(room, str) or not room:
        raise invalid_request("room is required")
    if day_of_week not in ("SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"):
        raise invalid_request("day_of_week invalid")
    st = parse_time(start_time, "start_time")
    et = parse_time(end_time, "end_time")
    if not st < et:
        raise invalid_request("start_time must be strictly earlier than end_time")

    if teacher_id is not None:
        if not isinstance(teacher_id, str):
            raise invalid_request("teacher_id must be a string")
        teacher = store.teachers.get(teacher_id)
        if teacher is None:
            raise not_found("Teacher not found")
        if teacher["status"] != "HIRED":
            raise ApiError(ERR_TEACHER_NOT_HIRED, 422, "Assigned teacher is not HIRED")

    # room/day/time half-open overlap check within same year
    for sec in store.sections.values():
        if sec["school_year_id"] != year_id:
            continue
        if sec["room"] != room or sec["day_of_week"] != day_of_week:
            continue
        s2 = parse_time(sec["start_time"])
        e2 = parse_time(sec["end_time"])
        # half-open [st, et) vs [s2, e2)
        if st < e2 and s2 < et:
            raise ApiError(ERR_ROOM_TIME_CONFLICT, 409, "Room/time conflict")

    rec = base_record()
    rec.update({
        "school_year_id": year_id,
        "teacher_id": teacher_id,
        "grade": grade,
        "hebrew_level": hebrew_level,
        "capacity": capacity,
        "room": room,
        "day_of_week": day_of_week,
        "start_time": start_time,
        "end_time": end_time,
        "enrolled_count": 0,
        "status": "OPEN",
    })
    store.sections[rec["id"]] = rec
    return success_object(serialize_section(rec), status=201)


@bp.route("/school/sections/<section_id>", methods=["GET"])
def get_section_endpoint(section_id):
    require_roles(["SchoolAdmin", "AssistanceOfficer", "Teacher", "Parent"])
    sec = get_section(section_id)
    return success_object(serialize_section(sec))


@bp.route("/school/sections", methods=["GET"])
def list_sections():
    require_roles(["SchoolAdmin", "AssistanceOfficer", "Teacher", "Parent"])
    limit, offset = parse_pagination(request.args)
    school_year_id = request.args.get("school_year_id")
    teacher_id = request.args.get("teacher_id")
    status = request.args.get("status")
    items = list(store.sections.values())
    if school_year_id is not None:
        items = [s for s in items if s["school_year_id"] == school_year_id]
    if teacher_id is not None:
        items = [s for s in items if s.get("teacher_id") == teacher_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    items.sort(key=lambda s: (s["created_at"], s["_seq"]))
    total = len(items)
    page = items[offset: offset + limit]
    return success_list([serialize_section(s) for s in page], limit, offset, total)


@bp.route("/school/sections/<section_id>", methods=["PATCH"])
def patch_section(section_id):
    require_roles(["SchoolAdmin"])
    sec = get_section(section_id)
    body = request.get_json(silent=True) or {}
    teacher_id = body.get("teacher_id", "__UNSET__")
    capacity = body.get("capacity", "__UNSET__")

    if teacher_id != "__UNSET__" and teacher_id is not None and not isinstance(teacher_id, str):
        raise invalid_request("teacher_id must be a string or null")
    if capacity != "__UNSET__":
        if isinstance(capacity, bool) or not isinstance(capacity, int) or capacity < 1:
            raise invalid_request("capacity must be an integer >= 1")

    if sec["status"] == "CLOSED":
        raise invalid_state("Cannot patch a CLOSED section")

    if teacher_id != "__UNSET__":
        if teacher_id is not None:
            teacher = store.teachers.get(teacher_id)
            if teacher is None:
                raise not_found("Teacher not found")
            if teacher["status"] != "HIRED":
                raise ApiError(ERR_TEACHER_NOT_HIRED, 422, "Assigned teacher is not HIRED")
        sec["teacher_id"] = teacher_id

    if capacity != "__UNSET__":
        if capacity < sec["enrolled_count"]:
            raise ApiError(ERR_CAPACITY_BELOW_ENROLLED, 409, "capacity below enrolled_count")
        sec["capacity"] = capacity
        # auto status transitions on capacity change
        if sec["status"] == "OPEN" and sec["enrolled_count"] >= capacity:
            sec["status"] = "FULL"
        elif sec["status"] == "FULL" and sec["enrolled_count"] < capacity:
            sec["status"] = "OPEN"

    touch(sec)
    return success_object(serialize_section(sec))
