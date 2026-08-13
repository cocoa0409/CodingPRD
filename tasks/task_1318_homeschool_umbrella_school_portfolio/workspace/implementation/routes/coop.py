"""Co-op class and co-op enrollment endpoints."""
from datetime import date as _date

from flask import Blueprint, request

import clock
import db
from errors import raise_err
from middleware import route, ALL_ROLES
from response import success_object, success_list
from serializers import ser_coop_class, ser_coop_enrollment
from services import core
from services import coop as coop_svc
from services import fees as fees_svc
from validation import (
    get_body, req_string, req_enum, req_int, req_date, MEETING_DAYS,
)

bp = Blueprint("coop", __name__)

_CLASS_CHAIN = (("coop_class", "class_id", db.coop_classes),)
_CE_CHAIN = (("coop_enrollment", "coop_enrollment_id", db.coop_enrollments),)


def _parse_date(d):
    y, m, dd = (int(x) for x in d.split("-"))
    return _date(y, m, dd)


@bp.route("/academic-years/<year_id>/coop-classes", methods=["POST"])
@route(["Registrar"], parent_chain=(("academic_year", "year_id", db.academic_years),))
def create_class(year_id):
    body = get_body()
    title = req_string(body, "title")
    subject = req_string(body, "subject")
    grade_min = req_int(body, "grade_min", lo=0, hi=12)
    grade_max = req_int(body, "grade_max", lo=0, hi=12)
    if grade_max < grade_min:
        raise_err("ERR_INVALID_REQUEST", "grade_max must be >= grade_min")
    meeting_day = req_enum(body, "meeting_day", MEETING_DAYS)
    meeting_start = req_int(body, "meeting_start_minutes", lo=0, hi=1439)
    meeting_end = req_int(body, "meeting_end_minutes", lo=0, hi=1440)
    if meeting_end <= meeting_start:
        raise_err("ERR_INVALID_REQUEST", "meeting_end_minutes must be > meeting_start_minutes")
    start_date = req_date(body, "start_date")
    end_date = req_date(body, "end_date")
    if _parse_date(end_date) < _parse_date(start_date):
        raise_err("ERR_INVALID_REQUEST", "end_date must be >= start_date")
    capacity = req_int(body, "capacity", lo=1)
    fee_base_cents = req_int(body, "fee_base_cents", lo=0)
    materials_fee_cents = req_int(body, "materials_fee_cents", lo=0)

    rec = core.make_record({
        "academic_year_id": year_id,
        "title": title,
        "subject": subject,
        "grade_min": grade_min,
        "grade_max": grade_max,
        "meeting_day": meeting_day,
        "meeting_start_minutes": meeting_start,
        "meeting_end_minutes": meeting_end,
        "start_date": start_date,
        "end_date": end_date,
        "capacity": capacity,
        "fee_base_cents": fee_base_cents,
        "materials_fee_cents": materials_fee_cents,
        "seats_taken": 0,
        "status": "DRAFT",
    })
    db.coop_classes[rec["id"]] = rec
    return success_object(ser_coop_class(rec), status=201)


@bp.route("/coop-classes/<class_id>", methods=["GET"])
@route(ALL_ROLES, parent_chain=_CLASS_CHAIN)
def get_class(class_id):
    return success_object(ser_coop_class(db.coop_classes[class_id]))


@bp.route("/coop-classes/<class_id>/open", methods=["POST"])
@route(["Registrar"], parent_chain=_CLASS_CHAIN)
def open_class(class_id):
    cls = db.coop_classes[class_id]
    if cls["status"] != "DRAFT":
        raise_err("ERR_INVALID_STATE_TRANSITION", "Class is not DRAFT")
    year = core.year_of_coop_class(cls)
    if year["status"] != "OPEN":
        raise_err("ERR_ACADEMIC_YEAR_NOT_OPEN", "Academic year is not OPEN")
    cls["status"] = "OPEN"
    core.touch(cls)
    return success_object(ser_coop_class(cls))


@bp.route("/coop-classes/<class_id>/cancel", methods=["POST"])
@route(["Registrar"], parent_chain=_CLASS_CHAIN)
def cancel_class(class_id):
    cls = db.coop_classes[class_id]
    if cls["status"] not in ("OPEN", "IN_SESSION"):
        raise_err("ERR_INVALID_STATE_TRANSITION",
                  "Only OPEN or IN_SESSION classes may be cancelled")
    for ce in list(db.coop_enrollments.values()):
        if ce["coop_class_id"] != class_id:
            continue
        if ce["status"] == "CONFIRMED":
            coop_svc.drop_coop_enrollment(ce, "SCHOOL_CANCEL", run_promotion=False)
        elif ce["status"] == "WAITLISTED":
            coop_svc.cancel_waitlisted(ce)
    cls["status"] = "CANCELLED"
    cls["seats_taken"] = 0
    core.touch(cls)
    return success_object(ser_coop_class(cls))


