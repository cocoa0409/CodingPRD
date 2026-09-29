"""Cumulative files, component assembly and the retention schedule listing (PRD 3.3)."""

from flask import Blueprint

import serialize
from common import (API_PREFIX, ROLE_COMPLIANCE_OFFICER, ROLE_ELIGIBLE_STUDENT,
                    ROLE_LEGAL_AFFAIRS_OFFICER, ROLE_PARENT, ROLE_RECORDS_CLERK,
                    ROLE_RECORDS_OFFICER, ROLE_SYSTEM_ADMIN, STORE, body, clock_now, err,
                    optional_int, query_value, require_enum, require_role, touch, user_id,
                    validation_error)
from derive import recompute_file
from domain import (COMPONENT_TARGET_STATUSES, EXCLUSION_REASONS, components_of_file,
                    file_of_student, get_cumulative_file, get_scoped_component, get_student,
                    schedule_of_file)
from response import ok, paginate

bp = Blueprint("files", __name__)

FILE_READ_ROLES = [ROLE_SYSTEM_ADMIN, ROLE_RECORDS_CLERK, ROLE_RECORDS_OFFICER,
                   ROLE_COMPLIANCE_OFFICER, ROLE_LEGAL_AFFAIRS_OFFICER,
                   ROLE_PARENT, ROLE_ELIGIBLE_STUDENT]
RETENTION_READ_ROLES = [ROLE_SYSTEM_ADMIN, ROLE_RECORDS_OFFICER, ROLE_COMPLIANCE_OFFICER,
                        ROLE_LEGAL_AFFAIRS_OFFICER]


@bp.route(API_PREFIX + "/students/<student_id>/cumulative-files", methods=["GET"])
def list_student_files(student_id):
    get_student(student_id)
    require_role(FILE_READ_ROLES)
    file_row = file_of_student(student_id)
    rows = [file_row] if file_row is not None else []
    return paginate(rows, serialize.cumulative_file)


@bp.route(API_PREFIX + "/cumulative-files/<file_id>", methods=["GET"])
def get_one_file(file_id):
    row = get_cumulative_file(file_id)
    require_role(FILE_READ_ROLES)
    return ok(serialize.cumulative_file(row))


@bp.route(API_PREFIX + "/cumulative-files/<file_id>/components", methods=["GET"])
def list_components(file_id):
    get_cumulative_file(file_id)
    require_role(FILE_READ_ROLES)
    rows = components_of_file(file_id)
    status = query_value("status")
    if status is not None:
        rows = [row for row in rows if row["status"] == status]
    component_type = query_value("component_type")
    if component_type is not None:
        rows = [row for row in rows if row["component_type"] == component_type]
    return paginate(rows, serialize.file_component, presorted=True)


@bp.route(API_PREFIX + "/cumulative-files/<file_id>/retention-schedules", methods=["GET"])
def list_retention_schedules(file_id):
    get_cumulative_file(file_id)
    require_role(RETENTION_READ_ROLES)
    schedule = schedule_of_file(file_id)
    rows = [schedule] if schedule is not None else []
    status = query_value("status")
    if status is not None:
        rows = [row for row in rows if row["status"] == status]
    return paginate(rows, serialize.retention_schedule)


# --------------------------------------------------------------------------- #
# Component lifecycle
# --------------------------------------------------------------------------- #
@bp.route(API_PREFIX + "/cumulative-files/<file_id>/components/<component_id>",
          methods=["PATCH"])
def patch_component(file_id, component_id):
    file_row = get_cumulative_file(file_id)
    component = get_scoped_component(file_row, component_id)
    require_role([ROLE_RECORDS_CLERK, ROLE_RECORDS_OFFICER])
    payload = body()

    target = require_enum(payload, "status", COMPONENT_TARGET_STATUSES)
    page_count = optional_int(payload, "page_count", None, 0, 5000)
    redacted = optional_int(payload, "redacted_page_count", None, 0, 5000)
    reason = payload.get("exclusion_reason")
    if reason is not None and reason not in EXCLUSION_REASONS:
        validation_error("Field 'exclusion_reason' must be a supported reason.")

    effective_pages = page_count if page_count is not None else int(component["page_count"])
    effective_redacted = redacted if redacted is not None else int(component["redacted_page_count"])
    if page_count is not None and redacted is None:
        effective_redacted = 0
    if effective_redacted > effective_pages:
        validation_error("Field 'redacted_page_count' may not exceed 'page_count'.")

    if target == "EXCLUDED" and reason is None:
        validation_error("Field 'exclusion_reason' is required to exclude a component.")

    current = component["status"]

    if target == "COLLECTED":
        if current == "CERTIFIED":
            err("ERR_COMPONENT_NOT_EXCLUDED", 409,
                "A certified component is neither collectible nor reinstatable.")
        if current == "PENDING" and page_count is None:
            validation_error("Field 'page_count' is required to collect a component.")
        component["page_count"] = effective_pages
        component["redacted_page_count"] = effective_redacted
        if current == "EXCLUDED":
            component["exclusion_reason"] = None
        component["status"] = "COLLECTED"
    elif target == "CERTIFIED":
        if current == "CERTIFIED":
            err("ERR_COMPONENT_ALREADY_CERTIFIED", 409, "The component is already certified.")
        if current != "COLLECTED":
            err("ERR_COMPONENT_NOT_COLLECTED", 409, "The component is not collected.")
        if int(component["page_count"]) < 1:
            validation_error("A component with no pages cannot be certified.")
        component["status"] = "CERTIFIED"
        component["certified_by_user_id"] = user_id()
        component["certified_at"] = clock_now()
    else:
        if current not in ("COLLECTED", "CERTIFIED"):
            err("ERR_COMPONENT_NOT_COLLECTED", 409,
                "Only a collected or certified component may be excluded.")
        if current == "CERTIFIED":
            component["certified_by_user_id"] = None
            component["certified_at"] = None
        component["exclusion_reason"] = reason
        component["status"] = "EXCLUDED"

    component["disclosable_page_count"] = (int(component["page_count"])
                                           - int(component["redacted_page_count"]))
    touch(component)
    recompute_file(file_row, force_bump=True)
    return ok(serialize.file_component(component))
