"""Program routes: create, get, and reverse-reachability lists (students, courses)."""
from __future__ import annotations

from flask import Blueprint

import db
from middleware import authenticate, parse_pagination, require_roles
from response import ok_array, ok_object
from services import helpers as h
from services import serialize
from services.entities import new_common

bp = Blueprint("programs", __name__)

ALL_ROLES = ("Registrar", "Advisor", "Student", "Bursar")


@bp.post("/programs")
def create_program():
    authenticate()
    require_roles("Registrar")
    body = h.get_json_body()

    name = h.require_string(body, "name")
    required_credit_hours = h.require_int(body, "required_credit_hours")
    min_gpa = h.optional_number(body, "min_gpa", 2.0)

    rec = new_common("Program")  # immutable: only id + created_at
    rec.update({
        "name": name,
        "required_credit_hours": required_credit_hours,
        "min_gpa": min_gpa,
    })
    db.programs[rec["id"]] = rec
    return ok_object(serialize.program(rec), 201)


@bp.get("/programs/<program_id>")
def get_program(program_id):
    authenticate()
    require_roles(*ALL_ROLES)
    rec = h.get_program(program_id)
    return ok_object(serialize.program(rec), 200)


@bp.get("/programs/<program_id>/students")
def list_program_students(program_id):
    authenticate()
    require_roles("Registrar", "Advisor")
    limit, offset = parse_pagination()
    h.get_program(program_id)

    recs = [s for s in db.students.values() if s["program_id"] == program_id]
    recs = h.order_by_created(recs)
    page, total = h.paginate(recs, limit, offset)
    return ok_array([serialize.student(s) for s in page], limit, offset, total, 200)


@bp.get("/programs/<program_id>/courses")
def list_program_courses(program_id):
    authenticate()
    require_roles(*ALL_ROLES)
    limit, offset = parse_pagination()
    h.get_program(program_id)

    recs = [c for c in db.courses.values() if c["program_id"] == program_id]
    recs = h.order_by_created(recs)
    page, total = h.paginate(recs, limit, offset)
    return ok_array([serialize.course(c) for c in page], limit, offset, total, 200)