@bp.route("/coop-classes/<class_id>/enrollments", methods=["GET"])
@route(ALL_ROLES, parent_chain=_CLASS_CHAIN)
def list_class_enrollments(class_id):
    recs = [ce for ce in db.coop_enrollments.values() if ce["coop_class_id"] == class_id]
    status = request.args.get("status")
    if status:
        recs = [ce for ce in recs if ce["status"] == status]
    recs = core.sorted_by_created(recs)
    page, limit, offset, total = core.paginate(recs)
    return success_list([ser_coop_enrollment(ce) for ce in page], limit, offset, total)


@bp.route("/coop-classes/<class_id>/enrollments", methods=["POST"])
@route(["Parent"], parent_chain=_CLASS_CHAIN)
def create_coop_enrollment(class_id):
    cls = db.coop_classes[class_id]
    body = get_body()
    enrollment_id = req_string(body, "enrollment_id")
    expected_version = req_int(body, "expected_coop_class_version", lo=0)
    en = db.enrollments.get(enrollment_id)
    if en is None:
        raise_err("ERR_NOT_FOUND", f"enrollment {enrollment_id} not found")
    # Parent ownership on the referenced enrollment
    if request.user_role == "Parent":
        owner = core.root_family_id("enrollment", enrollment_id)
        if owner is not None and request.user_id != owner:
            raise_err("ERR_OWNERSHIP_MISMATCH",
                      "Parent may only register own family's enrollment")
    if cls["status"] != "OPEN":
        raise_err("ERR_COOP_CLASS_NOT_OPEN", "Co-op class is not OPEN")
    if expected_version != cls["version"]:
        raise_err("ERR_STALE_VERSION",
                  "expected_coop_class_version does not match current version")
    if en["compliance_standing"] == "NONCOMPLIANT":
        raise_err("ERR_ENROLLMENT_NONCOMPLIANT",
                  "NONCOMPLIANT enrollments may not register for co-op classes")
    if not (cls["grade_min"] <= en["grade_level"] <= cls["grade_max"]):
        raise_err("ERR_COOP_GRADE_INELIGIBLE",
                  "Enrollment grade is outside the class grade band")
    if coop_svc.has_schedule_overlap(en, cls):
        raise_err("ERR_COOP_SCHEDULE_OVERLAP",
                  "Meeting window overlaps another CONFIRMED class of the student")
    student = core.student_of_enrollment(en)
    family = core.family_of_student(student)
    fees_svc.refresh_fee_status(family)
    if family["fee_status"] == "OVERDUE":
        raise_err("ERR_FEES_OVERDUE",
                  "OVERDUE families may not take on new co-op charges")

    if cls["seats_taken"] < cls["capacity"]:
        discount = fees_svc.compute_discount_pct(
            cls, student["family_id"], en["academic_year_id"], clock.now_iso())
        fee_cents = fees_svc.compute_fee_cents(cls, discount)
        rec = core.make_record({
            "enrollment_id": enrollment_id,
            "coop_class_id": class_id,
            "status": "CONFIRMED",
            "fee_cents": fee_cents,
            "discount_pct_applied": discount,
            "refund_cents": None,
            "drop_reason": None,
            "promoted_at": None,
        })
        db.coop_enrollments[rec["id"]] = rec
        fees_svc.charge_family(family, fee_cents)
        cls["seats_taken"] += 1
        core.touch(cls)
    else:
        rec = core.make_record({
            "enrollment_id": enrollment_id,
            "coop_class_id": class_id,
            "status": "WAITLISTED",
            "fee_cents": 0,
            "discount_pct_applied": 0,
            "refund_cents": None,
            "drop_reason": None,
            "promoted_at": None,
        })
        db.coop_enrollments[rec["id"]] = rec

    return success_object(ser_coop_enrollment(rec), status=201)


@bp.route("/coop-enrollments/<coop_enrollment_id>", methods=["GET"])
@route(ALL_ROLES, ownership=("coop_enrollment", "coop_enrollment_id"),
       parent_chain=_CE_CHAIN)
def get_coop_enrollment(coop_enrollment_id):
    return success_object(ser_coop_enrollment(db.coop_enrollments[coop_enrollment_id]))


@bp.route("/coop-enrollments/<coop_enrollment_id>/drop", methods=["POST"])
@route(["Parent"], ownership=("coop_enrollment", "coop_enrollment_id"),
       parent_chain=_CE_CHAIN)
def drop_coop_enrollment(coop_enrollment_id):
    ce = db.coop_enrollments[coop_enrollment_id]
    if ce["status"] != "CONFIRMED":
        raise_err("ERR_INVALID_STATE_TRANSITION",
                  "Only CONFIRMED co-op enrollments may be dropped")
    coop_svc.drop_coop_enrollment(ce, "PARENT_INITIATED", run_promotion=True)
    return success_object(ser_coop_enrollment(ce))
