"""Instructor routes: create, get, reverse-reachability sections list."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import err
from middleware import authenticate, parse_pagination, require_roles
from response import ok_array, ok_object
from services import helpers as h
from services import serialize
from services.entities import new_common

bp = Blueprint("instructors", __name__)

ALL_ROLES = ("Registrar", "Advisor", "Student", "Bursar")


@bp.post("/instructors")
def create_instructor():
    authenticate()
    require_roles("Registrar")
    body = h.get_json_body()

    full_name = h.require_string(body, "full_name")
    email = h.require_string(body, "email")
    gap_minutes = h.optional_int(body, "gap_minutes", 0)
    if gap_minutes < 0:
        raise err("ERR_VALIDATION", "gap_minutes must be >= 0")

    rec = new_common("Instructor")
    rec.update({
        "full_name": full_name,
        "email": email,
        "gap_minutes": gap_minutes,
    })
    db.instructors[rec["id"]] = rec
    return ok_object(serialize.instructor(rec), 201)


@bp.get("/instructors/<instructor_id>")
def get_instructor(instructor_id):
    authenticate()
    require_roles(*ALL_ROLES)
    rec = h.get_instructor(instructor_id)
    return ok_object(serialize.instructor(rec), 200)


@bp.get("/instructors/<instructor_id>/sections")
def list_instructor_sections(instructor_id):
    authenticate()
    require_roles(*ALL_ROLES)
    limit, offset = parse_pagination()
    h.get_instructor(instructor_id)

    term_id = request.args.get("term_id")
    recs = [
        s for s in db.sections.values()
        if s["instructor_id"] == instructor_id
        and (term_id is None or s["term_id"] == term_id)
    ]
    recs = h.order_by_created(recs)
    page, total = h.paginate(recs, limit, offset)
    return ok_array([serialize.section(s) for s in page], limit, offset, total, 200)
