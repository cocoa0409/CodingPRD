"""Faculty member endpoints, separation and cascade C (PRD 3.2, 3.7)."""

from flask import Blueprint

import db
import guards
import middleware
import response
import serialize
import validate
from constants import (
    ALL_ROLES, APPOINTMENT_STATUSES, DOSSIER_STATUSES, EMPLOYMENT_CLASSES,
    INSTRUCTOR, PROGRAM_DEAN, READ_ROLES, REGISTRAR_OFFICER,
)
from db import store, touch
from errors import ApiError
from routes.common import list_response, match
from services import domain, lookup

bp = Blueprint("faculty", __name__)


def _require_unique_email(email, skip_id=None):
    for row in db.ordered(store.faculty_members):
        if row["id"] == skip_id:
            continue
        if row["email"] == email:
            raise ApiError("ERR_DUPLICATE_FACULTY_EMAIL")


@bp.route("/faculty-members", methods=["POST"])
def create_faculty():
    middleware.require_role(REGISTRAR_OFFICER)
    payload = validate.body()

    full_name = validate.req_str(payload, "full_name")
    email = validate.req_str(payload, "email")
    employment_class = validate.req_enum(payload, "employment_class", EMPLOYMENT_CLASSES)
    home_program_id = validate.req_str(payload, "home_program_id")

    lookup.program(home_program_id)
    _require_unique_email(email)

    row = db.new_row(
        full_name=full_name,
        email=email,
        employment_class=employment_class,
        home_program_id=home_program_id,
        dossier_status="INCOMPLETE",
        appointment_status="PROSPECT",
        deficiency_codes=[],
        highest_verified_degree_level=None,
        assigned_credit_hours=0,
        pd_hours_current_cycle=0,
        pd_compliant=False,
    )
    store.faculty_members[row["id"]] = row
    return response.created(serialize.faculty(row))


@bp.route("/faculty-members/<faculty_member_id>", methods=["POST"])
def update_faculty(faculty_member_id):
    middleware.require_role(REGISTRAR_OFFICER)
    payload = validate.body()

    full_name = validate.opt_str(payload, "full_name", allow_empty=False)
    email = validate.opt_str(payload, "email", allow_empty=False)
    employment_class = validate.opt_enum(payload, "employment_class", EMPLOYMENT_CLASSES)
    home_program_id = validate.opt_str(payload, "home_program_id", allow_empty=False)

    row = lookup.faculty(faculty_member_id)

    if home_program_id is not None:
        lookup.program(home_program_id)
    if email is not None:
        _require_unique_email(email, skip_id=row["id"])

    if full_name is not None:
        row["full_name"] = full_name
    if email is not None:
        row["email"] = email
    if employment_class is not None:
        row["employment_class"] = employment_class
    if home_program_id is not None:
        row["home_program_id"] = home_program_id

    domain.refresh_pd(row)
    touch(row)
    return response.ok(serialize.faculty(row))


@bp.route("/faculty-members/<faculty_member_id>", methods=["GET"])
def read_faculty(faculty_member_id):
    middleware.require_role(*ALL_ROLES)
    middleware.require_instructor_owns(faculty_member_id)
    row = lookup.faculty(faculty_member_id)
    middleware.require_dean_owns(row.get("home_program_id"))
    return response.ok(serialize.faculty(row))


@bp.route("/faculty-members", methods=["GET"])
def list_faculty():
    middleware.require_role(*READ_ROLES)
    home_program_id = validate.q_str("home_program_id")
    employment_class = validate.q_enum("employment_class", EMPLOYMENT_CLASSES)
    dossier_status = validate.q_enum("dossier_status", DOSSIER_STATUSES)
    appointment_status = validate.q_enum("appointment_status", APPOINTMENT_STATUSES)
    pd_compliant = validate.q_bool("pd_compliant")

    rows = []
    for row in db.ordered(store.faculty_members):
        if not (match(row, "home_program_id", home_program_id)
                and match(row, "employment_class", employment_class)
                and match(row, "dossier_status", dossier_status)
                and match(row, "appointment_status", appointment_status)):
            continue
        if pd_compliant is not None:
            current = domain.refresh_pd(row).get("pd_compliant")
            if bool(current) is not pd_compliant:
                continue
        rows.append(row)
    return list_response(rows, serialize.faculty)


@bp.route("/faculty-members/<faculty_member_id>/separation", methods=["POST"])
def separate_faculty(faculty_member_id):
    middleware.require_role(REGISTRAR_OFFICER)
    payload = validate.body()
    validate.opt_str(payload, "reason")

    faculty = lookup.faculty(faculty_member_id)
    current = faculty["appointment_status"]

    if current not in ("PROSPECT", "CREDENTIALED_ELIGIBLE", "CONTRACTED"):
        guards.invalid_state("A faculty member in %s may not be separated." % current)

    if current in ("CREDENTIALED_ELIGIBLE", "CONTRACTED"):
        for assignment in lookup.assignments_of_faculty(faculty_member_id):
            if assignment["status"] not in domain.ACTIVE_ASSIGNMENT_STATUSES:
                continue
            section = store.course_sections.get(assignment["course_section_id"])
            if not section:
                continue
            if lookup.certified_roster(section["program_id"], section["term_id"]):
                raise ApiError("ERR_ROSTER_CERTIFIED")

    faculty["appointment_status"] = "SEPARATED"
    touch(faculty)

    if current in ("CREDENTIALED_ELIGIBLE", "CONTRACTED"):
        domain.cascade_c(faculty)

    return response.ok(serialize.faculty(faculty))
