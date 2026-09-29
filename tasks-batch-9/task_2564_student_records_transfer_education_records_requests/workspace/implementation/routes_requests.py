"""Inter-district records requests: intake, validation, snapshot, release, denial."""

from flask import Blueprint

import serialize
from calc import (discipline_inclusion_set, disclosure_packet_page_count, packet_component_types,
                  records_request_window)
from common import (API_PREFIX, READ_STAFF, ROLE_RECEIVING_REGISTRAR, ROLE_RECORDS_OFFICER,
                    STORE, base_row, body, clock_now, err, optional_bool, optional_enum,
                    query_bool, query_value, require_bool, require_enum, require_int,
                    require_role, require_role as _require_role, touch, user_id, user_role,
                    validation_error)
from derive import (append_disclosure, bubble_validated_requests, recompute_district_open_count,
                    refresh_eligibility)
from domain import (DENIAL_REASONS, OPEN_REQUEST_STATUSES, REQUEST_PRIORITIES,
                    TRANSMISSION_METHODS, components_of_file, file_of_student, get_district,
                    get_records_request, get_student)
from response import created, ok, paginate

bp = Blueprint("records_requests", __name__)

TERMINAL_STATUSES = ("RELEASED", "DENIED")


def _resolve_reference(payload, name, resolver):
    value = payload.get(name)
    if value is None or not isinstance(value, str) or value.strip() == "":
        validation_error("Field '%s' is required." % name)
    return resolver(value)


def _student_file(request_row):
    return file_of_student(request_row["student_id"])


def _apply_window(request_row):
    days, due_at = records_request_window(request_row)
    request_row["statutory_days_allowed"] = days
    request_row["statutory_due_at"] = due_at


@bp.route(API_PREFIX + "/records-requests", methods=["POST"])
def create_records_request():
    # Role permission is the gate immediately after path resolution (PRD 2.1); body
    # references resolve next, before any payload-dependent authorization.
    role = require_role([ROLE_RECEIVING_REGISTRAR, ROLE_RECORDS_OFFICER])
    payload = body()
    student = _resolve_reference(payload, "student_id", get_student)
    requesting = _resolve_reference(payload, "requesting_district_id", get_district)
    responding = _resolve_reference(payload, "responding_district_id", get_district)

    if role == ROLE_RECEIVING_REGISTRAR and requesting["id"] != user_id():
        err("ERR_DISTRICT_MISMATCH", 403,
            "A receiving registrar may only file in the name of their own district.")

    priority = optional_enum(payload, "request_priority", REQUEST_PRIORITIES, "STANDARD")
    includes_sped = optional_bool(payload, "includes_special_education", False)
    consent = optional_bool(payload, "sped_consent_on_file", False)
    authorization_reference = payload.get("authorization_reference")
    if authorization_reference is not None and not isinstance(authorization_reference, str):
        validation_error("Field 'authorization_reference' must be a string or null.")

    for row in STORE.records_requests.values():
        if (row["student_id"] == student["id"]
                and row["requesting_district_id"] == requesting["id"]
                and row["status"] in OPEN_REQUEST_STATUSES):
            err("ERR_DUPLICATE_ACTIVE_REQUEST", 409,
                "An active request from that district already exists for this student.")

    row = base_row()
    row.update({
        "student_id": student["id"],
        "requesting_district_id": requesting["id"],
        "responding_district_id": responding["id"],
        "request_priority": priority,
        "includes_special_education": includes_sped,
        "sped_consent_on_file": consent,
        "authorization_reference": authorization_reference,
        "authorization_verified": False,
        "status": "RECEIVED",
        "received_at": clock_now(),
        "statutory_days_allowed": None,
        "statutory_due_at": None,
        "is_overdue": False,
        "packet_status": "NONE",
        "packet_page_count": None,
        "included_incident_count": None,
        "withheld_incident_count": None,
        "receiving_state_inclusion_count": None,
        "reopen_count": 0,
        "denial_reason": None,
        "transmission_method": None,
        "released_at": None,
    })
    _apply_window(row)
    STORE.records_requests[row["id"]] = row
    recompute_district_open_count(responding["id"])
    return created(serialize.records_request(row))


@bp.route(API_PREFIX + "/records-requests", methods=["GET"])
def list_records_requests():
    require_role(READ_STAFF)
    rows = list(STORE.records_requests.values())
    for name in ("student_id", "requesting_district_id", "responding_district_id", "status"):
        value = query_value(name)
        if value is not None:
            rows = [row for row in rows if row[name] == value]
    is_overdue = query_bool("is_overdue")
    if is_overdue is not None:
        rows = [row for row in rows if row["is_overdue"] == is_overdue]
    return paginate(rows, serialize.records_request)


@bp.route(API_PREFIX + "/records-requests/<request_id>", methods=["GET"])
def get_one_records_request(request_id):
    row = get_records_request(request_id)
    require_role(READ_STAFF)
    return ok(serialize.records_request(row))


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #
@bp.route(API_PREFIX + "/records-requests/<request_id>/validate", methods=["POST"])
def validate_records_request(request_id):
    row = get_records_request(request_id)
    require_role([ROLE_RECORDS_OFFICER])
    payload = body()
    verified = require_bool(payload, "authorization_verified")

    if row["status"] in TERMINAL_STATUSES:
        err("ERR_REQUEST_TERMINAL", 409, "The request is terminal.")
    if row["status"] != "RECEIVED":
        err("ERR_REQUEST_NOT_RECEIVED", 409, "The request is not in RECEIVED.")
    if not verified or row["authorization_reference"] is None:
        err("ERR_AUTHORIZATION_NOT_VERIFIED", 422,
            "Enrollment authorization could not be verified.")

    row["authorization_verified"] = True
    row["status"] = "VALIDATED"
    _apply_window(row)
    touch(row)
    recompute_district_open_count(row["responding_district_id"])
    bubble_validated_requests(row["student_id"])
    return ok(serialize.records_request(row))


