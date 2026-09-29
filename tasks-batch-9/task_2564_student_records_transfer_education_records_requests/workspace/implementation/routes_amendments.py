"""Amendment challenges, hearings and statements of disagreement (PRD 3.8)."""

from flask import Blueprint

import serialize
from authz import RIGHTS_HOLDER_ROLES, rights_holder_guard
from common import (API_PREFIX, ROLE_COMPLIANCE_OFFICER, ROLE_ELIGIBLE_STUDENT, ROLE_PARENT,
                    ROLE_RECORDS_CLERK, ROLE_RECORDS_OFFICER, ROLE_SYSTEM_ADMIN, STORE,
                    add_calendar_days, base_row, body, clock_now, err, query_value,
                    require_enum, require_instant, require_role, require_string, touch, user_id,
                    validation_error, whole_minutes)
from derive import recompute_file
from domain import (AMENDMENT_OUTCOMES, OFFICER_DAILY_MINUTE_CAP, file_of_student,
                    get_amendment_request, get_component, get_hearing_officer, get_student,
                    state_rule_for_student)
from response import created, ok, paginate

bp = Blueprint("amendments", __name__)

AMENDMENT_READ_ROLES = [ROLE_SYSTEM_ADMIN, ROLE_RECORDS_CLERK, ROLE_RECORDS_OFFICER,
                        ROLE_COMPLIANCE_OFFICER, ROLE_PARENT, ROLE_ELIGIBLE_STUDENT]
TERMINAL_STATUSES = ("AMENDED", "STATEMENT_FILED")


def _student_of(amendment_row):
    return STORE.students.get(amendment_row["student_id"])


# --------------------------------------------------------------------------- #
# Filing
# --------------------------------------------------------------------------- #
@bp.route(API_PREFIX + "/students/<student_id>/amendment-requests", methods=["POST"])
def create_amendment(student_id):
    student = get_student(student_id)
    require_role(RIGHTS_HOLDER_ROLES)
    payload = body()
    component_id = payload.get("contested_component_id")
    if component_id is None or not isinstance(component_id, str) or component_id.strip() == "":
        validation_error("Field 'contested_component_id' is required.")
    component = get_component(component_id)
    rights_holder_guard(student)

    contested_field = require_string(payload, "contested_field")
    requested_change = require_string(payload, "requested_change")
    rationale = require_string(payload, "rationale")

    file_row = file_of_student(student_id)
    if (file_row is None or component["cumulative_file_id"] != file_row["id"]
            or component["status"] == "EXCLUDED"):
        err("ERR_COMPONENT_NOT_FOR_STUDENT", 422,
            "The contested component does not belong to this student's file.")

    row = base_row()
    row.update({
        "student_id": student_id,
        "contested_component_id": component_id,
        "hearing_officer_id": None,
        "requester_user_id": user_id(),
        "contested_field": contested_field,
        "requested_change": requested_change,
        "rationale": rationale,
        "status": "SUBMITTED",
        "initial_decided_by_user_id": None,
        "hearing_decided_by_user_id": None,
        "decision_note": None,
        "denied_at": None,
        "hearing_due_at": None,
        "hearing_start_at": None,
        "hearing_end_at": None,
        "hearing_duration_minutes": None,
        "statement_text": None,
        "statement_filed_at": None,
    })
    STORE.amendment_requests[row["id"]] = row
    return created(serialize.amendment_request(row))


@bp.route(API_PREFIX + "/amendment-requests", methods=["GET"])
def list_amendments():
    require_role(AMENDMENT_READ_ROLES)
    rows = list(STORE.amendment_requests.values())
    for name in ("student_id", "contested_component_id", "hearing_officer_id", "status"):
        value = query_value(name)
        if value is not None:
            rows = [row for row in rows if row[name] == value]
    return paginate(rows, serialize.amendment_request)


@bp.route(API_PREFIX + "/amendment-requests/<amendment_id>", methods=["GET"])
def get_one_amendment(amendment_id):
    row = get_amendment_request(amendment_id)
    require_role(AMENDMENT_READ_ROLES)
    return ok(serialize.amendment_request(row))


