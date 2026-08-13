"""ClinicAppointment endpoints (PRD §3.7)."""

from datetime import timedelta

from flask import request

import db
from db import clock, parse_iso, format_iso, stamp_new, touch
from errors import (
    ApiError,
    ERR_APPOINTMENT_NOT_BOOKED,
    ERR_APPOINTMENT_NOT_FOUND,
    ERR_APPOINTMENT_OUTSIDE_SESSION,
    ERR_APPOINTMENT_TIME_CONFLICT,
    ERR_SESSION_FULL,
    ERR_SESSION_NOT_FOUND,
    ERR_SESSION_NOT_OPEN,
    ERR_STALE_SESSION_VERSION,
    ERR_STUDENT_NOT_ACTIVE,
    ERR_STUDENT_NOT_FOUND,
    ERR_VALIDATION,
)
from middleware import require_roles
from response import success_object, success_list
from services.evaluation import (
    VACCINE_CODES,
    appointment_view,
    deficiency_codes,
    reevaluate_student,
    record_view,
)
from services.validate import (
    parse_pagination, paginate, req_datetime, req_enum, req_string, require_body,
)

ALL_ROLES = ("HealthClerk", "SchoolNurse", "DistrictHealthOfficer", "RegistryCoordinator")


def _recompute_booked_count(session):
    session["booked_count"] = sum(
        1 for a in db.clinic_appointments.values()
        if a["clinic_session_id"] == session["id"] and a["status"] == "BOOKED"
    )


