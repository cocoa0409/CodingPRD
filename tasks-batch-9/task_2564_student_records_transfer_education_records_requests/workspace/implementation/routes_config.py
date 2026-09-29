"""Clock, compliance sweep, statutory reference data and scheduling resources."""

from flask import Blueprint

import serialize
from common import (API_PREFIX, READ_STAFF, ROLE_COMPLIANCE_OFFICER, ROLE_RECORDS_CLERK,
                   ROLE_RECORDS_OFFICER, ROLE_SYSTEM_ADMIN, STORE, base_row, body, clock_now,
                   err, optional_int, query_value, require_enum, require_instant, require_int,
                   require_role, require_string, set_clock, touch, validation_error)
from derive import recompute_schedule, refresh_all_eligibility
from domain import (CREDENTIALS, DISCIPLINE_INCLUSION_MODES, OFFICER_STATUSES,
                    OPEN_DEMAND_STATUSES, OPEN_REQUEST_STATUSES, ROOM_STATUSES, STATE_CODES,
                    get_district, get_hearing_officer, get_room, get_state_rule)
from response import created, empty, ok, paginate

bp = Blueprint("config", __name__)

ROOM_READ_ROLES = [ROLE_SYSTEM_ADMIN, ROLE_RECORDS_CLERK, ROLE_RECORDS_OFFICER,
                   ROLE_COMPLIANCE_OFFICER]
OFFICER_READ_ROLES = [ROLE_SYSTEM_ADMIN, ROLE_RECORDS_OFFICER, ROLE_COMPLIANCE_OFFICER]