# --------------------------------------------------------------------------- #
# Decisions
# --------------------------------------------------------------------------- #
def _apply_grant(amendment_row):
    component = STORE.file_components.get(amendment_row["contested_component_id"])
    if component is None:
        return
    if component["status"] == "CERTIFIED":
        component["status"] = "COLLECTED"
        component["certified_by_user_id"] = None
        component["certified_at"] = None
    component["amendment_count"] = int(component["amendment_count"]) + 1
    touch(component)
    file_row = STORE.cumulative_files.get(component["cumulative_file_id"])
    if file_row is not None:
        recompute_file(file_row, force_bump=True)


@bp.route(API_PREFIX + "/amendment-requests/<amendment_id>/decisions", methods=["POST"])
def decide_amendment(amendment_id):
    row = get_amendment_request(amendment_id)
    require_role([ROLE_RECORDS_OFFICER])

    # Segregation of duties sits in the authorization band, ahead of payload schema.
    if row["status"] == "HEARING_SCHEDULED" and user_id() == row["initial_decided_by_user_id"]:
        err("ERR_SEGREGATION_OF_DUTIES", 403,
            "The official who denied the amendment may not decide its hearing.")

    payload = body()
    outcome = require_enum(payload, "outcome", AMENDMENT_OUTCOMES)
    note = payload.get("decision_note")
    if note is not None and not isinstance(note, str):
        validation_error("Field 'decision_note' must be a string.")

    if row["status"] in TERMINAL_STATUSES:
        err("ERR_AMENDMENT_TERMINAL", 409, "The amendment request is terminal.")
    if row["status"] not in ("SUBMITTED", "HEARING_SCHEDULED"):
        err("ERR_AMENDMENT_NOT_SUBMITTED", 409, "The amendment request is not open for decision.")

    now = clock_now()
    if row["status"] == "HEARING_SCHEDULED":
        if row["hearing_end_at"] is None or now < row["hearing_end_at"]:
            err("ERR_HEARING_NOT_HELD", 409, "The hearing has not been held yet.")
        row["hearing_decided_by_user_id"] = user_id()
        if note is not None:
            row["decision_note"] = note
        if outcome == "GRANT":
            row["status"] = "AMENDED"
            touch(row)
            _apply_grant(row)
        else:
            row["status"] = "UPHELD"
            touch(row)
        return ok(serialize.amendment_request(row))

    row["initial_decided_by_user_id"] = user_id()
    if note is not None:
        row["decision_note"] = note
    if outcome == "GRANT":
        row["status"] = "AMENDED"
        touch(row)
        _apply_grant(row)
    else:
        row["status"] = "DENIED"
        row["denied_at"] = now
        student = _student_of(row)
        rule = state_rule_for_student(student) if student is not None else None
        days = int(rule["amendment_hearing_days"]) if rule else 0
        row["hearing_due_at"] = add_calendar_days(now, days)
        touch(row)
    return ok(serialize.amendment_request(row))


# --------------------------------------------------------------------------- #
# Hearing right
# --------------------------------------------------------------------------- #
@bp.route(API_PREFIX + "/amendment-requests/<amendment_id>/hearing-requests", methods=["POST"])
def request_hearing(amendment_id):
    row = get_amendment_request(amendment_id)
    require_role(RIGHTS_HOLDER_ROLES)
    student = _student_of(row)
    if student is not None:
        rights_holder_guard(student)

    if row["status"] in TERMINAL_STATUSES:
        err("ERR_AMENDMENT_TERMINAL", 409, "The amendment request is terminal.")
    if row["status"] != "DENIED":
        err("ERR_AMENDMENT_NOT_DENIED", 409, "The amendment request has not been denied.")
    if row["hearing_due_at"] is None or clock_now() > row["hearing_due_at"]:
        err("ERR_HEARING_REQUEST_WINDOW_CLOSED", 422, "The hearing-request window has closed.")

    row["status"] = "HEARING_REQUESTED"
    touch(row)
    return ok(serialize.amendment_request(row))


# --------------------------------------------------------------------------- #
# Hearing scheduling
# --------------------------------------------------------------------------- #
def _officer_conflict(officer_id, start_at, end_at, exclude_id):
    for row in STORE.amendment_requests.values():
        if row["id"] == exclude_id or row["status"] != "HEARING_SCHEDULED":
            continue
        if row["hearing_officer_id"] != officer_id:
            continue
        if row["hearing_start_at"] is None or row["hearing_end_at"] is None:
            continue
        if start_at < row["hearing_end_at"] and end_at > row["hearing_start_at"]:
            return True
    return False


