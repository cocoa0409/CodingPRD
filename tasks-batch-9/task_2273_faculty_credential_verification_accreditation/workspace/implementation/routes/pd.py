"""Professional development records (PRD 3.8)."""

from flask import Blueprint

import clock
import db
import guards
import middleware
import response
import serialize
import util
import validate
from constants import (
    ALL_ROLES, CREDENTIAL_ANALYST, INSTRUCTOR, PD_ACTIVITY_TYPES, PD_STATUSES,
    READ_ROLES, REGISTRAR_OFFICER,
)
from db import store, touch
from errors import ApiError
from routes.common import list_response, match
from services import calc, domain, lookup

bp = Blueprint("pd", __name__)


@bp.route("/pd-records", methods=["POST"])
def create_pd_record():
    middleware.require_role(INSTRUCTOR, REGISTRAR_OFFICER)
    payload = validate.body()

    raw_faculty_id = payload.get("faculty_member_id")
    if isinstance(raw_faculty_id, str):
        middleware.require_instructor_owns(raw_faculty_id)

    faculty_id = validate.req_str(payload, "faculty_member_id")
    discipline_id = validate.req_str(payload, "discipline_id")
    activity_type = validate.req_enum(payload, "activity_type", PD_ACTIVITY_TYPES)
    contact_hours = validate.req_num(payload, "contact_hours", exclusive_min=0)
    activity_date = validate.req_date(payload, "activity_date")

    faculty = lookup.faculty(faculty_id)
    lookup.discipline(discipline_id)

    guards.require_not_separated(faculty)

    if activity_date > clock.current_date():
        raise ApiError("ERR_PD_DATE_IN_FUTURE")

    home_program = store.programs.get(faculty.get("home_program_id"))
    program_discipline = (home_program or {}).get("discipline_id")
    relevant = calc.aligns(discipline_id, program_discipline)

    row = db.new_row(
        faculty_member_id=faculty_id,
        discipline_id=discipline_id,
        activity_type=activity_type,
        contact_hours=contact_hours,
        activity_date=util.date_to_str(activity_date),
        status="SUBMITTED",
        discipline_relevant=bool(relevant),
    )
    store.pd_records[row["id"]] = row
    return response.created(serialize.pd_record(row))


@bp.route("/pd-records/<pd_record_id>", methods=["GET"])
def read_pd_record(pd_record_id):
    middleware.require_role(*ALL_ROLES)
    row = lookup.pd_record(pd_record_id)
    middleware.require_instructor_owns(row.get("faculty_member_id"))
    return response.ok(serialize.pd_record(row))


@bp.route("/pd-records", methods=["GET"])
def list_pd_records():
    middleware.require_role(*READ_ROLES)
    faculty_id = validate.q_str("faculty_member_id")
    discipline_id = validate.q_str("discipline_id")
    status = validate.q_enum("status", PD_STATUSES)
    activity_type = validate.q_enum("activity_type", PD_ACTIVITY_TYPES)
    relevant = validate.q_bool("discipline_relevant")

    rows = []
    for row in db.ordered(store.pd_records):
        if not (match(row, "faculty_member_id", faculty_id)
                and match(row, "discipline_id", discipline_id)
                and match(row, "status", status)
                and match(row, "activity_type", activity_type)):
            continue
        if relevant is not None and bool(row.get("discipline_relevant")) is not relevant:
            continue
        rows.append(row)
    return list_response(rows, serialize.pd_record)


@bp.route("/pd-records/<pd_record_id>/status", methods=["POST"])
def pd_record_status(pd_record_id):
    middleware.require_role(CREDENTIAL_ANALYST)
    payload = validate.body()
    to_status = validate.req_enum(payload, "to_status", PD_STATUSES)

    row = lookup.pd_record(pd_record_id)

    if row["status"] != "SUBMITTED" or to_status not in ("VERIFIED", "REJECTED"):
        guards.invalid_state("A professional development record in %s may not move to %s."
                             % (row["status"], to_status))

    row["status"] = to_status
    touch(row)

    if to_status == "VERIFIED":
        faculty = store.faculty_members.get(row["faculty_member_id"])
        if faculty is not None:
            domain.refresh_pd(faculty)
            touch(faculty)

    return response.ok(serialize.pd_record(row))
