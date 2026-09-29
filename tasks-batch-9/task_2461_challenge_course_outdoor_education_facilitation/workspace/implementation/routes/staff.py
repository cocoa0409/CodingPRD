"""Facilitator rosters, training records and block-assignment reads."""
from flask import Blueprint

from db import store, base_row, touch, clock_date, by_created_at
from errors import invalid
from middleware import authorize
from response import object_response, created_response, list_response, pagination, paginate
from validation import body, req_str, req_enum, req_bool, req_num, req_date, add_months
from services import constants as C
from services import derive, serialize
from services.lookup import get_course, get_facilitator, get_training_record, get_block_assignment, apply_filters

bp = Blueprint("staff", __name__)
PREFIX = "/challenge-course"

DIRECTOR_OR_OFFICER = ["ProgramDirector", "SafetyOfficer"]


@bp.post(PREFIX + "/facilitators")
def create_facilitator():
    authorize(["ProgramDirector"])
    payload = body()

    course_id = req_str(payload, "course_id")
    full_name = req_str(payload, "full_name")
    staff_type = req_enum(payload, "staff_type", C.STAFF_TYPES)
    certification_level = req_enum(payload, "certification_level", C.CERT_LEVELS)
    cert_expires_on = req_date(payload, "cert_expires_on")
    is_operator_employee = req_bool(payload, "is_operator_employee", required=False, default=True)

    course = get_course(course_id)

    row = base_row()
    row.update({
        "course_id": course["id"],
        "full_name": full_name,
        "staff_type": staff_type,
        "certification_level": certification_level,
        "is_operator_employee": is_operator_employee,
        "cert_expires_on": cert_expires_on,
        "cert_status": "PROBATION",
    })
    row["cert_status"] = derive.derive_cert_status(row)
    store.facilitators[row["id"]] = row

    # A certification-bearing write refreshes the rescue counters (which are
    # derived on read) but deliberately does NOT re-derive posture (PRD 2.5).
    return created_response(serialize.facilitator(row))


@bp.get(PREFIX + "/facilitators/<facilitator_id>")
def read_facilitator(facilitator_id):
    authorize(["ProgramDirector", "SafetyOfficer", "Facilitator", "ProfessionalInspector"])
    row = get_facilitator(facilitator_id)
    return object_response(serialize.facilitator(row))


@bp.get(PREFIX + "/facilitators")
def list_facilitators():
    authorize(DIRECTOR_OR_OFFICER)
    limit, offset = pagination()
    rows = by_created_at(list(store.facilitators.values()))
    rows = apply_filters(rows, {
        "course_id": ("str", "course_id"),
        "staff_type": ("str", "staff_type"),
        "cert_status": ("str", "cert_status"),
        "certification_level": ("str", "certification_level"),
    })
    window, total = paginate(rows, limit, offset)
    return list_response([serialize.facilitator(r) for r in window], limit, offset, total)


@bp.get(PREFIX + "/facilitators/<facilitator_id>/training-records")
def list_facilitator_training(facilitator_id):
    authorize(DIRECTOR_OR_OFFICER)
    limit, offset = pagination()
    facilitator = get_facilitator(facilitator_id)
    rows = derive.training_of_facilitator(facilitator["id"])
    rows = apply_filters(rows, {"kind": ("str", "kind")})
    window, total = paginate(rows, limit, offset)
    return list_response([serialize.training_record(r) for r in window], limit, offset, total)


@bp.get(PREFIX + "/facilitators/<facilitator_id>/block-assignments")
def list_facilitator_assignments(facilitator_id):
    authorize(["ProgramDirector", "SafetyOfficer", "Facilitator"])
    limit, offset = pagination()
    facilitator = get_facilitator(facilitator_id)
    rows = derive.assignments_of_facilitator(facilitator["id"])
    window, total = paginate(rows, limit, offset)
    return list_response([serialize.block_assignment(r) for r in window], limit, offset, total)


@bp.post(PREFIX + "/training-records")
def create_training_record():
    authorize(["ProgramDirector"])
    payload = body()

    facilitator_id = req_str(payload, "facilitator_id")
    kind = req_enum(payload, "kind", C.TRAINING_KINDS)
    completed_on = req_date(payload, "completed_on")
    hours = req_num(payload, "hours", required=False, default=0, minimum=0)
    notes = req_str(payload, "notes", required=False, default="", allow_empty=True)

    if completed_on > clock_date():
        raise invalid("completed_on may not be later than the clock date.")

    facilitator = get_facilitator(facilitator_id)

    row = base_row(common_fields=False)
    row.update({
        "facilitator_id": facilitator["id"],
        "kind": kind,
        "hours": hours,
        "completed_on": completed_on,
        "notes": notes,
    })
    store.training_records[row["id"]] = row

    changed = False
    if kind == "RECERTIFICATION":
        # The only route out of LAPSED; the expiry reset happens either way.
        facilitator["cert_expires_on"] = add_months(completed_on, C.RECERT_EXTENSION_MONTHS)
        changed = True

    new_status = derive.derive_cert_status(facilitator)
    if new_status != facilitator["cert_status"]:
        facilitator["cert_status"] = new_status
        changed = True
    if changed:
        touch(facilitator)

    return created_response(serialize.training_record(row))


@bp.get(PREFIX + "/training-records/<training_record_id>")
def read_training_record(training_record_id):
    authorize(DIRECTOR_OR_OFFICER)
    row = get_training_record(training_record_id)
    return object_response(serialize.training_record(row))


@bp.get(PREFIX + "/training-records")
def list_training_records():
    authorize(DIRECTOR_OR_OFFICER)
    limit, offset = pagination()
    rows = by_created_at(list(store.training_records.values()))
    rows = apply_filters(rows, {
        "facilitator_id": ("str", "facilitator_id"),
        "kind": ("str", "kind"),
        "completed_on": ("date", "completed_on"),
    })
    window, total = paginate(rows, limit, offset)
    return list_response([serialize.training_record(r) for r in window], limit, offset, total)


@bp.get(PREFIX + "/block-assignments/<block_assignment_id>")
def read_block_assignment(block_assignment_id):
    authorize(["ProgramDirector", "SafetyOfficer", "Facilitator"])
    row = get_block_assignment(block_assignment_id)
    return object_response(serialize.block_assignment(row))


@bp.get(PREFIX + "/block-assignments")
def list_block_assignments():
    authorize(["ProgramDirector", "SafetyOfficer", "Facilitator"])
    limit, offset = pagination()
    rows = by_created_at(list(store.block_assignments.values()))
    rows = apply_filters(rows, {
        "program_block_id": ("str", "program_block_id"),
        "facilitator_id": ("str", "facilitator_id"),
        "assignment_role": ("str", "assignment_role"),
    })
    window, total = paginate(rows, limit, offset)
    return list_response([serialize.block_assignment(r) for r in window], limit, offset, total)
