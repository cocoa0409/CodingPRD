"""Enrollment endpoints: get, activate, withdraw (cascade), standing overrides,
and per-enrollment child listings."""
from flask import Blueprint, request

import clock
import db
from errors import raise_err
from middleware import route, ALL_ROLES
from response import success_object, success_list
from serializers import (
    ser_enrollment, ser_notice, ser_curriculum_plan, ser_attendance_entry,
    ser_portfolio, ser_course_credit, ser_test_registration, ser_coop_enrollment,
)
from services import core
from services import coop as coop_svc
from services import compliance as compliance_svc
from validation import get_body, opt_string, req_enum, STANDINGS

bp = Blueprint("enrollments", __name__)

_CHAIN = (("enrollment", "enrollment_id", db.enrollments),)


@bp.route("/enrollments/<enrollment_id>", methods=["GET"])
@route(ALL_ROLES, ownership=("enrollment", "enrollment_id"), parent_chain=_CHAIN)
def get_enrollment(enrollment_id):
    return success_object(ser_enrollment(db.enrollments[enrollment_id]))


@bp.route("/enrollments/<enrollment_id>/activate", methods=["POST"])
@route(["Registrar"], parent_chain=_CHAIN)
def activate_enrollment(enrollment_id):
    en = db.enrollments[enrollment_id]
    if en["enrollment_status"] != "REGISTERED":
        raise_err("ERR_INVALID_STATE_TRANSITION", "Enrollment is not REGISTERED")
    year = core.year_of_enrollment(en)
    if year["status"] != "OPEN":
        raise_err("ERR_ACADEMIC_YEAR_NOT_OPEN", "Academic year is not OPEN")
    has_ack_notice = any(
        n["enrollment_id"] == enrollment_id and n["status"] == "ACKNOWLEDGED"
        for n in db.notices.values()
    )
    if not has_ack_notice:
        raise_err("ERR_NOTICE_NOT_ACKNOWLEDGED",
                  "Activation requires an ACKNOWLEDGED notice of intent")
    plan = next(
        (p for p in db.curriculum_plans.values() if p["enrollment_id"] == enrollment_id),
        None,
    )
    if plan is None or plan["status"] != "APPROVED":
        raise_err("ERR_PLAN_NOT_APPROVED",
                  "Activation requires an APPROVED curriculum plan")
    en["enrollment_status"] = "ACTIVE"
    en["activated_at"] = clock.now_iso()
    core.touch(en)
    return success_object(ser_enrollment(en))


@bp.route("/enrollments/<enrollment_id>/withdraw", methods=["POST"])
@route(["Parent", "Registrar"], ownership=("enrollment", "enrollment_id"),
       parent_chain=_CHAIN)
def withdraw_enrollment(enrollment_id):
    en = db.enrollments[enrollment_id]
    if en["enrollment_status"] not in ("REGISTERED", "ACTIVE"):
        raise_err("ERR_INVALID_STATE_TRANSITION",
                  "Only REGISTERED or ACTIVE enrollments may be withdrawn")
    en["enrollment_status"] = "WITHDRAWN"
    en["withdrawn_at"] = clock.now_iso()
    core.touch(en)

    # Cascade: notice of intent
    for n in db.notices.values():
        if n["enrollment_id"] == enrollment_id and n["status"] in (
                "DRAFT", "FILED", "ACKNOWLEDGED", "RETURNED"):
            n["status"] = "WITHDRAWN"
            core.touch(n)
    # Cascade: curriculum plan
    for p in db.curriculum_plans.values():
        if p["enrollment_id"] == enrollment_id and p["status"] != "ARCHIVED":
            p["status"] = "ARCHIVED"
            core.touch(p)
    # Cascade: portfolio
    for pf in db.portfolios.values():
        if pf["enrollment_id"] == enrollment_id and pf["status"] in (
                "DRAFT", "SUBMITTED", "REMEDIATION_REQUIRED"):
            pf["status"] = "WITHDRAWN"
            core.touch(pf)
    # Cascade: test registrations still REGISTERED
    for reg in db.test_registrations.values():
        if reg["enrollment_id"] == enrollment_id and reg["status"] == "REGISTERED":
            reg["status"] = "CANCELLED"
            core.touch(reg)
            sess = db.exam_sessions.get(reg["exam_session_id"])
            if sess is not None:
                sess["seats_taken"] -= 1
                core.touch(sess)
    # Cascade: co-op enrollments
    classes_to_promote = []
    for ce in list(db.coop_enrollments.values()):
        if ce["enrollment_id"] != enrollment_id:
            continue
        if ce["status"] == "CONFIRMED":
            cls = db.coop_classes.get(ce["coop_class_id"])
            coop_svc.drop_coop_enrollment(ce, "PARENT_INITIATED", run_promotion=False)
            if cls is not None:
                classes_to_promote.append(cls)
        elif ce["status"] == "WAITLISTED":
            coop_svc.cancel_waitlisted(ce)
    seen = set()
    for cls in classes_to_promote:
        if cls["id"] in seen:
            continue
        seen.add(cls["id"])
        coop_svc.waitlist_promotion(cls)

    return success_object(ser_enrollment(en))