def _officer_daily_minutes(officer_id, day, exclude_id):
    total = 0
    for row in STORE.amendment_requests.values():
        if row["id"] == exclude_id or row["status"] != "HEARING_SCHEDULED":
            continue
        if row["hearing_officer_id"] != officer_id or row["hearing_start_at"] is None:
            continue
        if row["hearing_start_at"].date() == day:
            total += int(row["hearing_duration_minutes"] or 0)
    return total


@bp.route(API_PREFIX + "/amendment-requests/<amendment_id>/hearing-schedules", methods=["POST"])
def schedule_hearing(amendment_id):
    row = get_amendment_request(amendment_id)
    require_role([ROLE_RECORDS_OFFICER])
    payload = body()
    officer_id = payload.get("hearing_officer_id")
    if officer_id is None or not isinstance(officer_id, str) or officer_id.strip() == "":
        validation_error("Field 'hearing_officer_id' is required.")
    officer = get_hearing_officer(officer_id)

    start_at = require_instant(payload, "hearing_start_at")
    end_at = require_instant(payload, "hearing_end_at")
    if end_at <= start_at:
        validation_error("Field 'hearing_end_at' must be strictly after 'hearing_start_at'.")

    if row["status"] in TERMINAL_STATUSES:
        err("ERR_AMENDMENT_TERMINAL", 409, "The amendment request is terminal.")
    if row["status"] not in ("HEARING_REQUESTED", "HEARING_SCHEDULED"):
        err("ERR_HEARING_NOT_SCHEDULED", 409, "No hearing has been requested.")

    if officer["status"] != "ACTIVE":
        err("ERR_OFFICER_INACTIVE", 409, "The hearing officer is inactive.")

    if _officer_conflict(officer_id, start_at, end_at, row["id"]):
        err("ERR_OFFICER_DOUBLE_BOOKED", 409, "The officer already has a hearing in that window.")

    duration = whole_minutes(start_at, end_at)
    booked = _officer_daily_minutes(officer_id, start_at.date(), row["id"])
    if booked + duration > OFFICER_DAILY_MINUTE_CAP:
        err("ERR_OFFICER_DAILY_CAP_EXCEEDED", 409, "The officer's daily minute cap is exceeded.")

    if row["hearing_due_at"] is not None and start_at > row["hearing_due_at"]:
        err("ERR_HEARING_WINDOW_EXCEEDED", 422, "The hearing falls outside the statutory window.")

    row["hearing_officer_id"] = officer_id
    row["hearing_start_at"] = start_at
    row["hearing_end_at"] = end_at
    row["hearing_duration_minutes"] = duration
    row["status"] = "HEARING_SCHEDULED"
    touch(row)
    return ok(serialize.amendment_request(row))


# --------------------------------------------------------------------------- #
# Statement of disagreement
# --------------------------------------------------------------------------- #
@bp.route(API_PREFIX + "/amendment-requests/<amendment_id>/statements", methods=["POST"])
def file_statement(amendment_id):
    row = get_amendment_request(amendment_id)
    require_role(RIGHTS_HOLDER_ROLES)
    student = _student_of(row)
    if student is not None:
        rights_holder_guard(student)
    payload = body()
    statement_text = require_string(payload, "statement_text")

    if row["status"] != "UPHELD":
        err("ERR_STATEMENT_ALREADY_FILED", 409,
            "A statement of disagreement may only be filed against an upheld record.")

    now = clock_now()
    row["statement_text"] = statement_text
    row["statement_filed_at"] = now
    row["status"] = "STATEMENT_FILED"
    touch(row)

    component = STORE.file_components.get(row["contested_component_id"])
    if component is not None:
        component["statement_of_disagreement_present"] = True
        component["page_count"] = int(component["page_count"]) + 1
        component["disclosable_page_count"] = (int(component["page_count"])
                                               - int(component["redacted_page_count"]))
        touch(component)
        file_row = STORE.cumulative_files.get(component["cumulative_file_id"])
        if file_row is not None:
            recompute_file(file_row, force_bump=True)
    return ok(serialize.amendment_request(row))
