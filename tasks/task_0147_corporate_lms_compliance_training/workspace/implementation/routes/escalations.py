"""Escalation / expiry / recurrence sweep + EscalationEvent endpoints (PRD §3.8, §3.9)."""

from flask import Blueprint, request

import errors
import serializers as ser
from db import db
from middleware import authenticate, require_roles, ROLE_ADMIN, ROLE_MANAGER, ROLE_LEARNER
from response import object_response, array_response
from services.common import (
    stamp_create, touch, get_or_404, parse_pagination, paginate, report_set,
)
from services import calculations as calc
from services import enrollment_engine as engine
from timeutil import is_strictly_after, add_months

bp = Blueprint("escalations", __name__)


@bp.route("/escalations/run", methods=["POST"])
def run_escalations():
    p = authenticate()
    require_roles(p, [ROLE_ADMIN])
    now = db.now()

    expired_enrollment_ids = []
    expired_certificate_ids = []
    reset_enrollment_ids = []
    escalation_event_ids = []

    affected_employees = set()

    # 1) Identify overdue enrollments (NOT_STARTED/IN_PROGRESS, due_date strictly before now)
    overdue = []
    for e in db.enrollments.values():
        if e["status"] in ("NOT_STARTED", "IN_PROGRESS") and is_strictly_after(now, e["due_date"]):
            overdue.append(e)

    # 2) Expire those overdue enrollments
    for e in overdue:
        e["status"] = "EXPIRED"
        touch(e)
        expired_enrollment_ids.append(e["id"])
        affected_employees.add(e["employee_id"])

    # 3) Expire certificates past expires_at; recurrence-reset linked recurring enrollments
    for c in list(db.certificates.values()):
        if c["status"] != "ACTIVE":
            continue
        if c.get("expires_at") is None:
            continue
        if not is_strictly_after(now, c["expires_at"]):
            continue
        # expire the certificate
        c["status"] = "EXPIRED"
        touch(c)
        expired_certificate_ids.append(c["id"])
        affected_employees.add(c["employee_id"])

        # recurrence reset of the linked enrollment, if recurring and COMPLETED
        enr = db.enrollments.get(c["enrollment_id"])
        if enr is None:
            continue
        course = db.courses.get(enr["course_id"])
        if (course is not None and course.get("is_recurring")
                and enr["status"] == "COMPLETED"):
            enr["status"] = "NOT_STARTED"
            enr["cycle_index"] = enr["cycle_index"] + 1
            enr["certificate_id"] = None
            enr["final_grade"] = None
            enr["attempts_used"] = 0
            enr["best_score"] = None
            enr["latest_score"] = None
            if course.get("recurrence_months"):
                enr["due_date"] = add_months(now, course["recurrence_months"])
            touch(enr)
            reset_enrollment_ids.append(enr["id"])
            affected_employees.add(enr["employee_id"])

    # 4) Reconcile conserved quantities for all touched employees
    for emp_id in affected_employees:
        emp = db.employees.get(emp_id)
        if emp is not None:
            calc.recompute_employee_invariants(emp)
            calc.recompute_employee_compliance_score(emp)

    # 5) Emit an EscalationEvent for each overdue enrollment at tier >= 1
    for e in sorted(overdue, key=lambda r: (r.get("created_at") or "", r.get("id") or "")):
        tier = _tier_for_overdue(e, now)
        if tier >= 1:
            emp = db.employees.get(e["employee_id"])
            manager_id = emp.get("manager_id") if emp else None
            event = {
                "enrollment_id": e["id"],
                "employee_id": e["employee_id"],
                "manager_id": manager_id,
                "tier": tier,
                "days_overdue": _days_overdue_for(e, now),
                "acknowledged": False,
            }
            stamp_create(event, common_fields=False)  # id + created_at only
            db.escalation_events[event["id"]] = event
            escalation_event_ids.append(event["id"])

    result = {
        "expired_enrollment_ids": expired_enrollment_ids,
        "expired_certificate_ids": expired_certificate_ids,
        "reset_enrollment_ids": reset_enrollment_ids,
        "escalation_event_ids": escalation_event_ids,
    }
    return object_response(result)


def _days_overdue_for(enrollment, now):
    from timeutil import days_overdue
    return days_overdue(now, enrollment["due_date"])


def _tier_for_overdue(enrollment, now):
    d = _days_overdue_for(enrollment, now)
    if d <= 0:
        return 0
    if d <= 7:
        return 1
    if d <= 30:
        return 2
    return 3


# --- escalation events ----------------------------------------------------

@bp.route("/escalation-events", methods=["GET"])
def list_events():
    p = authenticate()
    require_roles(p, [ROLE_ADMIN, ROLE_MANAGER, ROLE_LEARNER])
    limit, offset = parse_pagination()
    items = list(db.escalation_events.values())
    for field in ("enrollment_id", "employee_id", "manager_id"):
        val = request.args.get(field)
        if val is not None:
            items = [ev for ev in items if ev.get(field) == val]
    ack = request.args.get("acknowledged")
    if ack is not None:
        want = ack.lower() in ("true", "1", "yes")
        items = [ev for ev in items if ev["acknowledged"] == want]
    tier = request.args.get("tier")
    if tier is not None:
        try:
            t = int(tier)
        except (TypeError, ValueError):
            raise errors.invalid_request("tier must be an integer")
        items = [ev for ev in items if ev["tier"] == t]

    # scope: learner sees own; manager sees reports' (by employee_id)
    if p.is_learner:
        items = [ev for ev in items if ev["employee_id"] == p.user_id]
    elif p.is_manager:
        scope = report_set(p.user_id)
        items = [ev for ev in items if ev["employee_id"] in scope]

    page, total = paginate(items, limit, offset)
    return array_response([ser.escalation_event(ev) for ev in page], limit, offset, total)


@bp.route("/escalation-events/<rid>", methods=["GET"])
def get_event(rid):
    p = authenticate()
    require_roles(p, [ROLE_ADMIN, ROLE_MANAGER, ROLE_LEARNER])
    rec = get_or_404(db.escalation_events, rid)
    if p.is_learner and rec["employee_id"] != p.user_id:
        raise errors.unauthorized("Out of scope")
    if p.is_manager and rec["employee_id"] not in report_set(p.user_id):
        raise errors.unauthorized("Out of scope")
    return object_response(ser.escalation_event(rec))


@bp.route("/escalation-events/<rid>/acknowledge", methods=["POST"])
def acknowledge_event(rid):
    p = authenticate()
    require_roles(p, [ROLE_ADMIN, ROLE_MANAGER])
    rec = get_or_404(db.escalation_events, rid)
    # manager may only acknowledge for own reports
    if p.is_manager and rec["employee_id"] not in report_set(p.user_id):
        raise errors.unauthorized("Out of scope")
    rec["acknowledged"] = True
    return object_response(ser.escalation_event(rec))
