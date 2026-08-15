"""Attendance entry endpoints."""
from datetime import date as _date
from datetime import datetime, time, timezone

from flask import Blueprint

import clock
import db
from errors import raise_err
from middleware import route, ALL_ROLES
from response import success_object
from serializers import ser_attendance_entry
from services import core
from services import progress as progress_svc
from validation import get_body, req_date, req_int

bp = Blueprint("attendance", __name__)

_CHAIN = (("attendance_entry", "entry_id", db.attendance_entries),)


def _parse_date(d):
    y, m, dd = (int(x) for x in d.split("-"))
    return _date(y, m, dd)


def _check_entry_date(enrollment, entry_date):
    year = core.year_of_enrollment(enrollment)
    d = _parse_date(entry_date)
    if d < _parse_date(year["start_date"]) or d > _parse_date(year["end_date"]):
        raise_err("ERR_ATTENDANCE_DATE_OUT_OF_RANGE",
                  "entry_date is outside the academic year")
    if d > clock.now().date():
        raise_err("ERR_ATTENDANCE_DATE_OUT_OF_RANGE",
                  "entry_date is in the future")


@bp.route("/enrollments/<enrollment_id>/attendance-entries", methods=["POST"])
@route(["Parent"], ownership=("enrollment", "enrollment_id"),
       parent_chain=(("enrollment", "enrollment_id", db.enrollments),))
def create_entry(enrollment_id):
    en = db.enrollments[enrollment_id]
    body = get_body()
    entry_date = req_date(body, "entry_date")
    minutes = req_int(body, "minutes", lo=1, hi=720)
    if en["enrollment_status"] != "ACTIVE":
        raise_err("ERR_ENROLLMENT_NOT_ACTIVE", "Enrollment must be ACTIVE to log attendance")
    _check_entry_date(en, entry_date)
    for e in db.attendance_entries.values():
        if (e["enrollment_id"] == enrollment_id
                and e["entry_date"] == entry_date
                and e["status"] != "VOIDED"):
            raise_err("ERR_ATTENDANCE_DUPLICATE_DATE",
                      "A non-voided entry already exists for this date")
    rec = core.make_record({
        "enrollment_id": enrollment_id,
        "entry_date": entry_date,
        "minutes": minutes,
        "status": "RECORDED",
        "verified_by": None,
    })
    db.attendance_entries[rec["id"]] = rec
    progress_svc.recompute_progress(en)
    return success_object(ser_attendance_entry(rec), status=201)


@bp.route("/attendance-entries/<entry_id>", methods=["GET"])
@route(ALL_ROLES, ownership=("attendance_entry", "entry_id"), parent_chain=_CHAIN)
def get_entry(entry_id):
    return success_object(ser_attendance_entry(db.attendance_entries[entry_id]))


@bp.route("/attendance-entries/<entry_id>", methods=["PATCH"])
@route(["Parent"], ownership=("attendance_entry", "entry_id"), parent_chain=_CHAIN)
def patch_entry(entry_id):
    entry = db.attendance_entries[entry_id]
    body = get_body()
    minutes = req_int(body, "minutes", lo=1, hi=720)
    if entry["status"] != "RECORDED":
        raise_err("ERR_ATTENDANCE_ENTRY_LOCKED",
                  "Only RECORDED entries may be corrected")
    entry["minutes"] = minutes
    core.touch(entry)
    en = db.enrollments.get(entry["enrollment_id"])
    if en:
        progress_svc.recompute_progress(en)
    return success_object(ser_attendance_entry(entry))


@bp.route("/attendance-entries/<entry_id>/verify", methods=["POST"])
@route(["Reviewer"], parent_chain=_CHAIN)
def verify_entry(entry_id):
    from flask import request as freq
    entry = db.attendance_entries[entry_id]
    if entry["status"] != "RECORDED":
        raise_err("ERR_INVALID_STATE_TRANSITION", "Only RECORDED entries may be verified")
    entry["status"] = "VERIFIED"
    entry["verified_by"] = freq.user_id
    core.touch(entry)
    en = db.enrollments.get(entry["enrollment_id"])
    if en:
        progress_svc.recompute_progress(en)
    return success_object(ser_attendance_entry(entry))


@bp.route("/attendance-entries/<entry_id>/void", methods=["POST"])
@route(["Parent", "Registrar"], ownership=("attendance_entry", "entry_id"),
       parent_chain=_CHAIN)
def void_entry(entry_id):
    from flask import request as freq
    entry = db.attendance_entries[entry_id]
    if entry["status"] == "VOIDED":
        raise_err("ERR_INVALID_STATE_TRANSITION", "Entry is already VOIDED")
    if entry["status"] == "RECORDED":
        pass  # Parent or Registrar may void a RECORDED entry
    elif entry["status"] == "VERIFIED":
        if freq.user_role != "Registrar":
            raise_err("ERR_ATTENDANCE_ENTRY_LOCKED",
                      "Only a Registrar may void a VERIFIED entry")
    else:
        raise_err("ERR_INVALID_STATE_TRANSITION", "Entry cannot be voided")
    entry["status"] = "VOIDED"
    core.touch(entry)
    en = db.enrollments.get(entry["enrollment_id"])
    if en:
        progress_svc.recompute_progress(en)
    return success_object(ser_attendance_entry(entry))
