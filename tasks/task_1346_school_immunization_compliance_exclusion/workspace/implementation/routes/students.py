"""Student endpoints (PRD §3.1)."""

from datetime import timedelta

from flask import request

import db
from db import clock, parse_iso, format_iso, stamp_new, touch
from errors import ApiError, ERR_STUDENT_NOT_FOUND, ERR_STUDENT_NOT_ACTIVE
from middleware import require_roles
from response import success_object, success_list
from services.evaluation import (
    GRADES,
    applicable_requirements,
    deficiency_codes,
    evaluate_requirement,
    next_dose_due_date,
    reevaluate_student,
    student_view,
)
from services.validate import (
    parse_pagination, paginate, req_datetime, req_enum, req_string,
    require_body,
)

ALL_ROLES = ("HealthClerk", "SchoolNurse", "DistrictHealthOfficer", "RegistryCoordinator")


def register(app):

    @app.post("/api/students")
    def create_student():
        require_roles("HealthClerk")
        body = require_body(request.get_json(silent=True))
        legal_name = req_string(body, "legal_name")
        dob = req_datetime(body, "date_of_birth")
        grade = req_enum(body, "grade", GRADES)
        school_code = req_string(body, "school_code")
        enrollment_date = req_datetime(body, "enrollment_date")

        provisional_deadline = enrollment_date + timedelta(days=30)
        student = {
            "legal_name": legal_name,
            # Normalize DOB to midnight UTC per PRD §3.1
            "date_of_birth": format_iso(dob.replace(hour=0, minute=0, second=0, microsecond=0)),
            "grade": grade,
            "school_code": school_code,
            "enrollment_date": format_iso(enrollment_date),
            "status": "ENROLLED_PROVISIONAL",
            "provisional_deadline": format_iso(provisional_deadline),
            "deficiency_vaccine_codes": [],
        }
        stamp_new(student)
        db.students[student["id"]] = student
        # Initial evaluation populates deficiency_vaccine_codes
        student["deficiency_vaccine_codes"] = deficiency_codes(student)
        return success_object(student_view(student), status=201)

    @app.get("/api/students")
    def list_students():
        require_roles(*ALL_ROLES)
        limit, offset = parse_pagination(request.args)
        school_code = request.args.get("school_code")
        status = request.args.get("status")
        grade = request.args.get("grade")
        items = list(db.students.values())
        if school_code is not None:
            items = [s for s in items if s["school_code"] == school_code]
        if status is not None:
            items = [s for s in items if s["status"] == status]
        if grade is not None:
            items = [s for s in items if s["grade"] == grade]
        items.sort(key=lambda s: (s["created_at"], s["id"]))
        page, total = paginate(items, limit, offset)
        return success_list([student_view(s) for s in page], limit, offset, total)

    @app.get("/api/students/<sid>")
    def get_student(sid):
        require_roles(*ALL_ROLES)
        student = db.students.get(sid)
        if student is None:
            raise ApiError(ERR_STUDENT_NOT_FOUND, "Student not found.", 404)
        return success_object(student_view(student))

    @app.post("/api/students/<sid>/withdraw")
    def withdraw_student(sid):
        require_roles("HealthClerk")
        student = db.students.get(sid)
        if student is None:
            raise ApiError(ERR_STUDENT_NOT_FOUND, "Student not found.", 404)
        if student["status"] == "WITHDRAWN":
            # Terminal state machine: no WITHDRAWN->WITHDRAWN transition declared.
            raise ApiError(
                ERR_STUDENT_NOT_ACTIVE,
                "Operation targets a Student with status WITHDRAWN.",
                409,
            )
        # Cascade: cancel every BOOKED appointment for this student.
        affected_sessions = set()
        for appt in db.clinic_appointments.values():
            if appt["student_id"] == student["id"] and appt["status"] == "BOOKED":
                appt["status"] = "CANCELLED"
                touch(appt)
                affected_sessions.add(appt["clinic_session_id"])
        for sess_id in affected_sessions:
            session = db.clinic_sessions.get(sess_id)
            if session is None:
                continue
            session["booked_count"] = sum(
                1 for a in db.clinic_appointments.values()
                if a["clinic_session_id"] == sess_id and a["status"] == "BOOKED"
            )
            touch(session)
        student["status"] = "WITHDRAWN"
        touch(student)
        return success_object(student_view(student))

    @app.get("/api/students/<sid>/compliance")
    def get_student_compliance(sid):
        require_roles(*ALL_ROLES)
        student = db.students.get(sid)
        if student is None:
            raise ApiError(ERR_STUDENT_NOT_FOUND, "Student not found.", 404)
        rows = []
        for req in applicable_requirements(student):
            local_ok = evaluate_requirement(student, req, "LOCAL_RECORDS")
            reconciled_ok = evaluate_requirement(student, req, "REGISTRY_RECONCILED")
            due = next_dose_due_date(student, req)
            rows.append({
                "vaccine_code": req["vaccine_code"],
                "doses_required": req["doses_required"],
                "satisfied_local": local_ok,
                "satisfied_reconciled": reconciled_ok,
                "local_status": "SATISFIED" if local_ok else "NOT_SATISFIED",
                "reconciled_status": "SATISFIED" if reconciled_ok else "NOT_SATISFIED",
                "next_dose_due_date": format_iso(due) if due is not None else None,
            })
        return success_object({
            "student_id": student["id"],
            "student_status": student["status"],
            "requirements": rows,
        })