# --------------------------------------------------------------------------- #
# Packet snapshot
# --------------------------------------------------------------------------- #
@bp.route(API_PREFIX + "/records-requests/<request_id>/mark-ready", methods=["POST"])
def mark_ready(request_id):
    row = get_records_request(request_id)
    require_role([ROLE_RECORDS_OFFICER])
    payload = body()
    expected = require_int(payload, "expected_cumulative_file_version", 0)

    file_row = _student_file(row)
    if file_row is None or expected != int(file_row["version"]):
        err("ERR_STALE_CUMULATIVE_FILE_VERSION", 412,
            "The supplied cumulative file version is stale.")

    if row["status"] in TERMINAL_STATUSES:
        err("ERR_REQUEST_TERMINAL", 409, "The request is terminal.")
    if row["status"] != "ASSEMBLING":
        err("ERR_REQUEST_NOT_ASSEMBLING", 409, "The request is not assembling.")

    if file_row["assembly_status"] != "COMPLETE":
        err("ERR_FILE_NOT_COMPLETE", 409, "The cumulative file is not complete.")

    student = STORE.students.get(row["student_id"])
    responding = STORE.districts.get(row["responding_district_id"])
    rule = STORE.state_rules.get(responding["state_code"]) if responding else None
    needs_consent = bool(rule) and bool(rule["sped_requires_consent"]) and (
        bool(student["has_iep"]) or bool(row["includes_special_education"]))
    if needs_consent and not row["sped_consent_on_file"]:
        err("ERR_SPED_CONSENT_REQUIRED", 422,
            "Signed special-education consent is required before release.")

    included, withheld, receiving = discipline_inclusion_set(row)
    row["included_incident_count"] = included
    row["withheld_incident_count"] = withheld
    row["receiving_state_inclusion_count"] = receiving
    row["packet_page_count"] = disclosure_packet_page_count(file_row)
    row["packet_status"] = "SNAPSHOT"
    row["status"] = "READY_FOR_RELEASE"
    touch(row)

    file_row["last_packet_snapshot_at"] = clock_now()
    touch(file_row)
    recompute_district_open_count(row["responding_district_id"])
    return ok(serialize.records_request(row))


# --------------------------------------------------------------------------- #
# Release
# --------------------------------------------------------------------------- #
@bp.route(API_PREFIX + "/records-requests/<request_id>/release", methods=["POST"])
def release_records_request(request_id):
    row = get_records_request(request_id)
    require_role([ROLE_RECORDS_OFFICER])
    payload = body()
    method = require_enum(payload, "transmission_method", TRANSMISSION_METHODS)

    if row["status"] in TERMINAL_STATUSES:
        err("ERR_REQUEST_TERMINAL", 409, "The request is terminal.")
    if row["status"] != "READY_FOR_RELEASE":
        err("ERR_REQUEST_NOT_READY", 409, "The request is not ready for release.")

    for demand in STORE.legal_demands.values():
        if (demand["student_id"] == row["student_id"]
                and demand["demand_type"] == "EX_PARTE_ORDER"
                and demand["status"] in ("RECEIVED", "NOTIFIED")):
            err("ERR_EX_PARTE_HOLD_ACTIVE", 409,
                "An unexecuted ex parte order freezes this file.")

    file_row = _student_file(row)
    if file_row is not None and row["denial_reason"] != "COURT_SEALED":
        for component in components_of_file(file_row["id"]):
            if (component["status"] == "EXCLUDED"
                    and component["exclusion_reason"] == "SEALED_BY_COURT"):
                err("ERR_COURT_SEALED_COMPONENT", 409,
                    "Court-sealed material may not leave the district.")

    row["status"] = "RELEASED"
    row["released_at"] = clock_now()
    row["transmission_method"] = method
    touch(row)

    requesting = STORE.districts.get(row["requesting_district_id"])
    categories = packet_component_types(file_row) if file_row is not None else []
    append_disclosure(
        student_id=row["student_id"],
        disclosure_type="INTERDISTRICT_TRANSFER",
        source_type="RECORDS_REQUEST",
        source_id=row["id"],
        recipient_name=requesting["name"] if requesting else None,
        disclosed_categories=categories,
        page_count=row["packet_page_count"] or 0,
        logged_by_user_id=user_id(),
        legitimate_interest_note=None,
    )

    student = STORE.students.get(row["student_id"])
    if student is not None and student["enrollment_status"] == "WITHDRAWN":
        student["enrollment_status"] = "TRANSFERRED_OUT"
        touch(student)
    recompute_district_open_count(row["responding_district_id"])
    return ok(serialize.records_request(row))


# --------------------------------------------------------------------------- #
# Denial
# --------------------------------------------------------------------------- #
@bp.route(API_PREFIX + "/records-requests/<request_id>/deny", methods=["POST"])
def deny_records_request(request_id):
    row = get_records_request(request_id)
    require_role([ROLE_RECORDS_OFFICER])
    payload = body()
    reason = require_enum(payload, "denial_reason", DENIAL_REASONS)

    if row["status"] in TERMINAL_STATUSES:
        err("ERR_REQUEST_TERMINAL", 409, "The request is terminal.")
    if row["status"] not in ("RECEIVED", "VALIDATED", "ASSEMBLING"):
        err("ERR_REQUEST_NOT_ASSEMBLING", 409, "The request may no longer be denied.")

    row["status"] = "DENIED"
    row["denial_reason"] = reason
    touch(row)
    recompute_district_open_count(row["responding_district_id"])
    return ok(serialize.records_request(row))
