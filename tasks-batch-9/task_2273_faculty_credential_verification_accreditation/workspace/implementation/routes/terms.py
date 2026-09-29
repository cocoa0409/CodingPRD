"""Term endpoints and the term lifecycle (PRD 3.1)."""

from flask import Blueprint

import db
import guards
import middleware
import response
import serialize
import util
import validate
from constants import (
    READ_ROLES, REGISTRAR_OFFICER, SYSTEM_ADMIN, TERM_STATUSES,
)
from db import store, touch
from errors import ApiError
from routes.common import list_response, match
from services import domain, lookup

bp = Blueprint("terms", __name__)

TERM_TRANSITIONS = {
    ("PLANNING", "OPEN"),
    ("OPEN", "ROSTER_LOCKED"),
    ("ROSTER_LOCKED", "CLOSED"),
    ("ROSTER_LOCKED", "OPEN"),
}


@bp.route("/terms", methods=["POST"])
def create_term():
    middleware.require_role(SYSTEM_ADMIN, REGISTRAR_OFFICER)
    payload = validate.body()

    code = validate.req_str(payload, "code")
    start_date = validate.req_date(payload, "start_date")
    end_date = validate.req_date(payload, "end_date")
    census_date = validate.req_date(payload, "census_date")

    for row in db.ordered(store.terms):
        if row["code"] == code:
            raise ApiError("ERR_DUPLICATE_TERM_CODE")

    if not (start_date <= census_date <= end_date):
        raise ApiError("ERR_INVALID_WINDOW",
                       "start_date must be at or before census_date, which must be "
                       "at or before end_date.")

    row = db.new_row(
        code=code,
        start_date=util.date_to_str(start_date),
        end_date=util.date_to_str(end_date),
        census_date=util.date_to_str(census_date),
        status="PLANNING",
    )
    store.terms[row["id"]] = row
    return response.created(serialize.term(row))


@bp.route("/terms/<term_id>", methods=["GET"])
def read_term(term_id):
    middleware.require_role(*READ_ROLES)
    return response.ok(serialize.term(lookup.term(term_id)))


@bp.route("/terms", methods=["GET"])
def list_terms():
    middleware.require_role(*READ_ROLES)
    status = validate.q_enum("status", TERM_STATUSES)
    code = validate.q_str("code")
    rows = [r for r in db.ordered(store.terms)
            if match(r, "status", status) and match(r, "code", code)]
    return list_response(rows, serialize.term)


@bp.route("/terms/<term_id>/status", methods=["POST"])
def term_status(term_id):
    middleware.require_role(REGISTRAR_OFFICER)
    payload = validate.body()
    to_status = validate.req_enum(payload, "to_status", TERM_STATUSES)

    term = lookup.term(term_id)
    current = term["status"]

    if (current, to_status) not in TERM_TRANSITIONS:
        guards.invalid_state("A term in %s may not move to %s." % (current, to_status))

    term_rosters = [r for r in db.ordered(store.rosters) if r["term_id"] == term_id]

    if current == "ROSTER_LOCKED" and to_status == "OPEN":
        if any(r["status"] == "CERTIFIED" for r in term_rosters):
            raise ApiError("ERR_ROSTER_CERTIFIED")

    if to_status == "CLOSED":
        for roster in term_rosters:
            if roster["status"] not in ("CERTIFIED", "SUPERSEDED"):
                raise ApiError("ERR_ROSTER_NOT_READY",
                               "Every roster of the term must be CERTIFIED or "
                               "SUPERSEDED before the term may close.")

    term["status"] = to_status
    touch(term)

    if to_status == "CLOSED":
        faculty_ids = []
        for assignment in db.ordered(store.course_assignments):
            section = store.course_sections.get(assignment["course_section_id"])
            if not section or section["term_id"] != term_id:
                continue
            if assignment["faculty_member_id"] not in faculty_ids:
                faculty_ids.append(assignment["faculty_member_id"])
        for faculty_id in faculty_ids:
            faculty = store.faculty_members.get(faculty_id)
            if faculty is not None:
                domain.sync_faculty_load(faculty)

    return response.ok(serialize.term(term))
