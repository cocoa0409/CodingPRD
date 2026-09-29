"""Renewal reviews: certification, notice issuance and the non-renewal cascade."""
from datetime import timedelta

from flask import Blueprint

import calc
import serialize
import validate as v
from db import db, insert, update, force_update, now_iso, today
from errors import ApiError
from middleware import authenticate, require_owner
from response import ok, created, ok_list
from services import effects, queries

bp = Blueprint("renewals", __name__)

RENEWAL_STATUSES = ("DRAFT", "SAP_CERTIFIED", "NOTICE_ISSUED", "ACKNOWLEDGED")
DECISIONS = ("PENDING", "RENEW", "NON_RENEW")
ISSUE_DECISIONS = ("RENEW", "NON_RENEW")

READ_ROLES = ["GradSchoolAdmin", "DepartmentAdmin", "FacultySupervisor", "StudentUser"]


def _student_of(decision):
    appointment = db.appointments.get(decision["appointment_id"])
    if appointment is None:
        return None
    return db.students.get(appointment["student_id"])


@bp.post("/renewal-decisions")
def create_decision():
    authenticate(["DepartmentAdmin"])
    body = v.body_dict()
    appointment_ref = v.ref_value(body, "appointment_id")
    appointment = (queries.appointment_or_404(appointment_ref)
                   if appointment_ref is not None else None)
    appointment_id = v.field_id(body, "appointment_id")

    department = db.departments.get(appointment["department_id"])
    notice_days = department["non_renewal_notice_days"] if department else 60
    end_date = calc.parse_iso(appointment["end_date"])
    window_open = end_date - timedelta(days=calc.RENEWAL_WINDOW_DAYS)
    notice_deadline = end_date - timedelta(days=notice_days)

    if today() < window_open:
        raise ApiError("ERR_RENEWAL_WINDOW_NOT_OPEN",
                       "The renewal window opens on %s" % window_open.isoformat())

    for existing in queries.renewals_of_appointment(appointment_id):
        if existing["status"] != "ACKNOWLEDGED":
            raise ApiError("ERR_RENEWAL_DECISION_EXISTS",
                           "An unfinished renewal review already exists for this appointment")

    row = insert(db.renewal_decisions, {
        "appointment_id": appointment_id,
        "renewal_window_open_date": window_open.isoformat(),
        "notice_deadline_date": notice_deadline.isoformat(),
        "decision": "PENDING",
        "sap_certified": False,
        "certified_by_user_id": None,
        "certified_at": None,
        "issued_by_user_id": None,
        "notice_sent_date": None,
        "acknowledged_at": None,
        "revision_count": 0,
        "status": "DRAFT",
    })
    return created(serialize.renewal(row))


@bp.get("/renewal-decisions/<decision_id>")
def read_decision(decision_id):
    actor_id, role = authenticate(READ_ROLES)
    decision = queries.renewal_or_404(decision_id)
    appointment = db.appointments.get(decision["appointment_id"])
    require_owner(actor_id, role,
                  appointment["student_id"] if appointment else None)
    return ok(serialize.renewal(decision))


@bp.get("/renewal-decisions")
def list_decisions():
    actor_id, role = authenticate(READ_ROLES)
    appointment_id = v.query_str("appointment_id")
    status = v.query_enum("status", RENEWAL_STATUSES)
    decision_filter = v.query_enum("decision", DECISIONS)

    rows = list(db.renewal_decisions.values())
    if role == "StudentUser":
        owned = set(a["id"] for a in db.appointments.values()
                    if a["student_id"] == actor_id)
        rows = [r for r in rows if r["appointment_id"] in owned]
    if appointment_id:
        rows = [r for r in rows if r["appointment_id"] == appointment_id]
    if status:
        rows = [r for r in rows if r["status"] == status]
    if decision_filter:
        rows = [r for r in rows if r["decision"] == decision_filter]
    page, meta = v.paginate(queries.by_created(rows))
    return ok_list([serialize.renewal(r) for r in page], meta)


@bp.post("/renewal-decisions/<decision_id>/certify-progress")
def certify_progress(decision_id):
    actor_id, _ = authenticate(["FacultySupervisor", "GradSchoolAdmin"])
    decision = queries.renewal_or_404(decision_id)
    if decision["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_RENEWAL_STATE",
                       "Only a DRAFT review may be certified, not %s" % decision["status"])
    student = _student_of(decision)
    if student is None:
        raise ApiError("ERR_STUDENT_NOT_FOUND", "The reviewed student no longer exists")
    if (student["sap_status"] != "SATISFACTORY"
            or student["cumulative_gpa"] < calc.MIN_RENEWAL_GPA):
        raise ApiError("ERR_SAP_NOT_SATISFACTORY",
                       "Certification requires SATISFACTORY standing and a cumulative GPA "
                       "of at least 3.00")
    update(decision,
           status="SAP_CERTIFIED",
           sap_certified=True,
           certified_by_user_id=actor_id,
           certified_at=now_iso())
    return ok(serialize.renewal(decision))


@bp.post("/renewal-decisions/<decision_id>/issue-notice")
def issue_notice(decision_id):
    actor_id, _ = authenticate(["DepartmentAdmin", "GradSchoolAdmin"])
    decision = queries.renewal_or_404(decision_id)
    body = v.body_dict()
    outcome = v.field_enum(body, "decision", ISSUE_DECISIONS)

    if decision["status"] != "SAP_CERTIFIED":
        raise ApiError("ERR_INVALID_RENEWAL_STATE",
                       "Only a SAP_CERTIFIED review may issue a notice, not %s"
                       % decision["status"])
    if decision["certified_by_user_id"] == actor_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The certifying user may not issue the notice")
    if outcome == "NON_RENEW" and today().isoformat() > decision["notice_deadline_date"]:
        raise ApiError("ERR_NOTICE_DEADLINE_PASSED",
                       "The non-renewal notice deadline %s has passed"
                       % decision["notice_deadline_date"])
    appointment = db.appointments.get(decision["appointment_id"])
    if appointment is None or appointment["lifecycle_status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_APPOINTMENT_STATE",
                       "The reviewed appointment must be ACTIVE to issue a notice")

    update(decision,
           status="NOTICE_ISSUED",
           decision=outcome,
           issued_by_user_id=actor_id,
           notice_sent_date=today().isoformat())

    if outcome == "NON_RENEW":
        force_update(appointment,
                     lifecycle_status="NON_RENEWAL_PENDING",
                     renewal_eligible=False)
        effects.cancel_successors(appointment)
    return ok(serialize.renewal(decision))


@bp.post("/renewal-decisions/<decision_id>/acknowledge")
def acknowledge_notice(decision_id):
    actor_id, role = authenticate(["StudentUser"])
    decision = queries.renewal_or_404(decision_id)
    appointment = db.appointments.get(decision["appointment_id"])
    require_owner(actor_id, role,
                  appointment["student_id"] if appointment else None)
    if decision["status"] != "NOTICE_ISSUED":
        raise ApiError("ERR_INVALID_RENEWAL_STATE",
                       "Only a NOTICE_ISSUED review may be acknowledged, not %s"
                       % decision["status"])
    update(decision, status="ACKNOWLEDGED", acknowledged_at=now_iso())
    return ok(serialize.renewal(decision))
