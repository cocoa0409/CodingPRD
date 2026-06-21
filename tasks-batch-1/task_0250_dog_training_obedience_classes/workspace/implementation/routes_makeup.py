"""MakeupBooking routes."""
from flask import request

import domain
import serializers as S
from common import (
    get_user_context, require_role, get_json_body, check_string, touch,
)
from errors import err
from lookups import get_attendance, get_session, get_makeup, list_response
from response import success
from store import db, new_id, now_iso


def register(app):

    @app.route("/makeup-bookings", methods=["POST"])
    def create_makeup():
        user_id, role = get_user_context()
        require_role(role, {"Owner", "FrontDesk", "AdminManager"})
        body = get_json_body()
        attendance_id = check_string(body, "attendance_id")
        makeup_session_id = check_string(body, "makeup_session_id")
        # existence: session then attendance per left-to-right ordering;
        # both FKs validated.
        attendance = get_attendance(attendance_id)
        makeup_session = get_session(makeup_session_id)
        if role == "Owner":
            enrollment = db.enrollments.get(attendance["enrollment_id"])
            dog = db.dogs.get(enrollment["dog_id"]) if enrollment else None
            if not dog or dog["owner_id"] != user_id:
                raise err("ERR_NOT_DOG_OWNER", "Not owner of this attendance's dog")
        mid = new_id()
        ts = now_iso()
        booking = {
            "id": mid, "created_at": ts, "updated_at": ts, "version": 1,
            "attendance_id": attendance_id, "makeup_session_id": makeup_session_id,
            "status": "REQUESTED",
        }
        db.makeup_bookings[mid] = booking
        return success(S.ser_makeup(booking), 201)

    @app.route("/makeup-bookings", methods=["GET"])
    def list_makeups():
        user_id, role = get_user_context()
        require_role(role, {"Owner", "Trainer", "FrontDesk", "AdminManager"})
        rows = list(db.makeup_bookings.values())
        attendance_id = request.args.get("attendance_id")
        makeup_session_id = request.args.get("makeup_session_id")
        if attendance_id is not None:
            rows = [m for m in rows if m["attendance_id"] == attendance_id]
        if makeup_session_id is not None:
            rows = [m for m in rows if m["makeup_session_id"] == makeup_session_id]
        return list_response(rows, S.ser_makeup)

    @app.route("/makeup-bookings/<makeup_id>", methods=["GET"])
    def get_makeup_ep(makeup_id):
        user_id, role = get_user_context()
        require_role(role, {"Owner", "Trainer", "FrontDesk", "AdminManager"})
        booking = get_makeup(makeup_id)
        return success(S.ser_makeup(booking), 200)

    @app.route("/makeup-bookings/<makeup_id>/confirm", methods=["POST"])
    def confirm_makeup(makeup_id):
        user_id, role = get_user_context()
        require_role(role, {"FrontDesk", "AdminManager"})
        booking = get_makeup(makeup_id)
        if booking["status"] != "REQUESTED":
            raise err("ERR_INVALID_STATE", "Booking must be REQUESTED to confirm")
        attendance = db.attendance_records.get(booking["attendance_id"])
        makeup_session = db.class_sessions.get(booking["makeup_session_id"])
        # business constraints (priority 6)
        domain.refresh_attendance_eligible(attendance)
        if not attendance["makeup_eligible"]:
            raise err("ERR_MAKEUP_NOT_ELIGIBLE", "Source attendance not makeup-eligible")
        if not makeup_session["is_makeup_slot"] or makeup_session["status"] != "SCHEDULED":
            raise err("ERR_INVALID_MAKEUP_SLOT",
                      "Makeup session must be a SCHEDULED makeup slot")
        # level match: makeup session's series level == source enrollment's series level
        source_enrollment = db.enrollments.get(attendance["enrollment_id"])
        source_series = db.class_series.get(source_enrollment["series_id"]) if source_enrollment else None
        makeup_series = db.class_series.get(makeup_session["series_id"])
        if not source_series or not makeup_series or source_series["level"] != makeup_series["level"]:
            raise err("ERR_MAKEUP_LEVEL_MISMATCH",
                      "Makeup session level differs from source enrollment level")
        # dog overlap check (priority 11): candidate = makeup slot session
        committed = domain.dog_committed_intervals(source_enrollment["dog_id"])
        candidate = [(domain.parse_dt(makeup_session["starts_at"]),
                      domain.parse_dt(makeup_session["ends_at"]))]
        if domain.intervals_strictly_overlap(committed, candidate):
            raise err("ERR_DOG_SESSION_OVERLAP", "Dog has overlapping sessions")
        booking["status"] = "CONFIRMED"
        touch(booking)
        attendance["state"] = "MAKEUP_PENDING"
        domain.refresh_attendance_eligible(attendance)
        touch(attendance)
        return success(S.ser_makeup(booking), 200)

    @app.route("/makeup-bookings/<makeup_id>/reject", methods=["POST"])
    def reject_makeup(makeup_id):
        user_id, role = get_user_context()
        require_role(role, {"FrontDesk", "AdminManager"})
        booking = get_makeup(makeup_id)
        if booking["status"] != "REQUESTED":
            raise err("ERR_INVALID_STATE", "Booking must be REQUESTED to reject")
        booking["status"] = "REJECTED"
        touch(booking)
        return success(S.ser_makeup(booking), 200)

    @app.route("/makeup-bookings/<makeup_id>/complete", methods=["POST"])
    def complete_makeup(makeup_id):
        user_id, role = get_user_context()
        require_role(role, {"Trainer"})
        booking = get_makeup(makeup_id)
        if booking["status"] != "CONFIRMED":
            raise err("ERR_INVALID_STATE", "Booking must be CONFIRMED to complete")
        makeup_session = db.class_sessions.get(booking["makeup_session_id"])
        if not makeup_session or makeup_session["status"] != "COMPLETED":
            raise err("ERR_MAKEUP_SESSION_NOT_COMPLETED",
                      "Makeup session must be COMPLETED")
        booking["status"] = "COMPLETED"
        touch(booking)
        attendance = db.attendance_records.get(booking["attendance_id"])
        if attendance:
            attendance["state"] = "MAKEUP_DONE"
            domain.refresh_attendance_eligible(attendance)
            touch(attendance)
            enrollment = db.enrollments.get(attendance["enrollment_id"])
            if enrollment:
                domain.refresh_enrollment_progress_touch(enrollment)
        return success(S.ser_makeup(booking), 200)

    @app.route("/makeup-bookings/<makeup_id>/cancel", methods=["POST"])
    def cancel_makeup(makeup_id):
        user_id, role = get_user_context()
        require_role(role, {"Owner", "FrontDesk", "AdminManager"})
        booking = get_makeup(makeup_id)
        if booking["status"] not in ("REQUESTED", "CONFIRMED"):
            raise err("ERR_INVALID_STATE", "Booking must be REQUESTED or CONFIRMED to cancel")
        if role == "Owner":
            attendance = db.attendance_records.get(booking["attendance_id"])
            enrollment = db.enrollments.get(attendance["enrollment_id"]) if attendance else None
            dog = db.dogs.get(enrollment["dog_id"]) if enrollment else None
            if not dog or dog["owner_id"] != user_id:
                raise err("ERR_NOT_DOG_OWNER", "Not owner of this booking's dog")
        booking["status"] = "CANCELLED"
        touch(booking)
        attendance = db.attendance_records.get(booking["attendance_id"])
        if attendance:
            attendance["state"] = "MISSED_PROVIDER"
            domain.refresh_attendance_eligible(attendance)
            touch(attendance)
        return success(S.ser_makeup(booking), 200)
