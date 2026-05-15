"""Session endpoints and check-in endpoint."""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from flask import Flask, g, request

from ..auth import require_auth
from ..clock import format_iso, now_dt, parse_iso
from ..errors import ApiError
from ..pagination import parse_limit_offset
from ..store import bump_version, common_fields_append_only, common_fields_create, get_store
from ..services.calculations import compute_instructor_fee, compute_provisional_credit
from ..services.lookups import (
    get_enrollment,
    get_session,
    ref_classroom,
    ref_course,
    ref_instructor,
    ref_online_room,
)
from ..services.serializers import serialize_check_in, serialize_session
from ..services.sessions import (
    cascade_cancel_session,
    cascade_complete_session,
    check_classroom_conflict,
    check_instructor_availability,
    check_online_room_capacity,
    evaluate_attendance,
    get_pinned_snapshot,
)
from ..services.validation import validate_ipv4_in_private_cidrs
from ._helpers import created, get_json_body, ok, ok_list, sort_by_created, with_lock


def _validate_session_payload(body: dict) -> dict[str, Any]:
    out: dict[str, Any] = {}
    course_id = body.get("course_id")
    if not course_id:
        raise ApiError("ERR_REFERENCE_NOT_FOUND", "course_id required.", http_status=422)
    out["course_id"] = course_id
    instructor_id = body.get("instructor_id")
    if not instructor_id:
        raise ApiError("ERR_REFERENCE_NOT_FOUND", "instructor_id required.", http_status=422)
    out["instructor_id"] = instructor_id
    mode = body.get("mode")
    if mode not in ("ONSITE", "ONLINE", "HYBRID"):
        raise ApiError("ERR_REFERENCE_NOT_FOUND", "mode must be ONSITE/ONLINE/HYBRID.", http_status=422)
    out["mode"] = mode

    classroom_id = body.get("classroom_id")
    online_room_id = body.get("online_room_id")
    if mode == "ONSITE":
        if not classroom_id:
            raise ApiError("ERR_REFERENCE_NOT_FOUND", "classroom_id required for ONSITE.", http_status=422)
        if online_room_id is not None:
            raise ApiError("ERR_REFERENCE_NOT_FOUND", "online_room_id must be null for ONSITE.", http_status=422)
    elif mode == "ONLINE":
        if not online_room_id:
            raise ApiError("ERR_REFERENCE_NOT_FOUND", "online_room_id required for ONLINE.", http_status=422)
        if classroom_id is not None:
            raise ApiError("ERR_REFERENCE_NOT_FOUND", "classroom_id must be null for ONLINE.", http_status=422)
    else:  # HYBRID
        if not classroom_id or not online_room_id:
            raise ApiError("ERR_REFERENCE_NOT_FOUND", "HYBRID requires both classroom_id and online_room_id.", http_status=422)
    out["classroom_id"] = classroom_id
    out["online_room_id"] = online_room_id

    try:
        sa = parse_iso(body.get("start_at"))
        ea = parse_iso(body.get("end_at"))
        dl = parse_iso(body.get("enrollment_deadline"))
    except ValueError as exc:
        raise ApiError("ERR_REFERENCE_NOT_FOUND", f"Invalid timestamp: {exc}", http_status=422)
    if ea <= sa:
        raise ApiError("ERR_REFERENCE_NOT_FOUND", "end_at must be after start_at.", http_status=422)
    if dl >= sa:
        raise ApiError("ERR_REFERENCE_NOT_FOUND", "enrollment_deadline must be before start_at.", http_status=422)
    out["start_at"] = sa
    out["end_at"] = ea
    out["enrollment_deadline"] = dl

    cap = body.get("capacity")
    try:
        cap = int(cap)
    except (TypeError, ValueError):
        raise ApiError("ERR_REFERENCE_NOT_FOUND", "capacity must be integer.", http_status=422)
    if not (1 <= cap <= 500):
        raise ApiError("ERR_REFERENCE_NOT_FOUND", "capacity out of range.", http_status=422)
    out["capacity"] = cap

    wlc = body.get("waitlist_capacity", 10)
    try:
        wlc = int(wlc)
    except (TypeError, ValueError):
        raise ApiError("ERR_REFERENCE_NOT_FOUND", "waitlist_capacity must be integer.", http_status=422)
    if not (0 <= wlc <= 100):
        raise ApiError("ERR_REFERENCE_NOT_FOUND", "waitlist_capacity out of range.", http_status=422)
    out["waitlist_capacity"] = wlc

    return out