def register(app):

    @app.post("/api/clinic-sessions/<sid>/appointments")
    def book_appointment(sid):
        require_roles("HealthClerk")
        # Path existence (left to right)
        session = db.clinic_sessions.get(sid)
        if session is None:
            raise ApiError(ERR_SESSION_NOT_FOUND, "Clinic session not found.", 404)

        body = require_body(request.get_json(silent=True))

        # Body FK existence — student_id
        student_id = body.get("student_id")
        student = None
        if isinstance(student_id, str):
            student = db.students.get(student_id)
        if student_id is not None and isinstance(student_id, str) and student is None:
            raise ApiError(ERR_STUDENT_NOT_FOUND, "Student not found.", 404)

        # OCC on session (priority 4)
        expected = body.get("expected_clinic_session_version")
        if expected is not None and isinstance(expected, int) and not isinstance(expected, bool):
            if expected != session["version"]:
                raise ApiError(
                    ERR_STALE_SESSION_VERSION,
                    "expected_clinic_session_version does not equal the ClinicSession's current version.",
                    412,
                )

        # State admissibility (priority 5): session must be OPEN; student not WITHDRAWN
        if session["status"] != "OPEN":
            raise ApiError(
                ERR_SESSION_NOT_OPEN,
                "booking requires the session to be in OPEN.",
                409,
            )
        if student is not None and student["status"] == "WITHDRAWN":
            raise ApiError(
                ERR_STUDENT_NOT_ACTIVE,
                "Operation targets a Student with status WITHDRAWN.",
                409,
            )

        # Schema (needed for business checks below)
        if student_id is None:
            raise ApiError(ERR_VALIDATION, "Missing required field: student_id", 400)
        vaccine_code = req_enum(body, "vaccine_code", VACCINE_CODES)
        start_time = req_datetime(body, "start_time")
        end_time = req_datetime(body, "end_time")
        if "expected_clinic_session_version" not in body:
            raise ApiError(
                ERR_VALIDATION,
                "Missing required field: expected_clinic_session_version",
                400,
            )
        if isinstance(body["expected_clinic_session_version"], bool) or not isinstance(
            body["expected_clinic_session_version"], int
        ):
            raise ApiError(
                ERR_VALIDATION,
                "Field expected_clinic_session_version must be an integer.",
                400,
            )
        if end_time <= start_time:
            raise ApiError(
                ERR_VALIDATION,
                "end_time must be strictly after start_time.",
                400,
            )

        # 7b: interval within session window
        session_start = parse_iso(session["session_date"])
        session_end = session_start + timedelta(minutes=session["duration_minutes"])
        if start_time < session_start or end_time > session_end:
            raise ApiError(
                ERR_APPOINTMENT_OUTSIDE_SESSION,
                "Appointment interval does not lie within the session window.",
                422,
            )

        # 7c: no overlap with same student's other BOOKED appointments (half-open)
        for appt in db.clinic_appointments.values():
            if appt["student_id"] != student_id or appt["status"] != "BOOKED":
                continue
            a_start = parse_iso(appt["start_time"])
            a_end = parse_iso(appt["end_time"])
            # half-open overlap: start_time < a_end AND end_time > a_start
            if start_time < a_end and end_time > a_start:
                raise ApiError(
                    ERR_APPOINTMENT_TIME_CONFLICT,
                    "Appointment overlaps another BOOKED appointment of the same student.",
                    409,
                )

        # Priority 9: capacity
        if session["booked_count"] >= session["capacity"]:
            raise ApiError(
                ERR_SESSION_FULL,
                "ClinicSession.booked_count >= capacity at booking time.",
                409,
            )

        appt = {
            "clinic_session_id": session["id"],
            "student_id": student_id,
            "vaccine_code": vaccine_code,
            "start_time": format_iso(start_time),
            "end_time": format_iso(end_time),
            "status": "BOOKED",
        }
        stamp_new(appt)
        db.clinic_appointments[appt["id"]] = appt

        _recompute_booked_count(session)
        touch(session)
        return success_object(appointment_view(appt), status=201)

    @app.get("/api/clinic-sessions/<sid>/appointments")
    def list_session_appointments(sid):
        require_roles(*ALL_ROLES)
        session = db.clinic_sessions.get(sid)
        if session is None:
            raise ApiError(ERR_SESSION_NOT_FOUND, "Clinic session not found.", 404)
        limit, offset = parse_pagination(request.args)
        status = request.args.get("status")
        items = [a for a in db.clinic_appointments.values() if a["clinic_session_id"] == sid]
        if status is not None:
            items = [a for a in items if a["status"] == status]
        items.sort(key=lambda a: (a["created_at"], a["id"]))
        page, total = paginate(items, limit, offset)
        return success_list([appointment_view(a) for a in page], limit, offset, total)

    @app.get("/api/clinic-appointments/<aid>")
    def get_appointment(aid):
        require_roles(*ALL_ROLES)
        appt = db.clinic_appointments.get(aid)
        if appt is None:
            raise ApiError(ERR_APPOINTMENT_NOT_FOUND, "Appointment not found.", 404)
        return success_object(appointment_view(appt))

    @app.get("/api/students/<sid>/clinic-appointments")
    def list_student_appointments(sid):
        require_roles(*ALL_ROLES)
        student = db.students.get(sid)
        if student is None:
            raise ApiError(ERR_STUDENT_NOT_FOUND, "Student not found.", 404)
        limit, offset = parse_pagination(request.args)
        status = request.args.get("status")
        items = [a for a in db.clinic_appointments.values() if a["student_id"] == sid]
        if status is not None:
            items = [a for a in items if a["status"] == status]
        items.sort(key=lambda a: (a["created_at"], a["id"]))
        page, total = paginate(items, limit, offset)
        return success_list([appointment_view(a) for a in page], limit, offset, total)

    @app.post("/api/clinic-appointments/<aid>/cancel")
    def cancel_appointment(aid):
        require_roles("HealthClerk")
        appt = db.clinic_appointments.get(aid)
        if appt is None:
            raise ApiError(ERR_APPOINTMENT_NOT_FOUND, "Appointment not found.", 404)
        if appt["status"] != "BOOKED":
            raise ApiError(
                ERR_APPOINTMENT_NOT_BOOKED,
                "cancel requires the appointment to be in BOOKED.",
                409,
            )
        appt["status"] = "CANCELLED"
        touch(appt)
        session = db.clinic_sessions.get(appt["clinic_session_id"])
        if session is not None:
            _recompute_booked_count(session)
            touch(session)
        return success_object(appointment_view(appt))

    @app.post("/api/clinic-appointments/<aid>/complete")
    def complete_appointment(aid):
        require_roles("SchoolNurse")
        appt = db.clinic_appointments.get(aid)
        if appt is None:
            raise ApiError(ERR_APPOINTMENT_NOT_FOUND, "Appointment not found.", 404)
        if appt["status"] != "BOOKED":
            raise ApiError(
                ERR_APPOINTMENT_NOT_BOOKED,
                "complete requires the appointment to be in BOOKED.",
                409,
            )
        appt["status"] = "COMPLETED"
        touch(appt)

        # Create the VERIFIED CLINIC-source ImmunizationRecord
        student_id = appt["student_id"]
        vaccine_code = appt["vaccine_code"]
        existing = [
            r for r in db.immunization_records.values()
            if r["student_id"] == student_id
            and r["vaccine_code"] == vaccine_code
            and r["status"] != "VOIDED"
        ]
        next_dose = (max(r["dose_number"] for r in existing) + 1) if existing else 1
        record = {
            "student_id": student_id,
            "vaccine_code": vaccine_code,
            "dose_number": next_dose,
            "administered_date": appt["start_time"],
            "source": "CLINIC",
            "clinic_appointment_id": appt["id"],
            "status": "VERIFIED",
            "verified_by_user_id": None,
        }
        stamp_new(record)
        db.immunization_records[record["id"]] = record

        # Re-evaluate student
        student = db.students.get(student_id)
        if student is not None:
            reevaluate_student(student)

        # Recompute session booked_count
        session = db.clinic_sessions.get(appt["clinic_session_id"])
        if session is not None:
            _recompute_booked_count(session)
            touch(session)
        return success_object(appointment_view(appt))

    @app.get("/api/clinic-appointments/<aid>/immunization-records")
    def list_appointment_records(aid):
        require_roles(*ALL_ROLES)
        appt = db.clinic_appointments.get(aid)
        if appt is None:
            raise ApiError(ERR_APPOINTMENT_NOT_FOUND, "Appointment not found.", 404)
        limit, offset = parse_pagination(request.args)
        items = [
            r for r in db.immunization_records.values()
            if r.get("clinic_appointment_id") == aid
        ]
        items.sort(key=lambda r: (r["created_at"], r["id"]))
        page, total = paginate(items, limit, offset)
        return success_list([record_view(r) for r in page], limit, offset, total)
