"""Inspection requests, copy fees and supervised review appointments (PRD 3.7)."""

from datetime import timedelta

from flask import Blueprint

import serialize
from authz import RIGHTS_HOLDER_ROLES, requester_role_value, rights_holder_guard
from calc import certification_fee_cents, inspection_copy_fee_cents
from common import (API_PREFIX, ROLE_COMPLIANCE_OFFICER, ROLE_ELIGIBLE_STUDENT, ROLE_PARENT,
                    ROLE_RECORDS_CLERK, ROLE_RECORDS_OFFICER, ROLE_SYSTEM_ADMIN, STORE,
                    add_calendar_days, base_row, body, clock_now, err, optional_bool,
                    query_value, require_bool, require_enum, require_instant, require_int,
                    require_role, require_subset, touch, user_id, validation_error,
                    whole_minutes)
from derive import append_disclosure
from domain import (COMPONENT_TYPES, COMPONENT_TYPE_ORDER, FEE_TRANSACTION_TYPES,
                    INSPECTION_WINDOW_DAYS, ROOM_TURNOVER_BUFFER_MINUTES,
                    appointments_of_request, file_of_student, get_appointment,
                    get_inspection_request, get_room, get_student)
from response import created, ok, paginate

bp = Blueprint("inspections", __name__)

INSPECTION_READ_ROLES = [ROLE_SYSTEM_ADMIN, ROLE_RECORDS_CLERK, ROLE_RECORDS_OFFICER,
                         ROLE_COMPLIANCE_OFFICER, ROLE_PARENT, ROLE_ELIGIBLE_STUDENT]


# --------------------------------------------------------------------------- #
# Inspection requests
# --------------------------------------------------------------------------- #
@bp.route(API_PREFIX + "/students/<student_id>/inspection-requests", methods=["POST"])
def create_inspection_request(student_id):
    student = get_student(student_id)
    require_role(RIGHTS_HOLDER_ROLES)
    rights_holder_guard(student)
    payload = body()
    categories = require_subset(payload, "requested_categories",
                               COMPONENT_TYPES, COMPONENT_TYPE_ORDER)
    copies = optional_bool(payload, "copies_requested", False)

    file_row = file_of_student(student_id)
    base_fee = inspection_copy_fee_cents(file_row, categories, copies) if file_row else 0
    cert_fee = certification_fee_cents(base_fee)
    assessed = base_fee + cert_fee

    row = base_row()
    row.update({
        "student_id": student_id,
        "requester_user_id": user_id(),
        "requester_role": requester_role_value(),
        "requested_categories": categories,
        "copies_requested": copies,
        "status": "SUBMITTED",
        "statutory_inspection_due_at": add_calendar_days(row["created_at"],
                                                        INSPECTION_WINDOW_DAYS),
        "base_copy_fee_cents": base_fee,
        "certification_fee_cents": cert_fee,
        "fee_assessed_cents": assessed,
        "fee_collected_cents": 0,
        "fee_waived_cents": 0,
        "fee_outstanding_cents": assessed,
        "inspection_completed_at": None,
    })
    STORE.inspection_requests[row["id"]] = row
    return created(serialize.inspection_request(row))


@bp.route(API_PREFIX + "/students/<student_id>/inspection-requests", methods=["GET"])
def list_inspection_requests(student_id):
    get_student(student_id)
    require_role(INSPECTION_READ_ROLES)
    rows = [row for row in STORE.inspection_requests.values() if row["student_id"] == student_id]
    status = query_value("status")
    if status is not None:
        rows = [row for row in rows if row["status"] == status]
    requester_role = query_value("requester_role")
    if requester_role is not None:
        rows = [row for row in rows if row["requester_role"] == requester_role]
    return paginate(rows, serialize.inspection_request)


@bp.route(API_PREFIX + "/inspection-requests/<request_id>", methods=["GET"])
def get_one_inspection_request(request_id):
    row = get_inspection_request(request_id)
    require_role(INSPECTION_READ_ROLES)
    return ok(serialize.inspection_request(row))


# --------------------------------------------------------------------------- #
# Fee transactions
# --------------------------------------------------------------------------- #
@bp.route(API_PREFIX + "/inspection-requests/<request_id>/fee-payments", methods=["POST"])
def fee_payment(request_id):
    row = get_inspection_request(request_id)
    require_role([ROLE_RECORDS_CLERK, ROLE_RECORDS_OFFICER])
    payload = body()
    transaction_type = require_enum(payload, "fee_transaction_type", FEE_TRANSACTION_TYPES)
    amount = require_int(payload, "amount_cents", 1)

    if transaction_type in ("PAYMENT", "WAIVER") and amount > int(row["fee_outstanding_cents"]):
        err("ERR_FEE_OVERPAYMENT", 422, "The amount exceeds the outstanding balance.")

    if transaction_type == "PAYMENT":
        row["fee_collected_cents"] = int(row["fee_collected_cents"]) + amount
    elif transaction_type == "WAIVER":
        row["fee_waived_cents"] = int(row["fee_waived_cents"]) + amount
    else:
        row["fee_collected_cents"] = int(row["fee_collected_cents"]) - amount

    row["fee_outstanding_cents"] = (int(row["fee_assessed_cents"])
                                    - int(row["fee_collected_cents"])
                                    - int(row["fee_waived_cents"]))
    touch(row)
    return ok(serialize.inspection_request(row))


