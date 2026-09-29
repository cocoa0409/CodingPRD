"""Withdrawal clearance, exit holds and the exit cascade (PRD 3.2)."""

from datetime import datetime, timezone

from flask import Blueprint

import serialize
from common import (API_PREFIX, ROLE_COMPLIANCE_OFFICER, ROLE_RECEIVING_REGISTRAR,
                    ROLE_RECORDS_CLERK, ROLE_RECORDS_OFFICER, ROLE_SYSTEM_ADMIN, STORE, base_row,
                    body, clock_now, err, parse_calendar_date, query_value, require_enum,
                    require_role, require_string, touch, validation_error)
from derive import recompute_file, recompute_schedule
from domain import (HOLD_TYPES, WITHDRAWAL_REASONS, file_of_student, get_student, get_withdrawal,
                    state_rule_for_student)
from response import created, ok, paginate

bp = Blueprint("withdrawals", __name__)

WITHDRAWAL_LIST_ROLES = [ROLE_SYSTEM_ADMIN, ROLE_RECORDS_CLERK, ROLE_RECORDS_OFFICER,
                         ROLE_COMPLIANCE_OFFICER, ROLE_RECEIVING_REGISTRAR]
WITHDRAWAL_READ_ROLES = [ROLE_SYSTEM_ADMIN, ROLE_RECORDS_CLERK, ROLE_RECORDS_OFFICER,
                         ROLE_COMPLIANCE_OFFICER]


@bp.route(API_PREFIX + "/students/<student_id>/withdrawals", methods=["POST"])
def open_withdrawal(student_id):
    student = get_student(student_id)
    require_role([ROLE_RECORDS_CLERK])
    payload = body()
    effective_raw = require_string(payload, "effective_date")
    if parse_calendar_date(effective_raw) is None:
        validation_error("Field 'effective_date' must be an ISO 8601 calendar date.")
    destination = payload.get("destination_district_code")
    if destination is not None and not isinstance(destination, str):
        validation_error("Field 'destination_district_code' must be a string or null.")
    reason = require_enum(payload, "withdrawal_reason", WITHDRAWAL_REASONS)

    if student["enrollment_status"] not in ("ENROLLED", "WITHDRAWAL_PENDING"):
        err("ERR_STUDENT_NOT_ENROLLED", 409, "The student is no longer enrolled.")

    for row in STORE.withdrawals.values():
        if row["student_id"] == student_id and row["status"] != "COMPLETED":
            err("ERR_OPEN_WITHDRAWAL_EXISTS", 409, "The student already has an open withdrawal.")

    row = base_row()
    row.update({
        "student_id": student_id,
        "effective_date": effective_raw,
        "destination_district_code": destination,
        "withdrawal_reason": reason,
        "status": "CLEARED",
        "hold_count": 0,
        "active_hold_types": [],
        "completed_at": None,
    })
    STORE.withdrawals[row["id"]] = row

    if student["enrollment_status"] == "ENROLLED":
        student["enrollment_status"] = "WITHDRAWAL_PENDING"
        touch(student)
    return created(serialize.withdrawal(row))


@bp.route(API_PREFIX + "/students/<student_id>/withdrawals", methods=["GET"])
def list_withdrawals(student_id):
    get_student(student_id)
    require_role(WITHDRAWAL_LIST_ROLES)
    rows = [row for row in STORE.withdrawals.values() if row["student_id"] == student_id]
    status = query_value("status")
    if status is not None:
        rows = [row for row in rows if row["status"] == status]
    return paginate(rows, serialize.withdrawal)


@bp.route(API_PREFIX + "/withdrawals/<withdrawal_id>", methods=["GET"])
def get_one_withdrawal(withdrawal_id):
    row = get_withdrawal(withdrawal_id)
    require_role(WITHDRAWAL_READ_ROLES)
    return ok(serialize.withdrawal(row))


