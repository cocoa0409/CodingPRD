"""ServiceDelivery endpoints (PRD section 3.8)."""

from datetime import timedelta

import db
from errors import (
    ApiError,
    ERR_INVALID_STATE,
    ERR_PROVIDER_NOT_CERTIFIED_IN_STATE,
    ERR_NOT_SPECIAL_ED_STUDENT,
    ERR_SCHEDULE_TIME_IN_PAST,
    ERR_MARK_MISSED_TOO_EARLY,
    ERR_INVALID_REQUEST,
)
from middleware import authenticate
from response import success_obj, success_list
from routes import make_blueprint
from util import (
    body_json, check_shape, pagination_params, paginate, apply_filters,
    require_fk, exist_body_fks, parse_dt,
)

bp = make_blueprint("service_deliveries")

SERVICE_TYPES = ["SPEECH_THERAPY", "OCCUPATIONAL_THERAPY", "COUNSELING", "RESOURCE_ROOM"]
READ_ROLES = ["PlatformAdmin", "SpecialEdCoordinator"]
STUDENT_LIST_ROLES = ["PlatformAdmin", "SpecialEdCoordinator", "EnrollmentOfficer"]
PROVIDER_LIST_ROLES = ["PlatformAdmin", "SpecialEdCoordinator", "AcademicDirector"]


@bp.post("/service-deliveries")
def create_service_delivery():
    authenticate(["SpecialEdCoordinator"])
    body = body_json()
    # Body FK existence (priority 4): student and provider.
    exist_body_fks(body, {
        "student_id": ("students", "student"),
        "provider_id": ("teachers", "provider"),
    })
    student = db.get("students", body.get("student_id")) if body.get("student_id") else None
    provider = db.get("teachers", body.get("provider_id")) if body.get("provider_id") else None
    # State admissibility (priority 5): student must be ENROLLED.
    if student is not None and student["enrollment_status"] != "ENROLLED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "service delivery requires an ENROLLED student")
    if student is not None and provider is not None:
        # Provider certification (priority 8) reports ahead of the
        # special-education flag rule (priority 15).
        district = db.get("districts", student["district_of_residence_id"])
        state_code = district["state_code"] if district else None
        if state_code not in provider["certification_state_codes"]:
            raise ApiError(ERR_PROVIDER_NOT_CERTIFIED_IN_STATE, 422,
                           "provider is not certified in the student's district state")
        if not student["special_education_flag"]:
            raise ApiError(ERR_NOT_SPECIAL_ED_STUDENT, 422,
                           "student does not have an active IEP")
    # Input shape (priority 16).
    check_shape(body, {
        "student_id": {"type": "string", "required": True},
        "service_type": {"type": "enum", "required": True, "values": SERVICE_TYPES},
        "scheduled_at": {"type": "datetime", "required": True},
        "duration_minutes": {"type": "integer", "required": True, "min": 15},
        "provider_id": {"type": "string", "required": True},
    })
    delivery = db.new_entity("service_deliveries", {
        "student_id": body["student_id"],
        "service_type": body["service_type"],
        "scheduled_at": body["scheduled_at"],
        "duration_minutes": body["duration_minutes"],
        "provider_id": body["provider_id"],
        "delivery_status": "SCHEDULED",
        "delivered_at": None,
    })
    return success_obj(db.public(delivery), 201)


@bp.get("/service-deliveries/<did>")
def get_service_delivery(did):
    authenticate(READ_ROLES)
    delivery = require_fk("service_deliveries", did, "service delivery")
    return success_obj(db.public(delivery), 200)


@bp.get("/students/<sid>/service-deliveries")
def list_student_service_deliveries(sid):
    authenticate(STUDENT_LIST_ROLES)
    student = require_fk("students", sid, "student")
    limit, offset = pagination_params()
    items = [d for d in db.all_of("service_deliveries")
             if d["student_id"] == student["id"]]
    items = apply_filters(items, ["delivery_status"])
    page, total, has_more = paginate(items, limit, offset)
    return success_list([db.public(d) for d in page], limit, offset, total, has_more)


@bp.get("/teachers/<tid>/service-deliveries")
def list_provider_service_deliveries(tid):
    authenticate(PROVIDER_LIST_ROLES)
    teacher = require_fk("teachers", tid, "teacher")
    limit, offset = pagination_params()
    items = [d for d in db.all_of("service_deliveries")
             if d["provider_id"] == teacher["id"]]
    items = apply_filters(items, ["delivery_status"])
    page, total, has_more = paginate(items, limit, offset)
    return success_list([db.public(d) for d in page], limit, offset, total, has_more)


@bp.post("/service-deliveries/<did>/mark-delivered")
def mark_delivered(did):
    authenticate(["SpecialEdCoordinator"])
    delivery = require_fk("service_deliveries", did, "service delivery")
    if delivery["delivery_status"] != "SCHEDULED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "only a SCHEDULED service delivery can be marked delivered")
    student = db.get("students", delivery["student_id"])
    if student is None or student["enrollment_status"] != "ENROLLED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "marking delivered requires the student to still be ENROLLED")
    delivery["delivery_status"] = "DELIVERED"
    delivery["delivered_at"] = db.fmt_ts(db.now())
    db.touch(delivery)
    return success_obj(db.public(delivery), 200)


@bp.post("/service-deliveries/<did>/mark-missed")
def mark_missed(did):
    authenticate(["SpecialEdCoordinator"])
    delivery = require_fk("service_deliveries", did, "service delivery")
    if delivery["delivery_status"] != "SCHEDULED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "only a SCHEDULED service delivery can be marked missed")
    session_end = (parse_dt(delivery["scheduled_at"], "scheduled_at")
                   + timedelta(minutes=delivery["duration_minutes"]))
    if not db.now() > session_end:
        raise ApiError(ERR_MARK_MISSED_TOO_EARLY, 422,
                       "the scheduled session has not yet ended on the logical clock")
    delivery["delivery_status"] = "MISSED"
    db.touch(delivery)
    return success_obj(db.public(delivery), 200)


@bp.post("/service-deliveries/<did>/cancel")
def cancel_delivery(did):
    authenticate(["SpecialEdCoordinator"])
    delivery = require_fk("service_deliveries", did, "service delivery")
    if delivery["delivery_status"] != "SCHEDULED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "only a SCHEDULED service delivery can be cancelled")
    delivery["delivery_status"] = "CANCELLED"
    db.touch(delivery)
    return success_obj(db.public(delivery), 200)


@bp.post("/service-deliveries/<did>/reschedule")
def reschedule_delivery(did):
    authenticate(["SpecialEdCoordinator"])
    delivery = require_fk("service_deliveries", did, "service delivery")
    if delivery["delivery_status"] != "MISSED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "only a MISSED service delivery can be rescheduled")
    body = body_json()
    # Temporal rule (priority 12) ahead of generic input shape (priority 16):
    # a parseable-but-past instant is the 422; a missing/malformed one is 400.
    if "scheduled_at" in body and body["scheduled_at"] is not None:
        new_time = parse_dt(body["scheduled_at"], "scheduled_at")
        if not new_time > db.now():
            raise ApiError(ERR_SCHEDULE_TIME_IN_PAST, 422,
                           "scheduled_at must be strictly in the future")
    check_shape(body, {
        "scheduled_at": {"type": "datetime", "required": True},
    })
    delivery["scheduled_at"] = body["scheduled_at"]
    delivery["delivery_status"] = "SCHEDULED"
    db.touch(delivery)
    return success_obj(db.public(delivery), 200)