@bp.route("/enrollments/<enrollment_id>/standing-overrides", methods=["POST"])
@route(["AcademicDirector"], parent_chain=_CHAIN)
def set_standing_override(enrollment_id):
    en = db.enrollments[enrollment_id]
    body = get_body()
    standing = req_enum(body, "standing", STANDINGS)
    reason = body.get("reason")
    if not isinstance(reason, str) or reason == "":
        raise_err("ERR_INVALID_REQUEST", "reason is required")
    en["standing_locked"] = True
    prev = en["compliance_standing"]
    en["compliance_standing"] = standing
    core.touch(en)
    if standing == "NONCOMPLIANT" and prev != "NONCOMPLIANT":
        coop_svc.noncompliant_cascade(en)
    return success_object(ser_enrollment(en))


@bp.route("/enrollments/<enrollment_id>/standing-overrides/clear", methods=["POST"])
@route(["AcademicDirector"], parent_chain=_CHAIN)
def clear_standing_override(enrollment_id):
    en = db.enrollments[enrollment_id]
    en["standing_locked"] = False
    year = core.year_of_enrollment(en)
    target = compliance_svc.derive_standing(en, year)
    en["compliance_standing"] = target
    core.touch(en)
    if target == "NONCOMPLIANT":
        coop_svc.noncompliant_cascade(en)
    return success_object(ser_enrollment(en))


# --- per-enrollment child listings -----------------------------------------

def _list_child(enrollment_id, table, serializer, status_filterable=False):
    recs = [r for r in table.values() if r.get("enrollment_id") == enrollment_id]
    if status_filterable:
        status = request.args.get("status")
        if status:
            recs = [r for r in recs if r["status"] == status]
    recs = core.sorted_by_created(recs)
    page, limit, offset, total = core.paginate(recs)
    return success_list([serializer(r) for r in page], limit, offset, total)


@bp.route("/enrollments/<enrollment_id>/notices", methods=["GET"])
@route(ALL_ROLES, ownership=("enrollment", "enrollment_id"), parent_chain=_CHAIN)
def list_notices(enrollment_id):
    return _list_child(enrollment_id, db.notices, ser_notice)


@bp.route("/enrollments/<enrollment_id>/curriculum-plans", methods=["GET"])
@route(ALL_ROLES, ownership=("enrollment", "enrollment_id"), parent_chain=_CHAIN)
def list_plans(enrollment_id):
    return _list_child(enrollment_id, db.curriculum_plans, ser_curriculum_plan)


@bp.route("/enrollments/<enrollment_id>/attendance-entries", methods=["GET"])
@route(ALL_ROLES, ownership=("enrollment", "enrollment_id"), parent_chain=_CHAIN)
def list_attendance(enrollment_id):
    return _list_child(enrollment_id, db.attendance_entries, ser_attendance_entry,
                       status_filterable=True)


@bp.route("/enrollments/<enrollment_id>/portfolios", methods=["GET"])
@route(ALL_ROLES, ownership=("enrollment", "enrollment_id"), parent_chain=_CHAIN)
def list_portfolios(enrollment_id):
    return _list_child(enrollment_id, db.portfolios, ser_portfolio)


@bp.route("/enrollments/<enrollment_id>/course-credits", methods=["GET"])
@route(ALL_ROLES, ownership=("enrollment", "enrollment_id"), parent_chain=_CHAIN)
def list_course_credits(enrollment_id):
    return _list_child(enrollment_id, db.course_credits, ser_course_credit,
                       status_filterable=True)


@bp.route("/enrollments/<enrollment_id>/test-registrations", methods=["GET"])
@route(ALL_ROLES, ownership=("enrollment", "enrollment_id"), parent_chain=_CHAIN)
def list_test_registrations(enrollment_id):
    return _list_child(enrollment_id, db.test_registrations, ser_test_registration)


@bp.route("/enrollments/<enrollment_id>/coop-enrollments", methods=["GET"])
@route(ALL_ROLES, ownership=("enrollment", "enrollment_id"), parent_chain=_CHAIN)
def list_coop_enrollments(enrollment_id):
    return _list_child(enrollment_id, db.coop_enrollments, ser_coop_enrollment,
                       status_filterable=True)
