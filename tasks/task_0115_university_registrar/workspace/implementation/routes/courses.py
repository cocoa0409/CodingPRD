"""Course routes: create, get, requirement edges, and reverse-reachability lists."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import err
from middleware import authenticate, parse_pagination, require_roles
from response import ok_array, ok_object
from services import helpers as h
from services import serialize
from services.entities import new_common

bp = Blueprint("courses", __name__)

ALL_ROLES = ("Registrar", "Advisor", "Student", "Bursar")
REQUIREMENT_TYPES = {"PREREQUISITE", "COREQUISITE"}


@bp.post("/courses")
def create_course():
    authenticate()
    require_roles("Registrar")
    body = h.get_json_body()

    code = h.require_string(body, "code")
    title = h.require_string(body, "title")
    credit_hours = h.require_int(body, "credit_hours")
    if credit_hours < 0:
        raise err("ERR_VALIDATION", "credit_hours must be >= 0")
    program_id = h.require_string(body, "program_id")
    h.get_program(program_id)

    rec = new_common("Course")
    rec.update({
        "code": code,
        "title": title,
        "credit_hours": credit_hours,
        "program_id": program_id,
        "is_active": True,
    })
    db.courses[rec["id"]] = rec
    return ok_object(serialize.course(rec), 201)


@bp.get("/courses/<course_id>")
def get_course(course_id):
    authenticate()
    require_roles(*ALL_ROLES)
    rec = h.get_course(course_id)
    return ok_object(serialize.course(rec), 200)


@bp.post("/courses/<course_id>/requirements")
def create_requirement(course_id):
    authenticate()
    require_roles("Registrar")
    body = h.get_json_body()

    course = h.get_course(course_id)
    required_course_id = h.require_string(body, "required_course_id")
    requirement_type = h.require_enum(body, "requirement_type", REQUIREMENT_TYPES)
    min_grade_points = h.optional_number(body, "min_grade_points", 1.0)
    h.get_course(required_course_id)

    rec = new_common("CourseRequirement")  # immutable: only id + created_at
    rec.update({
        "course_id": course["id"],
        "required_course_id": required_course_id,
        "requirement_type": requirement_type,
        "min_grade_points": min_grade_points,
    })
    db.course_requirements[rec["id"]] = rec
    return ok_object(serialize.course_requirement(rec), 201)


@bp.get("/courses/<course_id>/requirements")
def list_requirements(course_id):
    authenticate()
    require_roles(*ALL_ROLES)
    limit, offset = parse_pagination()
    h.get_course(course_id)

    required_course_id = request.args.get("required_course_id")
    recs = [
        r for r in db.course_requirements.values()
        if r["course_id"] == course_id
        and (required_course_id is None or r["required_course_id"] == required_course_id)
    ]
    recs = h.order_by_created(recs)
    page, total = h.paginate(recs, limit, offset)
    return ok_array([serialize.course_requirement(r) for r in page], limit, offset, total, 200)


@bp.get("/courses/<course_id>/sections")
def list_course_sections(course_id):
    authenticate()
    require_roles(*ALL_ROLES)
    limit, offset = parse_pagination()
    h.get_course(course_id)

    term_id = request.args.get("term_id")
    recs = [
        s for s in db.sections.values()
        if s["course_id"] == course_id
        and (term_id is None or s["term_id"] == term_id)
    ]
    recs = h.order_by_created(recs)
    page, total = h.paginate(recs, limit, offset)
    return ok_array([serialize.section(s) for s in page], limit, offset, total, 200)
