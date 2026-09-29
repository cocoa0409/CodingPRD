"""Test centres, examination authorizations and seat bookings (PRD 3.1, 3.5)."""
from flask import Blueprint

import calc
import cascade
import db
import guards
import schemas
from errors import ApiError
from middleware import endpoint, role
from response import created, ok
from util import add_days, add_minutes
from validate import (body, opt_enum, opt_str, q_enum, q_str, req_dt, req_enum,
                      req_id, req_int, req_str, req_str_list, req_state_code)

bp = Blueprint("exams", __name__)

CENTER_STATUSES = ("OPEN", "SUSPENDED")
AUTHORIZATION_STATUSES = ("APPROVED_TO_SIT", "SCHEDULED", "PASSED", "FAILED",
                          "EXPIRED", "CANCELLED")
APPOINTMENT_STATUSES = ("SCHEDULED", "COMPLETED", "CANCELLED_BY_CANDIDATE",
                        "CANCELLED_BY_BOARD")
EXAM_CODES = ("PE_CIVIL", "PE_MECHANICAL", "PE_ELECTRICAL")
CENTER_ROLES = ("Applicant", "BoardSecretary", "BoardLicensingOfficer",
                "TestingService")
AUTHORIZATION_ROLES = ("Applicant", "BoardReviewer", "BoardLicensingOfficer",
                       "BoardSecretary", "TestingService")


# ----------------------------------------------------------------- test centres
@bp.post("/test-centers")
@endpoint("BoardSecretary")
def create_test_center():
    data = body()
    name = req_str(data, "name", max_len=120)
    state_code = req_state_code(data, "state_code")
    seat_labels = req_str_list(data, "seat_labels", min_items=1, max_items=20,
                               distinct=True)
    status = opt_enum(data, "status", CENTER_STATUSES, default="OPEN")
    center = db.insert("test_centers", {
        "name": name,
        "state_code": state_code,
        "seat_labels": list(seat_labels),
        "seat_count": len(seat_labels),
        "seats_committed": 0,
        "seats_available": len(seat_labels),
        "status": status,
    })
    return created(schemas.view(center, schemas.TEST_CENTER))


@bp.get("/test-centers/<test_center_id>")
@endpoint(*CENTER_ROLES)
def read_test_center(test_center_id):
    center = schemas.fetch("test_centers", test_center_id, "ERR_TEST_CENTER_NOT_FOUND")
    return ok(schemas.view(center, schemas.TEST_CENTER))


@bp.get("/test-centers")
@endpoint(*CENTER_ROLES)
def list_test_centers():
    state_code = q_str("state_code")
    status = q_enum("status", CENTER_STATUSES)

    def keep(row):
        if state_code is not None and row["state_code"] != state_code:
            return False
        if status is not None and row["status"] != status:
            return False
        return True

    return schemas.listing("test_centers", schemas.TEST_CENTER, keep)


# ------------------------------------------------------------- authorizations
def _fetch_authorization(authorization_id):
    return schemas.fetch("exam_authorizations", authorization_id,
                         "ERR_EXAM_AUTHORIZATION_NOT_FOUND")


@bp.get("/exam-authorizations/<exam_authorization_id>")
@endpoint(*AUTHORIZATION_ROLES)
def read_authorization(exam_authorization_id):
    authorization = _fetch_authorization(exam_authorization_id)
    return ok(schemas.view(authorization, schemas.EXAM_AUTHORIZATION))


@bp.get("/exam-authorizations")
@endpoint(*AUTHORIZATION_ROLES)
def list_authorizations():
    application_id = q_str("application_id")
    status = q_enum("status", AUTHORIZATION_STATUSES)
    exam_code = q_enum("exam_code", EXAM_CODES)

    def keep(row):
        if application_id is not None and row["application_id"] != application_id:
            return False
        if status is not None and row["status"] != status:
            return False
        if exam_code is not None and row["exam_code"] != exam_code:
            return False
        return True

    return schemas.listing("exam_authorizations", schemas.EXAM_AUTHORIZATION, keep)


