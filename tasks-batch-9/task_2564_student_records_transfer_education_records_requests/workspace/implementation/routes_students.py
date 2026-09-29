"""Enrollment, directory information, disclosure log and discipline incidents."""

from flask import Blueprint

import serialize
from authz import RIGHTS_HOLDER_ROLES, rights_holder_guard
from calc import is_eligible_student
from common import (API_PREFIX, READ_STAFF, ROLE_COMPLIANCE_OFFICER, ROLE_ELIGIBLE_STUDENT,
                    ROLE_LEGAL_AFFAIRS_OFFICER, ROLE_PARENT, ROLE_RECORDS_CLERK,
                    ROLE_RECORDS_OFFICER, ROLE_SYSTEM_ADMIN, STORE, add_calendar_days, base_row,
                    body, clock_now, err, optional_bool, optional_enum, optional_int,
                    parse_calendar_date, query_bool, query_value, require_enum, require_int,
                    require_role, require_string, require_subset, touch, user_id,
                    validation_error)
from derive import append_disclosure, refresh_eligibility
from domain import (ACTION_TYPES, COMPONENT_TYPE_ORDER, DIRECTORY_CATEGORIES,
                    DIRECTORY_CATEGORY_ORDER, DISCLOSURE_TYPES, INCIDENT_STATUSES,
                    REQUIRED_BASE_TYPES, SOURCE_TYPES, disclosures_of_student, get_district,
                    get_incident, get_student, incidents_of_student, state_rule_for_student)
from response import created, ok, paginate

bp = Blueprint("students", __name__)

STUDENT_READ_ROLES = READ_STAFF + [ROLE_PARENT, ROLE_ELIGIBLE_STUDENT]
DISCLOSURE_LOG_ROLES = [ROLE_SYSTEM_ADMIN, ROLE_RECORDS_CLERK, ROLE_RECORDS_OFFICER,
                        ROLE_COMPLIANCE_OFFICER, ROLE_LEGAL_AFFAIRS_OFFICER,
                        ROLE_PARENT, ROLE_ELIGIBLE_STUDENT]
INCIDENT_READ_ROLES = [ROLE_SYSTEM_ADMIN, ROLE_RECORDS_CLERK, ROLE_RECORDS_OFFICER,
                       ROLE_COMPLIANCE_OFFICER, ROLE_LEGAL_AFFAIRS_OFFICER,
                       ROLE_PARENT, ROLE_ELIGIBLE_STUDENT]


# --------------------------------------------------------------------------- #
# Enrollment
# --------------------------------------------------------------------------- #
def _mint_file_skeleton(student_row):
    required = list(REQUIRED_BASE_TYPES)
    if student_row["has_iep"]:
        required = required + ["SPECIAL_EDUCATION"]

    file_row = base_row()
    file_row.update({
        "student_id": student_row["id"],
        "assembly_status": "NOT_STARTED",
        "required_component_types": required,
        "certified_component_count": 0,
        "completeness_pct": 0.0,
        "total_page_count": 0,
        "included_page_count": 0,
        "excluded_page_count": 0,
        "disclosable_page_count": 0,
        "last_packet_snapshot_at": None,
    })
    STORE.cumulative_files[file_row["id"]] = file_row

    for component_type in COMPONENT_TYPE_ORDER:
        component = base_row()
        component.update({
            "cumulative_file_id": file_row["id"],
            "component_type": component_type,
            "status": "PENDING",
            "page_count": 0,
            "redacted_page_count": 0,
            "disclosable_page_count": 0,
            "exclusion_reason": None,
            "certified_by_user_id": None,
            "certified_at": None,
            "amendment_count": 0,
            "statement_of_disagreement_present": False,
            "is_required": component_type in required,
        })
        STORE.file_components[component["id"]] = component
    return file_row