# --------------------------------------------------------------------------- #
# Logical clock
# --------------------------------------------------------------------------- #
@bp.route(API_PREFIX + "/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    require_role([ROLE_SYSTEM_ADMIN])
    payload = body()
    instant = require_instant(payload, "current_utc")
    set_clock(instant)
    refresh_all_eligibility()
    return empty()


# --------------------------------------------------------------------------- #
# Compliance sweep
# --------------------------------------------------------------------------- #
def _student_has_open_demand(student_id):
    for row in STORE.legal_demands.values():
        if row["student_id"] == student_id and row["status"] in OPEN_DEMAND_STATUSES:
            return True
    return False


@bp.route(API_PREFIX + "/compliance-sweeps", methods=["POST"])
def compliance_sweep():
    require_role([ROLE_COMPLIANCE_OFFICER])
    now = clock_now()

    for row in STORE.records_requests.values():
        if row["status"] in OPEN_REQUEST_STATUSES and row["statutory_due_at"] is not None:
            if row["statutory_due_at"] < now and not row["is_overdue"]:
                row["is_overdue"] = True
                touch(row)

    for row in STORE.inspection_requests.values():
        if row["status"] == "SUBMITTED" and row["statutory_inspection_due_at"] < now:
            row["status"] = "EXPIRED"
            touch(row)

    for row in STORE.review_appointments.values():
        if row["status"] == "SCHEDULED" and row["end_at"] < now:
            row["status"] = "EXPIRED"
            touch(row)

    for row in STORE.retention_schedules.values():
        if row["status"] != "ACTIVE":
            continue
        file_row = STORE.cumulative_files.get(row["cumulative_file_id"])
        if file_row is None:
            continue
        if row["destruction_eligible_at"] is not None and now >= row["destruction_eligible_at"]:
            if not _student_has_open_demand(file_row["student_id"]):
                row["status"] = "DESTRUCTION_ELIGIBLE"
                touch(row)

    return empty()


# --------------------------------------------------------------------------- #
# State records rules
# --------------------------------------------------------------------------- #
@bp.route(API_PREFIX + "/state-rules", methods=["POST"])
def create_state_rule():
    require_role([ROLE_SYSTEM_ADMIN])
    payload = body()
    state_code = require_enum(payload, "state_code", STATE_CODES)
    transfer_response_days = require_int(payload, "transfer_response_days", 1, 90)
    mode = require_enum(payload, "discipline_inclusion_mode", DISCIPLINE_INCLUSION_MODES)
    min_days = optional_int(payload, "discipline_min_days_removed", 10, 0, 365)
    include_pending = payload.get("include_pending_investigations")
    if not isinstance(include_pending, bool):
        validation_error("Field 'include_pending_investigations' must be a boolean.")
    sped = payload.get("sped_requires_consent")
    if not isinstance(sped, bool):
        validation_error("Field 'sped_requires_consent' must be a boolean.")
    hearing_days = require_int(payload, "amendment_hearing_days", 1, 90)
    destruction_years = require_int(payload, "destruction_min_age_years", 1, 30)
    optout_days = require_int(payload, "directory_optout_grace_days", 1, 120)
    wait_days = require_int(payload, "notification_wait_days", 0, 30)

    if state_code in STORE.state_rules:
        err("ERR_DUPLICATE_STATE_RULE", 409, "A rule for this state already exists.")

    row = base_row(with_version=False)
    row.update({
        "state_code": state_code,
        "transfer_response_days": transfer_response_days,
        "discipline_inclusion_mode": mode,
        "discipline_min_days_removed": min_days,
        "include_pending_investigations": include_pending,
        "sped_requires_consent": sped,
        "amendment_hearing_days": hearing_days,
        "destruction_min_age_years": destruction_years,
        "directory_optout_grace_days": optout_days,
        "notification_wait_days": wait_days,
    })
    STORE.state_rules[state_code] = row
    return created(serialize.state_rule(row))


@bp.route(API_PREFIX + "/state-rules", methods=["GET"])
def list_state_rules():
    require_role(READ_STAFF)
    return paginate(list(STORE.state_rules.values()), serialize.state_rule)


@bp.route(API_PREFIX + "/state-rules/<state_code>", methods=["GET"])
def get_one_state_rule(state_code):
    row = get_state_rule(state_code)
    require_role(READ_STAFF)
    return ok(serialize.state_rule(row))


# --------------------------------------------------------------------------- #
# Districts
# --------------------------------------------------------------------------- #
UPPER_ALNUM = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")


def _valid_code(value, low, high):
    if len(value) < low or len(value) > high:
        return False
    return all(ch in UPPER_ALNUM for ch in value)


@bp.route(API_PREFIX + "/districts", methods=["POST"])
def create_district():
    require_role([ROLE_SYSTEM_ADMIN])
    payload = body()
    name = require_string(payload, "name")
    district_code = require_string(payload, "district_code")
    if not _valid_code(district_code, 2, 12):
        validation_error("Field 'district_code' must be 2-12 uppercase alphanumeric characters.")
    state_code = require_enum(payload, "state_code", STATE_CODES)
    get_state_rule(state_code)

    for row in STORE.districts.values():
        if row["district_code"] == district_code:
            err("ERR_DUPLICATE_DISTRICT_CODE", 409, "District code already registered.")

    row = base_row()
    row.update({
        "name": name,
        "district_code": district_code,
        "state_code": state_code,
        "open_request_count": 0,
    })
    STORE.districts[row["id"]] = row
    return created(serialize.district(row))


@bp.route(API_PREFIX + "/districts", methods=["GET"])
def list_districts():
    require_role(READ_STAFF)
    rows = list(STORE.districts.values())
    state_code = query_value("state_code")
    if state_code is not None:
        rows = [row for row in rows if row["state_code"] == state_code]
    return paginate(rows, serialize.district)


@bp.route(API_PREFIX + "/districts/<district_id>", methods=["GET"])
def get_one_district(district_id):
    row = get_district(district_id)
    require_role(READ_STAFF)
    return ok(serialize.district(row))


# --------------------------------------------------------------------------- #
# Inspection rooms
# --------------------------------------------------------------------------- #
@bp.route(API_PREFIX + "/inspection-rooms", methods=["POST"])
def create_room():
    require_role([ROLE_SYSTEM_ADMIN])
    payload = body()
    room_code = require_string(payload, "room_code")
    if len(room_code) < 2 or len(room_code) > 12:
        validation_error("Field 'room_code' must be 2-12 characters.")
    site_name = require_string(payload, "site_name")
    seats = require_int(payload, "seats", 1, 40)
    status = payload.get("status", "ACTIVE")
    if status is None:
        status = "ACTIVE"
    if status not in ROOM_STATUSES:
        validation_error("Field 'status' must be ACTIVE or CLOSED.")

    for row in STORE.inspection_rooms.values():
        if row["room_code"] == room_code:
            err("ERR_DUPLICATE_ROOM_CODE", 409, "Room code already registered.")

    row = base_row()
    row.update({"room_code": room_code, "site_name": site_name, "seats": seats,
                "status": status})
    STORE.inspection_rooms[row["id"]] = row
    return created(serialize.inspection_room(row))


@bp.route(API_PREFIX + "/inspection-rooms", methods=["GET"])
def list_rooms():
    require_role(ROOM_READ_ROLES)
    rows = list(STORE.inspection_rooms.values())
    status = query_value("status")
    if status is not None:
        rows = [row for row in rows if row["status"] == status]
    return paginate(rows, serialize.inspection_room)


@bp.route(API_PREFIX + "/inspection-rooms/<room_id>", methods=["GET"])
def get_one_room(room_id):
    row = get_room(room_id)
    require_role(ROOM_READ_ROLES)
    return ok(serialize.inspection_room(row))


@bp.route(API_PREFIX + "/inspection-rooms/<room_id>", methods=["PATCH"])
def patch_room(room_id):
    row = get_room(room_id)
    require_role([ROLE_SYSTEM_ADMIN])
    payload = body()
    status = require_enum(payload, "status", ROOM_STATUSES)
    seats = optional_int(payload, "seats", None, 1, 40)
    row["status"] = status
    if seats is not None:
        row["seats"] = seats
    touch(row)
    return ok(serialize.inspection_room(row))


# --------------------------------------------------------------------------- #
# Hearing officers
# --------------------------------------------------------------------------- #
@bp.route(API_PREFIX + "/hearing-officers", methods=["POST"])
def create_officer():
    require_role([ROLE_SYSTEM_ADMIN])
    payload = body()
    full_name = require_string(payload, "full_name")
    credential = require_enum(payload, "credential", CREDENTIALS)
    status = payload.get("status", "ACTIVE")
    if status is None:
        status = "ACTIVE"
    if status not in OFFICER_STATUSES:
        validation_error("Field 'status' must be ACTIVE or INACTIVE.")
    row = base_row()
    row.update({"full_name": full_name, "credential": credential, "status": status})
    STORE.hearing_officers[row["id"]] = row
    return created(serialize.hearing_officer(row))


@bp.route(API_PREFIX + "/hearing-officers", methods=["GET"])
def list_officers():
    require_role(OFFICER_READ_ROLES)
    rows = list(STORE.hearing_officers.values())
    status = query_value("status")
    if status is not None:
        rows = [row for row in rows if row["status"] == status]
    credential = query_value("credential")
    if credential is not None:
        rows = [row for row in rows if row["credential"] == credential]
    return paginate(rows, serialize.hearing_officer)


@bp.route(API_PREFIX + "/hearing-officers/<officer_id>", methods=["GET"])
def get_one_officer(officer_id):
    row = get_hearing_officer(officer_id)
    require_role(OFFICER_READ_ROLES)
    return ok(serialize.hearing_officer(row))


@bp.route(API_PREFIX + "/hearing-officers/<officer_id>", methods=["PATCH"])
def patch_officer(officer_id):
    row = get_hearing_officer(officer_id)
    require_role([ROLE_SYSTEM_ADMIN])
    payload = body()
    status = require_enum(payload, "status", OFFICER_STATUSES)
    credential = payload.get("credential")
    if credential is not None and credential not in CREDENTIALS:
        validation_error("Field 'credential' must be a supported credential.")
    row["status"] = status
    if credential is not None:
        row["credential"] = credential
    touch(row)
    return ok(serialize.hearing_officer(row))