def register(app: Flask) -> None:
    @app.post("/training/sessions")
    @require_auth("TrainingAdmin")
    @with_lock
    def create_session():
        body = get_json_body()
        data = _validate_session_payload(body)

        store = get_store()
        course = ref_course(data["course_id"])
        instructor = ref_instructor(data["instructor_id"])
        classroom = ref_classroom(data["classroom_id"]) if data["classroom_id"] else None
        online_room = ref_online_room(data["online_room_id"]) if data["online_room_id"] else None

        # Course must be ON_SHELF
        if course["status"] != "ON_SHELF":
            raise ApiError("ERR_COURSE_NOT_ON_SHELF", f"Course is {course['status']}, not ON_SHELF.")

        # instructor not blacklisted/retired
        if instructor["status"] != "ACTIVE":
            raise ApiError("ERR_INSTRUCTOR_BLACKLISTED", "Instructor is not ACTIVE.")
        # expertise overlap
        c_tags = set(course.get("tags") or [])
        i_tags = set(instructor.get("expertise_tags") or [])
        if not (c_tags & i_tags):
            raise ApiError("ERR_INSTRUCTOR_EXPERTISE_MISMATCH", "Instructor expertise does not overlap with course tags.")

        # end_at must equal start_at + duration_hours (within 1-minute tolerance)
        dh = float(course.get("duration_hours") or 0)
        expected_end = data["start_at"] + timedelta(hours=dh)
        if abs((data["end_at"] - expected_end).total_seconds()) > 60:
            raise ApiError("ERR_REFERENCE_NOT_FOUND", "end_at must equal start_at + duration_hours (1-min tolerance).", http_status=422)

        # Classroom conflict (priority 10)
        if classroom is not None:
            check_classroom_conflict(classroom, data["start_at"], data["end_at"], None)

        # Online room capacity (priority 11)
        if online_room is not None:
            check_online_room_capacity(online_room, data["start_at"], data["end_at"], data["capacity"], None)

        # Instructor availability (priority 12)
        check_instructor_availability(instructor["id"], data["start_at"], data["end_at"])

        # Find pinned course version
        pinned = None
        for v in store.course_versions.values():
            if v["course_id"] == course["id"] and v["status"] == "PUBLISHED" and v["version_no"] == course["current_version_no"]:
                pinned = v
                break
        if pinned is None:
            raise ApiError("ERR_COURSE_NOT_ON_SHELF", "No PUBLISHED CourseVersion to pin.")

        base = common_fields_create()
        row: dict[str, Any] = {
            **base,
            "course_id": course["id"],
            "pinned_course_version_id": pinned["id"],
            "instructor_id": instructor["id"],
            "mode": data["mode"],
            "classroom_id": data["classroom_id"],
            "online_room_id": data["online_room_id"],
            "start_at": format_iso(data["start_at"]),
            "end_at": format_iso(data["end_at"]),
            "capacity": data["capacity"],
            "waitlist_capacity": data["waitlist_capacity"],
            "enrollment_deadline": format_iso(data["enrollment_deadline"]),
            "status": "SCHEDULED",
            "enrolled_count": 0,
            "waitlist_count": 0,
            "cancellation_fee_charged": False,
        }
        # Snapshot of instructor pricing for fee calc (pinned at creation)
        row["pinned_instructor_snapshot"] = {
            "hourly_rate": float(instructor.get("hourly_rate") or 0),
            "travel_cost": float(instructor.get("travel_cost") or 0),
            "instructor_type": instructor.get("instructor_type"),
        }
        store.sessions[base["id"]] = row
        return created(serialize_session(row))

    @app.get("/training/sessions")
    @require_auth("TrainingAdmin", "CourseDesigner", "DepartmentManager", "Trainee")
    @with_lock
    def list_sessions():
        limit, offset = parse_limit_offset()
        course_id = request.args.get("course_id")
        instructor_id = request.args.get("instructor_id")
        status = request.args.get("status")
        start_after = request.args.get("start_after")
        start_before = request.args.get("start_before")
        items = list(get_store().sessions.values())
        if course_id:
            items = [s for s in items if s["course_id"] == course_id]
        if instructor_id:
            items = [s for s in items if s["instructor_id"] == instructor_id]
        if status:
            items = [s for s in items if s["status"] == status]
        if start_after:
            try:
                sa = parse_iso(start_after)
                items = [s for s in items if parse_iso(s["start_at"]) >= sa]
            except ValueError:
                raise ApiError("ERR_INVALID_PAGINATION", "Invalid start_after.")
        if start_before:
            try:
                sb = parse_iso(start_before)
                items = [s for s in items if parse_iso(s["start_at"]) < sb]
            except ValueError:
                raise ApiError("ERR_INVALID_PAGINATION", "Invalid start_before.")
        items = sort_by_created(items)
        return ok_list([serialize_session(s) for s in items], limit, offset)

    @app.get("/training/sessions/<sid>")
    @require_auth("TrainingAdmin", "CourseDesigner", "DepartmentManager", "Trainee")
    @with_lock
    def fetch_session(sid):
        row = get_session(sid)
        return ok(serialize_session(row))

    @app.post("/training/sessions/<sid>/open-enrollment")
    @require_auth("TrainingAdmin")
    @with_lock
    def open_enrollment(sid):
        s = get_session(sid)
        store = get_store()
        if s["status"] != "SCHEDULED":
            raise ApiError("ERR_INVALID_STATE", "Session not SCHEDULED.")
        course = store.courses.get(s["course_id"])
        if not course or course["status"] != "ON_SHELF":
            raise ApiError("ERR_COURSE_NOT_ON_SHELF", "Parent course not ON_SHELF.")
        if now_dt() >= parse_iso(s["enrollment_deadline"]):
            raise ApiError("ERR_INVALID_STATE", "Enrollment deadline already passed.")
        s["status"] = "ENROLLMENT_OPEN"
        bump_version(s)
        return ok(serialize_session(s))

    @app.post("/training/sessions/<sid>/complete")
    @require_auth("TrainingAdmin")
    @with_lock
    def complete_session(sid):
        s = get_session(sid)
        if s["status"] != "IN_PROGRESS":
            raise ApiError("ERR_INVALID_SESSION_STATE", "Session not IN_PROGRESS.")
        if now_dt() < parse_iso(s["end_at"]):
            raise ApiError("ERR_INVALID_STATE", "Session has not ended yet.")
        s["status"] = "COMPLETED"
        bump_version(s)
        cascade_complete_session(s)
        return ok(serialize_session(s))

    @app.post("/training/sessions/<sid>/cancel")
    @require_auth("TrainingAdmin")
    @with_lock
    def cancel_session(sid):
        s = get_session(sid)
        if s["status"] in ("COMPLETED", "CANCELLED"):
            raise ApiError("ERR_INVALID_SESSION_STATE", "Session already terminal.")
        s["status"] = "CANCELLED"
        cascade_cancel_session(s)
        bump_version(s)
        return ok(serialize_session(s))

    @app.get("/training/sessions/<sid>/instructor-fee")
    @require_auth("TrainingAdmin")
    @with_lock
    def instructor_fee(sid):
        s = get_session(sid)
        snapshot = get_pinned_snapshot(s)
        inst_snap = s.get("pinned_instructor_snapshot") or {}
        result = compute_instructor_fee(
            duration_hours=float(snapshot.get("duration_hours") or 0),
            hourly_rate=float(inst_snap.get("hourly_rate") or 0),
            travel_cost=float(inst_snap.get("travel_cost") or 0),
            instructor_type=inst_snap.get("instructor_type") or "INTERNAL",
        )
        result["session_id"] = s["id"]
        result["cancellation_fee_charged"] = bool(s.get("cancellation_fee_charged", False))
        return ok(result)

    @app.post("/training/sessions/<sid>/check-ins")
    @require_auth("Trainee", "TrainingAdmin")
    @with_lock
    def create_check_in(sid):
        s = get_session(sid)
        body = get_json_body()
        enrollment_id = body.get("enrollment_id")
        channel = body.get("channel")
        source_value = body.get("source_value")

        if not enrollment_id:
            raise ApiError("ERR_REFERENCE_NOT_FOUND", "enrollment_id required.", http_status=422)
        if channel not in ("QR", "FACE", "IP_RANGE"):
            raise ApiError("ERR_CHECKIN_INVALID", "Invalid channel.")
        store = get_store()
        e = store.enrollments.get(enrollment_id)
        if not e:
            raise ApiError("ERR_REFERENCE_NOT_FOUND", "Enrollment not found.")
        if e["session_id"] != s["id"]:
            raise ApiError("ERR_REFERENCE_NOT_FOUND", "Enrollment does not belong to this session.")

        # Ownership for Trainee
        if g.user_role == "Trainee":
            if e["trainee_id"] != g.user_id:
                raise ApiError("ERR_FORBIDDEN_ROLE", "Trainee may only check in for own enrollment.")

        if s["status"] != "IN_PROGRESS":
            raise ApiError("ERR_INVALID_STATE", "Session not IN_PROGRESS.")

        # Channel/value coherence
        # PRD §3.5: QR requires a server-issued token (PRD does not pin
        # the token syntax; any non-empty string is treated as a valid
        # token here). FACE requires a non-empty image reference.
        # IP_RANGE requires an IPv4 dotted-quad in 10.0.0.0/8 or
        # 192.168.0.0/16.
        if channel == "QR":
            if not isinstance(source_value, str) or not source_value:
                raise ApiError("ERR_CHECKIN_INVALID", "Invalid QR token.")
        elif channel == "FACE":
            if not isinstance(source_value, str) or not source_value:
                raise ApiError("ERR_CHECKIN_INVALID", "Empty image reference.")
        elif channel == "IP_RANGE":
            if not isinstance(source_value, str) or not validate_ipv4_in_private_cidrs(source_value):
                raise ApiError("ERR_CHECKIN_INVALID", "IP not in allowed CIDR.")

        base = common_fields_append_only()
        row = {
            **base,
            "session_id": s["id"],
            "enrollment_id": enrollment_id,
            "channel": channel,
            "source_value": source_value,
            "checked_in_at": base["created_at"],
        }
        store.check_ins[base["id"]] = row

        # Update enrollment.attendance_status (provisional sampling)
        e["attendance_status"] = evaluate_attendance(enrollment_id, s)
        # update provisional credit
        snapshot = get_pinned_snapshot(s)
        cv = float(snapshot.get("credit_value") or 0)
        e["provisional_credit"] = compute_provisional_credit(cv, e["attendance_status"])
        bump_version(e)

        return created(serialize_check_in(row))
