"""Catalog routes: courses and rooms."""

from flask import Blueprint, request

import db
import serializers as ser
from auth import require_role, body
from envelope import success_object, success_list, paginate
from errors import invalid_request
from util import q2
from validate import (new_record, req_field, as_str, as_int, as_decimal,
                      opt_enum, opt_bool, fk_or_404, get_or_404)

bp = Blueprint("catalog", __name__)

SUBJECT_AREAS = ("ENGLISH", "MATH", "SCIENCE", "SOCIAL_STUDIES",
                 "WORLD_LANGUAGE", "PE_HEALTH", "ARTS", "ELECTIVE")
ROOM_TYPES = ("STANDARD", "LAB", "GYM", "STUDIO")
PROGRAMS = ("NONE", "IEP", "ELL", "GIFTED", "ATHLETE")


@bp.post("/scheduling/courses")
def create_course():
    require_role("Administrator")
    data = body()
    code = as_str(req_field(data, "course_code"), "course_code")
    title = as_str(req_field(data, "title"), "title")
    credits = as_decimal(req_field(data, "credits"), "credits")
    if credits < q2("0.25") or credits > q2("2.00") or (credits * 4) % 1 != 0:
        raise invalid_request("credits must be between 0.25 and 2.00 in "
                              "0.25 steps")
    subject = as_enum_val(data, "subject_area", SUBJECT_AREAS, required=True)
    room_type = opt_enum(data, "required_room_type", ROOM_TYPES, "STANDARD")
    singleton = opt_bool(data, "singleton", False)
    gb_min = as_int(req_field(data, "grade_band_min"), "grade_band_min")
    if not 9 <= gb_min <= 12:
        raise invalid_request("grade_band_min must be between 9 and 12")
    gb_max = as_int(req_field(data, "grade_band_max"), "grade_band_max")
    if not gb_min <= gb_max <= 12:
        raise invalid_request("grade_band_max must satisfy "
                              "grade_band_min <= grade_band_max <= 12")
    spe = opt_enum(data, "special_program_exclusive", PROGRAMS, "NONE")
    prereq = data.get("prerequisite_course_id")
    if prereq is not None:
        if not isinstance(prereq, str):
            raise invalid_request("prerequisite_course_id must be a string")
        fk_or_404(db.courses, prereq, "prerequisite_course_id")
    if any(c["course_code"] == code for c in db.courses.values()):
        raise invalid_request("course_code must be unique")
    c = new_record()
    c.update({
        "course_code": code, "title": title, "credits": q2(credits),
        "subject_area": subject, "required_room_type": room_type,
        "singleton": singleton, "grade_band_min": gb_min,
        "grade_band_max": gb_max, "special_program_exclusive": spe,
        "prerequisite_course_id": prereq,
    })
    db.courses[c["id"]] = c
    return success_object(ser.course(c), 201)


def as_enum_val(data, name, allowed, required=False):
    from validate import as_enum
    if required:
        return as_enum(req_field(data, name), name, allowed)
    return opt_enum(data, name, allowed, None)


@bp.get("/scheduling/courses")
def list_courses():
    require_role("Administrator", "Counselor", "Student")
    rows = list(db.courses.values())
    subject = request.args.get("subject_area")
    if subject is not None:
        rows = [c for c in rows if c["subject_area"] == subject]
    singleton = request.args.get("singleton")
    if singleton is not None:
        want = singleton.lower() == "true"
        rows = [c for c in rows if c["singleton"] == want]
    prereq = request.args.get("prerequisite_course_id")
    if prereq is not None:
        rows = [c for c in rows if c["prerequisite_course_id"] == prereq]
    page, limit, offset, total = paginate(rows, request.args)
    return success_list([ser.course(c) for c in page], limit, offset, total)


@bp.get("/scheduling/courses/<cid>")
def get_course(cid):
    require_role("Administrator", "Counselor", "Student")
    return success_object(ser.course(get_or_404(db.courses, cid)))


@bp.post("/scheduling/rooms")
def create_room():
    require_role("Administrator")
    data = body()
    number = as_str(req_field(data, "room_number"), "room_number")
    capacity = as_int(req_field(data, "capacity"), "capacity")
    if capacity < 1:
        raise invalid_request("capacity must be >= 1")
    room_type = opt_enum(data, "room_type", ROOM_TYPES, "STANDARD")
    if any(r["room_number"] == number for r in db.rooms.values()):
        raise invalid_request("room_number must be unique")
    r = new_record()
    r.update({"room_number": number, "capacity": capacity,
              "room_type": room_type})
    db.rooms[r["id"]] = r
    return success_object(ser.room(r), 201)


@bp.get("/scheduling/rooms/<rid>")
def get_room(rid):
    require_role("Administrator", "Counselor")
    return success_object(ser.room(get_or_404(db.rooms, rid)))