@bp.route(API_PREFIX + "/students", methods=["POST"])
def create_student():
    require_role([ROLE_SYSTEM_ADMIN, ROLE_RECORDS_CLERK])
    payload = body()
    district_id = payload.get("district_id")
    if district_id is None or not isinstance(district_id, str) or district_id.strip() == "":
        validation_error("Field 'district_id' is required.")
    district = get_district(district_id)

    first_name = require_string(payload, "first_name")
    last_name = require_string(payload, "last_name")
    dob_raw = require_string(payload, "dob")
    dob = parse_calendar_date(dob_raw)
    if dob is None:
        validation_error("Field 'dob' must be an ISO 8601 calendar date.")
    now = clock_now()
    if not (dob < now.date()):
        validation_error("Field 'dob' must fall strictly before the current date.")
    grade_level = require_int(payload, "grade_level", 0, 12)
    guardian_user_id = require_string(payload, "guardian_user_id")
    has_iep = optional_bool(payload, "has_iep", False)
    student_user_id = payload.get("student_user_id")
    if student_user_id is not None and not isinstance(student_user_id, str):
        validation_error("Field 'student_user_id' must be a string.")

    rule = STORE.state_rules.get(district["state_code"])
    if rule is None:
        err("ERR_STATE_RULE_NOT_FOUND", 404, "The district's state has no rule row.")

    row = base_row()
    row.update({
        "district_id": district_id,
        "first_name": first_name,
        "last_name": last_name,
        "dob": dob_raw,
        "grade_level": grade_level,
        "has_iep": has_iep,
        "guardian_user_id": guardian_user_id,
        "student_user_id": student_user_id,
        "enrollment_status": "ENROLLED",
        "is_eligible_student": False,
        "directory_optout_deadline_at": add_calendar_days(
            row["created_at"], rule["directory_optout_grace_days"]),
        "directory_optout_received_at": None,
        "directory_optout_categories": [],
        "directory_optout_effective": False,
        "exit_effective_date": None,
        "records_disposition_date": None,
    })
    row["is_eligible_student"] = is_eligible_student(row)
    STORE.students[row["id"]] = row
    _mint_file_skeleton(row)
    return created(serialize.student(row))


@bp.route(API_PREFIX + "/students", methods=["GET"])
def list_students():
    require_role(READ_STAFF)
    rows = list(STORE.students.values())
    district_id = query_value("district_id")
    if district_id is not None:
        rows = [row for row in rows if row["district_id"] == district_id]
    enrollment_status = query_value("enrollment_status")
    if enrollment_status is not None:
        rows = [row for row in rows if row["enrollment_status"] == enrollment_status]
    has_iep = query_bool("has_iep")
    if has_iep is not None:
        rows = [row for row in rows if row["has_iep"] == has_iep]
    return paginate(rows, serialize.student)


@bp.route(API_PREFIX + "/students/<student_id>", methods=["GET"])
def get_one_student(student_id):
    row = get_student(student_id)
    require_role(STUDENT_READ_ROLES)
    refresh_eligibility(row)
    return ok(serialize.student(row))


# --------------------------------------------------------------------------- #
# Directory information
# --------------------------------------------------------------------------- #
@bp.route(API_PREFIX + "/students/<student_id>/directory-optout", methods=["PATCH"])
def directory_optout(student_id):
    row = get_student(student_id)
    require_role(RIGHTS_HOLDER_ROLES)
    rights_holder_guard(row)
    payload = body()
    categories = require_subset(payload, "directory_optout_categories",
                                DIRECTORY_CATEGORIES, DIRECTORY_CATEGORY_ORDER)
    now = clock_now()
    if now > row["directory_optout_deadline_at"]:
        err("ERR_OPTOUT_WINDOW_CLOSED", 422, "The directory opt-out window has closed.")
    row["directory_optout_categories"] = categories
    row["directory_optout_received_at"] = now
    row["directory_optout_effective"] = True
    touch(row)
    return ok(serialize.student(row))