# --------------------------------------------------------------------------- #
# Review appointments
# --------------------------------------------------------------------------- #
def _room_conflict(room_id, start_at, end_at):
    """PRD 3.7: closed, buffer-padded occupancy over EVERY existing SCHEDULED or
    ATTENDED appointment in the room. A standing appointment of the same request
    only releases its interval once the new booking has been accepted, so it still
    participates in this test (unlike the hearing rule of PRD 3.8, which releases
    the replaced window before testing)."""
    buffer = timedelta(minutes=ROOM_TURNOVER_BUFFER_MINUTES)
    for row in STORE.review_appointments.values():
        if row["room_id"] != room_id:
            continue
        if row["status"] not in ("SCHEDULED", "ATTENDED"):
            continue
        if start_at <= row["end_at"] + buffer and end_at >= row["start_at"] - buffer:
            return True
    return False


@bp.route(API_PREFIX + "/inspection-requests/<request_id>/appointments", methods=["POST"])
def create_appointment(request_id):
    request_row = get_inspection_request(request_id)
    require_role([ROLE_RECORDS_OFFICER])
    payload = body()
    room_id = payload.get("room_id")
    if room_id is None or not isinstance(room_id, str) or room_id.strip() == "":
        validation_error("Field 'room_id' is required.")
    room = get_room(room_id)

    start_at = require_instant(payload, "start_at")
    end_at = require_instant(payload, "end_at")
    if end_at <= start_at:
        validation_error("Field 'end_at' must be strictly after 'start_at'.")
    expected = require_int(payload, "expected_inspection_request_version", 0)

    if expected != int(request_row["version"]):
        err("ERR_STALE_INSPECTION_REQUEST_VERSION", 412,
            "The supplied inspection request version is stale.")

    if request_row["status"] == "COMPLETED":
        err("ERR_INSPECTION_ALREADY_COMPLETED", 409, "The inspection is already completed.")
    if request_row["status"] == "EXPIRED":
        err("ERR_INSPECTION_EXPIRED", 409, "The inspection request has expired.")
    if request_row["status"] not in ("SUBMITTED", "SCHEDULED"):
        err("ERR_INSPECTION_EXPIRED", 409, "The inspection request cannot be scheduled.")

    if room["status"] != "ACTIVE":
        err("ERR_ROOM_CLOSED", 409, "The room is closed.")

    if _room_conflict(room_id, start_at, end_at):
        err("ERR_ROOM_DOUBLE_BOOKED", 409, "The room is already occupied in that window.")

    now = clock_now()
    if start_at < now or start_at > request_row["statutory_inspection_due_at"]:
        err("ERR_APPOINTMENT_OUTSIDE_STATUTORY_WINDOW", 422,
            "The appointment falls outside the statutory inspection window.")

    for existing in appointments_of_request(request_id):
        if existing["status"] == "SCHEDULED":
            existing["status"] = "SUPERSEDED"
            touch(existing)

    row = base_row()
    row.update({
        "inspection_request_id": request_id,
        "room_id": room_id,
        "start_at": start_at,
        "end_at": end_at,
        "duration_minutes": whole_minutes(start_at, end_at),
        "status": "SCHEDULED",
        "attended_at": None,
    })
    STORE.review_appointments[row["id"]] = row

    request_row["status"] = "SCHEDULED"
    touch(request_row)
    return created(serialize.review_appointment(row))


@bp.route(API_PREFIX + "/review-appointments", methods=["GET"])
def list_appointments():
    require_role(INSPECTION_READ_ROLES)
    rows = list(STORE.review_appointments.values())
    for name in ("inspection_request_id", "room_id", "status"):
        value = query_value(name)
        if value is not None:
            rows = [row for row in rows if row[name] == value]
    return paginate(rows, serialize.review_appointment)


@bp.route(API_PREFIX + "/review-appointments/<appointment_id>", methods=["GET"])
def get_one_appointment(appointment_id):
    row = get_appointment(appointment_id)
    require_role(INSPECTION_READ_ROLES)
    return ok(serialize.review_appointment(row))


@bp.route(API_PREFIX + "/review-appointments/<appointment_id>/attendance", methods=["POST"])
def record_attendance(appointment_id):
    row = get_appointment(appointment_id)
    require_role([ROLE_RECORDS_OFFICER])
    payload = body()
    attended = require_bool(payload, "attended")

    if row["status"] != "SCHEDULED":
        err("ERR_APPOINTMENT_NOT_SCHEDULED", 409, "The appointment is not scheduled.")

    request_row = STORE.inspection_requests.get(row["inspection_request_id"])
    if not attended:
        return ok(serialize.review_appointment(row))

    if (request_row is not None and request_row["copies_requested"]
            and int(request_row["fee_outstanding_cents"]) != 0):
        err("ERR_FEE_OUTSTANDING", 422, "The copy fee must be settled before attendance.")

    now = clock_now()
    row["status"] = "ATTENDED"
    row["attended_at"] = now
    touch(row)

    if request_row is not None:
        request_row["status"] = "COMPLETED"
        request_row["inspection_completed_at"] = now
        touch(request_row)
        append_disclosure(
            student_id=request_row["student_id"],
            disclosure_type="PARENT_INSPECTION",
            source_type="INSPECTION_REQUEST",
            source_id=request_row["id"],
            recipient_name=request_row["requester_user_id"],
            disclosed_categories=request_row["requested_categories"],
            page_count=0,
            logged_by_user_id=user_id(),
            legitimate_interest_note=None,
        )
    return ok(serialize.review_appointment(row))