@bp.route(API_PREFIX + "/withdrawals/<withdrawal_id>/holds", methods=["POST"])
def place_hold(withdrawal_id):
    row = get_withdrawal(withdrawal_id)
    require_role([ROLE_RECORDS_CLERK])
    payload = body()
    hold_type = require_enum(payload, "hold_type", HOLD_TYPES)
    if row["status"] == "COMPLETED":
        err("ERR_WITHDRAWAL_ALREADY_COMPLETED", 409, "The withdrawal is already completed.")
    if hold_type in row["active_hold_types"]:
        err("ERR_HOLD_ALREADY_ACTIVE", 409, "That hold is already active.")
    holds = sorted(row["active_hold_types"] + [hold_type])
    row["active_hold_types"] = holds
    row["hold_count"] = len(holds)
    row["status"] = "HOLD"
    touch(row)
    return ok(serialize.withdrawal(row))


@bp.route(API_PREFIX + "/withdrawals/<withdrawal_id>/hold-releases", methods=["POST"])
def release_hold(withdrawal_id):
    row = get_withdrawal(withdrawal_id)
    require_role([ROLE_RECORDS_CLERK])
    payload = body()
    hold_type = require_enum(payload, "hold_type", HOLD_TYPES)
    if row["status"] == "COMPLETED":
        err("ERR_WITHDRAWAL_ALREADY_COMPLETED", 409, "The withdrawal is already completed.")
    if hold_type not in row["active_hold_types"]:
        err("ERR_HOLD_NOT_ACTIVE", 409, "That hold is not active.")
    holds = sorted([name for name in row["active_hold_types"] if name != hold_type])
    row["active_hold_types"] = holds
    row["hold_count"] = len(holds)
    row["status"] = "HOLD" if holds else "CLEARED"
    touch(row)
    return ok(serialize.withdrawal(row))


def _mint_retention_schedule(student, file_row):
    exit_date = parse_calendar_date(student["exit_effective_date"])
    anchor = datetime(exit_date.year, exit_date.month, exit_date.day, 0, 0, 0, 0,
                      tzinfo=timezone.utc)
    rule = state_rule_for_student(student)
    years = int(rule["destruction_min_age_years"]) if rule else 1
    row = base_row()
    row.update({
        "cumulative_file_id": file_row["id"],
        "exit_anchor_at": anchor,
        "last_activity_at": anchor,
        "destruction_min_age_years": years,
        "destruction_eligible_at": anchor,
        "exit_anchored_eligible_at": anchor,
        "status": "ACTIVE",
        "destruction_method": None,
        "certification_note": None,
        "destroyed_at": None,
    })
    STORE.retention_schedules[row["id"]] = row
    recompute_schedule(row)
    return row


@bp.route(API_PREFIX + "/withdrawals/<withdrawal_id>/complete", methods=["POST"])
def complete_withdrawal(withdrawal_id):
    row = get_withdrawal(withdrawal_id)
    require_role([ROLE_RECORDS_OFFICER])
    if row["status"] == "COMPLETED":
        err("ERR_WITHDRAWAL_ALREADY_COMPLETED", 409, "The withdrawal is already completed.")
    student = STORE.students.get(row["student_id"])
    if (row["status"] != "CLEARED" or int(row["hold_count"]) != 0
            or student is None or student["enrollment_status"] != "WITHDRAWAL_PENDING"):
        err("ERR_WITHDRAWAL_NOT_CLEARED", 409,
            "The withdrawal is not cleared for completion.")

    now = clock_now()
    row["status"] = "COMPLETED"
    row["completed_at"] = now
    touch(row)

    student["enrollment_status"] = "WITHDRAWN"
    student["exit_effective_date"] = row["effective_date"]
    touch(student)

    file_row = file_of_student(student["id"])
    if file_row is not None:
        _mint_retention_schedule(student, file_row)
        recompute_file(file_row)
    return ok(serialize.withdrawal(row))