@bp.post("/exam-authorizations/<exam_authorization_id>/score")
@endpoint("TestingService")
def report_score(exam_authorization_id):
    data = body()
    raw_score = req_int(data, "raw_score", minimum=0, maximum=100)
    administered_at = req_dt(data, "administered_at")
    transmission_id = req_str(data, "ncees_transmission_id")
    authorization = _fetch_authorization(exam_authorization_id)
    if authorization["status"] != "SCHEDULED":
        raise ApiError("ERR_EXAM_STATE_INVALID",
                       "only a SCHEDULED authorization may be scored")
    sitting = None
    for appointment in calc.appointments_of_authorization(authorization["id"]):
        if appointment["status"] == "SCHEDULED" and appointment["window_end"] <= db.clock():
            sitting = appointment
            break
    if sitting is None:
        raise ApiError("ERR_EXAM_STATE_INVALID",
                       "no finished sitting is on record for this authorization")
    if raw_score >= calc.PASSING_SCORE:
        db.write(authorization, status="PASSED", result="PASS",
                 raw_score=raw_score, ncees_transmission_id=transmission_id)
    else:
        db.write(authorization, status="FAILED", result="FAIL",
                 raw_score=raw_score, ncees_transmission_id=transmission_id,
                 retake_eligible_at=add_days(administered_at, calc.RETAKE_WAIT_DAYS))
    cascade.release_appointment(sitting, "COMPLETED")
    return ok(schemas.view(authorization, schemas.EXAM_AUTHORIZATION))


@bp.post("/exam-authorizations/<exam_authorization_id>/retake")
@endpoint("Applicant")
def retake(exam_authorization_id):
    authorization = _fetch_authorization(exam_authorization_id)
    application = db.get("applications", authorization["application_id"])
    guards.owned_by_caller(application["engineer_id"])
    if authorization["status"] != "FAILED":
        raise ApiError("ERR_EXAM_STATE_INVALID",
                       "only a FAILED authorization may be re-armed")
    now = db.clock()
    if authorization["authorization_expires_at"] is not None and now >= authorization["authorization_expires_at"]:
        raise ApiError("ERR_AUTHORIZATION_EXPIRED",
                       "the authorization envelope has lapsed")
    eligible_at = authorization["retake_eligible_at"]
    if eligible_at is not None and now < eligible_at:
        raise ApiError("ERR_RETAKE_WAITING_PERIOD",
                       "the retake waiting period has not run")
    if authorization["attempt_number"] >= calc.MAX_ATTEMPTS:
        raise ApiError("ERR_ATTEMPT_LIMIT_REACHED",
                       "no further examination attempts remain")
    db.write(authorization, status="APPROVED_TO_SIT",
             attempt_number=authorization["attempt_number"] + 1,
             raw_score=None, result="PENDING", retake_eligible_at=None)
    return ok(schemas.view(authorization, schemas.EXAM_AUTHORIZATION))


