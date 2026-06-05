"""Enrollment appointment routes: grant (create) and get."""
from __future__ import annotations

from flask import Blueprint

import db
from errors import err
from middleware import authenticate, require_roles
from response import ok_object
from services import helpers as h
from services import serialize
from services.entities import new_common

bp = Blueprint("appointments", __name__)


@bp.post("/appointments")
def create_appointment():
    authenticate()
    require_roles("Registrar", "Advisor")
    body = h.get_json_body()

    term_id = h.require_string(body, "term_id")
    student_id = h.require_string(body, "student_id")
    priority_tier = h.require_int(body, "priority_tier")
    window_opens_at = h.require_string(body, "window_opens_at")
    max_credit_hours = h.require_int(body, "max_credit_hours")

    if priority_tier < 1:
        raise err("ERR_VALIDATION", "priority_tier must be >= 1")
    if max_credit_hours < 1:
        raise err("ERR_VALIDATION", "max_credit_hours must be >= 1")

    # existence checks (Term, then Student)
    h.get_term(term_id)
    h.get_student(student_id)

    rec = new_common("EnrollmentAppointment")
    rec.update({
        "term_id": term_id,
        "student_id": student_id,
        "priority_tier": priority_tier,
        "window_opens_at": window_opens_at,
        "max_credit_hours": max_credit_hours,
        "enrolled_credit_hours": 0,
    })
    db.appointments[rec["id"]] = rec
    return ok_object(serialize.appointment(rec), 201)


@bp.get("/appointments/<appointment_id>")
def get_appointment(appointment_id):
    authenticate()
    require_roles("Registrar", "Advisor", "Student")
    rec = h.get_appointment(appointment_id)
    return ok_object(serialize.appointment(rec), 200)