@bp.route(API_PREFIX + "/students/<student_id>/directory-disclosures", methods=["POST"])
def directory_disclosure(student_id):
    row = get_student(student_id)
    require_role([ROLE_RECORDS_CLERK, ROLE_RECORDS_OFFICER])
    payload = body()
    recipient_name = require_string(payload, "recipient_name")
    categories = require_subset(payload, "disclosed_categories",
                               DIRECTORY_CATEGORIES, DIRECTORY_CATEGORY_ORDER)
    note = payload.get("legitimate_interest_note")
    if note is not None and not isinstance(note, str):
        validation_error("Field 'legitimate_interest_note' must be a string.")

    if row["directory_optout_effective"]:
        opted_out = set(row["directory_optout_categories"])
        if all(name in opted_out for name in categories):
            err("ERR_DIRECTORY_OPTOUT_ACTIVE", 422,
                "Every requested category is covered by an active opt-out.")

    entry = append_disclosure(
        student_id=student_id,
        disclosure_type="DIRECTORY_INFORMATION",
        source_type="STUDENT_DIRECTORY",
        source_id=student_id,
        recipient_name=recipient_name,
        disclosed_categories=categories,
        page_count=0,
        logged_by_user_id=user_id(),
        legitimate_interest_note=note,
    )
    return created(serialize.disclosure_entry(entry))


@bp.route(API_PREFIX + "/students/<student_id>/disclosure-log", methods=["GET"])
def disclosure_log(student_id):
    get_student(student_id)
    require_role(DISCLOSURE_LOG_ROLES)
    rows = disclosures_of_student(student_id)
    disclosure_type = query_value("disclosure_type")
    if disclosure_type is not None:
        rows = [row for row in rows if row["disclosure_type"] == disclosure_type]
    source_type = query_value("source_type")
    if source_type is not None:
        rows = [row for row in rows if row["source_type"] == source_type]
    return paginate(rows, serialize.disclosure_entry, presorted=True)


# --------------------------------------------------------------------------- #
# Discipline incidents
# --------------------------------------------------------------------------- #
@bp.route(API_PREFIX + "/students/<student_id>/discipline-incidents", methods=["POST"])
def create_incident(student_id):
    get_student(student_id)
    require_role([ROLE_RECORDS_CLERK, ROLE_RECORDS_OFFICER])
    payload = body()
    incident_date_raw = require_string(payload, "incident_date")
    if parse_calendar_date(incident_date_raw) is None:
        validation_error("Field 'incident_date' must be an ISO 8601 calendar date.")
    action_type = require_enum(payload, "action_type", ACTION_TYPES)
    days_removed = optional_int(payload, "days_removed", 0, 0, 365)
    incident_status = optional_enum(payload, "incident_status", INCIDENT_STATUSES, "SUSTAINED")
    adjudicated = optional_bool(payload, "adjudicated_by_court", False)
    description = require_string(payload, "description")

    row = base_row()
    row.update({
        "student_id": student_id,
        "incident_date": incident_date_raw,
        "action_type": action_type,
        "days_removed": days_removed,
        "incident_status": incident_status,
        "adjudicated_by_court": adjudicated,
        "description": description,
        "transfer_inclusion_state": "NOT_EVALUATED",
    })
    STORE.discipline_incidents[row["id"]] = row
    return created(serialize.discipline_incident(row))


@bp.route(API_PREFIX + "/students/<student_id>/discipline-incidents", methods=["GET"])
def list_incidents(student_id):
    get_student(student_id)
    require_role(INCIDENT_READ_ROLES)
    rows = incidents_of_student(student_id)
    action_type = query_value("action_type")
    if action_type is not None:
        rows = [row for row in rows if row["action_type"] == action_type]
    incident_status = query_value("incident_status")
    if incident_status is not None:
        rows = [row for row in rows if row["incident_status"] == incident_status]
    inclusion_state = query_value("transfer_inclusion_state")
    if inclusion_state is not None:
        rows = [row for row in rows if row["transfer_inclusion_state"] == inclusion_state]
    return paginate(rows, serialize.discipline_incident, presorted=True)


@bp.route(API_PREFIX + "/discipline-incidents/<incident_id>", methods=["GET"])
def get_one_incident(incident_id):
    row = get_incident(incident_id)
    require_role(INCIDENT_READ_ROLES)
    return ok(serialize.discipline_incident(row))