# --------------------------------------------------------------- appointments
@bp.post("/exam-appointments")
@endpoint("Applicant")
def create_appointment():
    data = body()
    authorization_id = req_id(data, "exam_authorization_id")
    test_center_id = req_id(data, "test_center_id")
    seat_label = req_str(data, "seat_label")
    window_start = req_dt(data, "window_start")
    window_end = req_dt(data, "window_end")
    authorization = _fetch_authorization(authorization_id)
    center = schemas.fetch("test_centers", test_center_id,
                           "ERR_TEST_CENTER_NOT_FOUND")
    if seat_label not in center["seat_labels"]:
        raise ApiError("ERR_SEAT_LABEL_NOT_FOUND",
                       "the centre does not offer that seat label")
    application = db.get("applications", authorization["application_id"])
    guards.owned_by_caller(application["engineer_id"])
    if authorization["status"] != "APPROVED_TO_SIT":
        raise ApiError("ERR_EXAM_STATE_INVALID",
                       "the authorization is not open for booking")
    if application["status"] != "EXAM_APPROVED":
        raise ApiError("ERR_APPLICATION_STATE_INVALID",
                       "the file does not stand in EXAM_APPROVED")
    if add_minutes(window_start, calc.EXAM_WINDOW_MINUTES) != window_end:
        raise ApiError("ERR_EXAM_WINDOW_LENGTH_INVALID",
                       "an examination window is exactly 480 minutes long")
    for existing in db.all_rows("exam_appointments"):
        if existing["test_center_id"] != center["id"]:
            continue
        if existing["seat_label"] != seat_label:
            continue
        if existing["status"] != "SCHEDULED":
            continue
        if calc.seat_conflict(existing, window_start, window_end):
            raise ApiError("ERR_SEAT_WINDOW_CONFLICT",
                           "the seat is already reserved across that window")
    committed = sum(1 for a in db.all_rows("exam_appointments")
                    if a["test_center_id"] == center["id"] and a["status"] == "SCHEDULED")
    if center["status"] != "OPEN" or (center["seat_count"] - committed) < 1:
        raise ApiError("ERR_NO_SEAT_AVAILABLE", "the centre has no seat available")
    if authorization["authorization_expires_at"] is not None and db.clock() >= authorization["authorization_expires_at"]:
        raise ApiError("ERR_AUTHORIZATION_EXPIRED",
                       "the authorization envelope has lapsed")
    appointment = db.insert("exam_appointments", {
        "exam_authorization_id": authorization["id"],
        "test_center_id": center["id"],
        "seat_label": seat_label,
        "window_start": window_start,
        "window_end": window_end,
        "status": "SCHEDULED",
    })
    db.write(authorization, status="SCHEDULED")
    calc.refresh_seat_ledger(center)
    return created(schemas.view(appointment, schemas.EXAM_APPOINTMENT))


@bp.get("/exam-appointments/<exam_appointment_id>")
@endpoint(*CENTER_ROLES)
def read_appointment(exam_appointment_id):
    appointment = schemas.fetch("exam_appointments", exam_appointment_id,
                                "ERR_EXAM_APPOINTMENT_NOT_FOUND")
    return ok(schemas.view(appointment, schemas.EXAM_APPOINTMENT))


@bp.get("/exam-appointments")
@endpoint(*CENTER_ROLES)
def list_appointments():
    authorization_id = q_str("exam_authorization_id")
    test_center_id = q_str("test_center_id")
    status = q_enum("status", APPOINTMENT_STATUSES)

    def keep(row):
        if authorization_id is not None and row["exam_authorization_id"] != authorization_id:
            return False
        if test_center_id is not None and row["test_center_id"] != test_center_id:
            return False
        if status is not None and row["status"] != status:
            return False
        return True

    return schemas.listing("exam_appointments", schemas.EXAM_APPOINTMENT, keep)


@bp.post("/exam-appointments/<exam_appointment_id>/cancel")
@endpoint("Applicant", "BoardSecretary")
def cancel_appointment(exam_appointment_id):
    data = body()
    opt_str(data, "reason", max_len=None)
    appointment = schemas.fetch("exam_appointments", exam_appointment_id,
                                "ERR_EXAM_APPOINTMENT_NOT_FOUND")
    authorization = db.get("exam_authorizations", appointment["exam_authorization_id"])
    application = db.get("applications", authorization["application_id"])
    if role() == "Applicant":
        guards.owned_by_caller(application["engineer_id"])
    if appointment["status"] != "SCHEDULED":
        raise ApiError("ERR_EXAM_STATE_INVALID",
                       "only a SCHEDULED appointment may be cancelled")
    if db.clock() >= appointment["window_start"]:
        raise ApiError("ERR_EXAM_STATE_INVALID",
                       "a sitting already begun cannot be cancelled")
    terminal = ("CANCELLED_BY_CANDIDATE" if role() == "Applicant"
                else "CANCELLED_BY_BOARD")
    cascade.release_appointment(appointment, terminal)
    if authorization["status"] == "SCHEDULED":
        db.write(authorization, status="APPROVED_TO_SIT")
    return ok(schemas.view(appointment, schemas.EXAM_APPOINTMENT))
