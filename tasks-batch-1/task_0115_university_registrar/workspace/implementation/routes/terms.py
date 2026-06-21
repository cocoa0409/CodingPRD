"""Term routes: create, get, status transition, and reverse-reachability lists."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import err
from middleware import authenticate, parse_pagination, require_roles
from response import ok_array, ok_object
from services import helpers as h
from services import serialize
from services.entities import new_common, touch

bp = Blueprint("terms", __name__)

ALL_ROLES = ("Registrar", "Advisor", "Student", "Bursar")

# Term lifecycle transitions (PRD §3.1).
TERM_TRANSITIONS = {
    "PLANNING": {"REGISTRATION_OPEN"},
    "REGISTRATION_OPEN": {"IN_SESSION"},
    "IN_SESSION": {"CLOSED"},
    "CLOSED": set(),
}
TERM_STATUSES = {"PLANNING", "REGISTRATION_OPEN", "IN_SESSION", "CLOSED"}


@bp.post("/terms")
def create_term():
    authenticate()
    require_roles("Registrar")
    body = h.get_json_body()

    name = h.require_string(body, "name")
    registration_opens_at = h.require_string(body, "registration_opens_at")
    add_deadline = h.require_string(body, "add_deadline")
    drop_deadline = h.require_string(body, "drop_deadline")
    withdraw_deadline = h.require_string(body, "withdraw_deadline")
    per_credit_cost_cents = h.require_int(body, "per_credit_cost_cents")
    refund_full_pct = h.optional_number(body, "refund_full_pct", 1.0)
    refund_partial_pct = h.optional_number(body, "refund_partial_pct", 0.5)

    rec = new_common("Term")
    rec.update({
        "name": name,
        "registration_opens_at": registration_opens_at,
        "add_deadline": add_deadline,
        "drop_deadline": drop_deadline,
        "withdraw_deadline": withdraw_deadline,
        "refund_full_pct": refund_full_pct,
        "refund_partial_pct": refund_partial_pct,
        "per_credit_cost_cents": per_credit_cost_cents,
        "status": "PLANNING",
    })
    db.terms[rec["id"]] = rec
    return ok_object(serialize.term(rec), 201)


@bp.get("/terms/<term_id>")
def get_term(term_id):
    authenticate()
    require_roles(*ALL_ROLES)
    rec = h.get_term(term_id)
    return ok_object(serialize.term(rec), 200)


@bp.post("/terms/<term_id>/status")
def transition_term(term_id):
    authenticate()
    require_roles("Registrar")
    body = h.get_json_body()
    to_status = h.require_enum(body, "to_status", TERM_STATUSES)

    term = h.get_term(term_id)
    cur = term["status"]
    if to_status not in TERM_TRANSITIONS.get(cur, set()):
        raise err("ERR_INVALID_STATE", f"Transition {cur} -> {to_status} is not defined")

    # PLANNING -> REGISTRATION_OPEN requires at least one section for the term.
    if cur == "PLANNING" and to_status == "REGISTRATION_OPEN":
        has_section = any(s["term_id"] == term_id for s in db.sections.values())
        if not has_section:
            raise err("ERR_TERM_HAS_NO_SECTIONS", "Term cannot open registration without at least one section")

    term["status"] = to_status
    touch(term)
    return ok_object(serialize.term(term), 200)


@bp.get("/terms/<term_id>/sections")
def list_term_sections(term_id):
    authenticate()
    require_roles(*ALL_ROLES)
    limit, offset = parse_pagination()
    h.get_term(term_id)

    course_id = request.args.get("course_id")
    status = request.args.get("status")
    recs = [
        s for s in db.sections.values()
        if s["term_id"] == term_id
        and (course_id is None or s["course_id"] == course_id)
        and (status is None or s["status"] == status)
    ]
    recs = h.order_by_created(recs)
    page, total = h.paginate(recs, limit, offset)
    return ok_array([serialize.section(s) for s in page], limit, offset, total, 200)


@bp.get("/terms/<term_id>/enrollments")
def list_term_enrollments(term_id):
    authenticate()
    require_roles("Registrar", "Advisor", "Bursar")
    limit, offset = parse_pagination()
    h.get_term(term_id)

    student_id = request.args.get("student_id")
    registration_status = request.args.get("registration_status")
    recs = [
        e for e in db.enrollments.values()
        if e["term_id"] == term_id
        and (student_id is None or e["student_id"] == student_id)
        and (registration_status is None or e["registration_status"] == registration_status)
    ]
    recs = h.order_by_created(recs)
    page, total = h.paginate(recs, limit, offset)
    return ok_array([serialize.enrollment(e) for e in page], limit, offset, total, 200)


@bp.get("/terms/<term_id>/appointments")
def list_term_appointments(term_id):
    authenticate()
    require_roles("Registrar", "Advisor")
    limit, offset = parse_pagination()
    h.get_term(term_id)

    recs = [a for a in db.appointments.values() if a["term_id"] == term_id]
    recs = h.order_by_created(recs)
    page, total = h.paginate(recs, limit, offset)
    return ok_array([serialize.appointment(a) for a in page], limit, offset, total, 200)
