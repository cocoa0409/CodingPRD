"""AttendanceRecord read endpoints."""

from flask import Blueprint, request

import db
import errors
import middleware
import response
import serializers
import util
from services import core

bp = Blueprint("attendance", __name__)

ATTENDANCE_READERS = {"SchoolAdmin", "FrontOfficeStaff", "Teacher", "FamilyGuardian"}


def _check_attendance_scope(role, uid, record):
    booking = db.bookings.get(record["booking_id"])
    if booking is None:
        return
    if role == "Teacher" and booking["teacher_id"] != uid:
        raise errors.forbidden("Teacher may view only their own bookings' records")
    if role == "FamilyGuardian" and booking["family_id"] != uid:
        raise errors.forbidden("FamilyGuardian may view only their own family's records")


@bp.route("/conf/attendance-records", methods=["GET"])
def list_attendance():
    role, uid = middleware.get_auth()
    middleware.require_roles(role, ATTENDANCE_READERS)
    limit, offset = util.parse_pagination(request.args)
    booking_id = request.args.get("booking_id")
    outcome = request.args.get("outcome")
    items = list(db.attendance_records.values())
    if role in ("Teacher", "FamilyGuardian"):
        scoped = []
        for a in items:
            booking = db.bookings.get(a["booking_id"])
            if booking is None:
                continue
            if role == "Teacher" and booking["teacher_id"] != uid:
                continue
            if role == "FamilyGuardian" and booking["family_id"] != uid:
                continue
            scoped.append(a)
        items = scoped
    if booking_id is not None:
        items = [a for a in items if a["booking_id"] == booking_id]
    if outcome is not None:
        items = [a for a in items if a["outcome"] == outcome]
    items.sort(key=lambda a: a["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return response.success_list([serializers.attendance_view(a) for a in page],
                                 total, limit, offset)


@bp.route("/conf/attendance-records/<aid>", methods=["GET"])
def get_attendance(aid):
    role, uid = middleware.get_auth()
    middleware.require_roles(role, ATTENDANCE_READERS)
    record = core.get_attendance_or_404(aid)
    _check_attendance_scope(role, uid, record)
    return response.success_object(serializers.attendance_view(record))
