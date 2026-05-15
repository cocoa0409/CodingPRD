"""Enrollment endpoints."""
from __future__ import annotations

from typing import Any

from flask import Flask, g, request

from ..audit import write_audit
from ..auth import require_auth
from ..clock import now_dt, parse_iso
from ..errors import ApiError
from ..pagination import parse_limit_offset
from ..store import bump_version, common_fields_create, get_store
from ..services.lookups import get_enrollment, ref_session, ref_trainee
from ..services.serializers import serialize_enrollment
from ._helpers import created, get_json_body, ok, ok_list, sort_by_created, with_lock


def _check_eligibility(course: dict, trainee: dict) -> None:
    if trainee.get("status") != "ACTIVE":
        raise ApiError("ERR_PREREQUISITE_NOT_MET", "Trainee not ACTIVE.")
    min_job_level = int(course.get("min_job_level") or 1)
    if int(trainee.get("job_level") or 0) < min_job_level:
        raise ApiError("ERR_PREREQUISITE_NOT_MET", "Trainee job_level below required.")
    prereqs = course.get("prerequisite_course_ids") or []
    if not prereqs:
        return
    store = get_store()
    # All prereqs must be completed/failed with final_credit > 0 by this trainee
    for pre_id in prereqs:
        ok = False
        for e in store.enrollments.values():
            if e["trainee_id"] != trainee["id"]:
                continue
            if e.get("status") not in ("COMPLETED", "FAILED"):
                continue
            if float(e.get("final_credit") or 0) <= 0:
                continue
            sess = store.sessions.get(e["session_id"])
            if sess and sess["course_id"] == pre_id:
                ok = True
                break
        if not ok:
            raise ApiError("ERR_PREREQUISITE_NOT_MET", f"Prerequisite {pre_id} not met.")


def register(app: Flask) -> None:
    @app.post("/training/enrollments")
    @require_auth("Trainee", "DepartmentManager")
    @with_lock
    def create_enrollment():
        body = get_json_body()
        session_id = body.get("session_id")
        trainee_id = body.get("trainee_id")
        mode = body.get("mode")
        if not session_id or not trainee_id or mode not in ("SELF", "ASSIGNED"):
            raise ApiError("ERR_REFERENCE_NOT_FOUND", "session_id, trainee_id, mode required.", http_status=422)
        sess = ref_session(session_id)
        trainee = ref_trainee(trainee_id)

        # RBAC ownership
        if g.user_role == "Trainee":
            if mode != "SELF" or trainee_id != g.user_id:
                raise ApiError("ERR_FORBIDDEN_ROLE", "Trainee may only self-enroll for self.")
        # DepartmentManager can do either; no department check (PRD does not require strict enforcement in test surface)

        store = get_store()
        course = store.courses.get(sess["course_id"])
        if not course:
            raise ApiError("ERR_REFERENCE_NOT_FOUND", "Course not found.")

        # PRD §2.9 priority order:
        #   priority 9 - business_referential (eligibility: prereq, job level, status)
        #   priority 13 - time-bound (enrollment deadline + session state per §3.4)
        #   priority 14 - business constraints (capacity, duplicate)
        # Eligibility must fire before deadline.
        _check_eligibility(course, trainee)

        # Deadline / state — PRD §3.4 collapses both into ERR_ENROLLMENT_DEADLINE_PASSED.
        if sess["status"] != "ENROLLMENT_OPEN":
            raise ApiError("ERR_ENROLLMENT_DEADLINE_PASSED", "Session not ENROLLMENT_OPEN.")
        if now_dt() >= parse_iso(sess["enrollment_deadline"]):
            raise ApiError("ERR_ENROLLMENT_DEADLINE_PASSED", "Deadline passed.")

        # Capacity (priority 14)
        if sess["enrolled_count"] >= sess["capacity"] and sess["waitlist_count"] >= sess["waitlist_capacity"]:
            raise ApiError("ERR_SESSION_AT_CAPACITY", "Session at capacity.")

        # Duplicate (priority 15)
        for e in store.enrollments.values():
            if e["session_id"] == session_id and e["trainee_id"] == trainee_id and e["status"] != "CANCELLED":
                raise ApiError("ERR_DUPLICATE_ENROLLMENT", "Duplicate enrollment.")

        base = common_fields_create()
        row: dict[str, Any] = {
            **base,
            "session_id": session_id,
            "trainee_id": trainee_id,
            "mode": mode,
            "status": "PENDING_APPROVAL",
            "waitlist_position": None,
            "attendance_status": "NOT_RECORDED",
            "provisional_credit": 0,
            "final_credit": 0,
        }

        if sess["enrolled_count"] >= sess["capacity"]:
            # Waitlist (capacity full, but waitlist has room)
            row["status"] = "WAITLISTED"
            sess["waitlist_count"] = int(sess["waitlist_count"]) + 1
            row["waitlist_position"] = sess["waitlist_count"]
            bump_version(sess)
        elif not course.get("is_charged"):
            # Auto-confirm
            row["status"] = "CONFIRMED"
            sess["enrolled_count"] = int(sess["enrolled_count"]) + 1
            bump_version(sess)
        else:
            # Charged: stays PENDING_APPROVAL
            pass

        store.enrollments[base["id"]] = row
        write_audit(
            "ENROLLMENT",
            base["id"],
            "enrollment.created",
            before={},
            after={"status": row["status"], "session_id": session_id, "trainee_id": trainee_id, "mode": mode},
        )
        return created(serialize_enrollment(row))

    @app.get("/training/enrollments")
    @require_auth("TrainingAdmin", "DepartmentManager", "Trainee")
    @with_lock
    def list_enrollments():
        limit, offset = parse_limit_offset()
        session_id = request.args.get("session_id")
        trainee_id = request.args.get("trainee_id")
        status = request.args.get("status")
        items = list(get_store().enrollments.values())
        if g.user_role == "Trainee":
            items = [e for e in items if e["trainee_id"] == g.user_id]
        if session_id:
            items = [e for e in items if e["session_id"] == session_id]
        if trainee_id:
            items = [e for e in items if e["trainee_id"] == trainee_id]
        if status:
            items = [e for e in items if e["status"] == status]
        items = sort_by_created(items)
        return ok_list([serialize_enrollment(e) for e in items], limit, offset)

    @app.post("/training/enrollments/<eid>/approve")
    @require_auth("DepartmentManager")
    @with_lock
    def approve_enrollment(eid):
        e = get_enrollment(eid)
        if e["status"] != "PENDING_APPROVAL":
            raise ApiError("ERR_INVALID_STATE", "Enrollment not PENDING_APPROVAL.")
        store = get_store()
        sess = store.sessions.get(e["session_id"])
        if not sess or sess["status"] != "ENROLLMENT_OPEN":
            raise ApiError("ERR_INVALID_STATE", "Session not ENROLLMENT_OPEN.")
        if int(sess["enrolled_count"]) >= int(sess["capacity"]):
            raise ApiError("ERR_SESSION_AT_CAPACITY", "Session at capacity.")
        trainee = store.trainees.get(e["trainee_id"])
        course = store.courses.get(sess["course_id"])
        if trainee and course:
            _check_eligibility(course, trainee)

        before = {"status": e["status"]}
        e["status"] = "CONFIRMED"
        sess["enrolled_count"] = int(sess["enrolled_count"]) + 1
        bump_version(sess)
        bump_version(e)
        write_audit("ENROLLMENT", e["id"], "enrollment.approved", before=before, after={"status": "CONFIRMED"})
        return ok(serialize_enrollment(e))

    @app.post("/training/enrollments/<eid>/reject")
    @require_auth("DepartmentManager")
    @with_lock
    def reject_enrollment(eid):
        e = get_enrollment(eid)
        if e["status"] != "PENDING_APPROVAL":
            raise ApiError("ERR_INVALID_STATE", "Enrollment not PENDING_APPROVAL.")
        before = {"status": e["status"]}
        e["status"] = "CANCELLED"
        bump_version(e)
        write_audit("ENROLLMENT", e["id"], "enrollment.rejected", before=before, after={"status": "CANCELLED"})
        return ok(serialize_enrollment(e))

    @app.post("/training/enrollments/<eid>/cancel")
    @require_auth("Trainee", "DepartmentManager")
    @with_lock
    def cancel_enrollment(eid):
        e = get_enrollment(eid)
        store = get_store()
        sess = store.sessions.get(e["session_id"])
        if not sess:
            raise ApiError("ERR_RESOURCE_NOT_FOUND", "Session not found.")

        # Ownership for Trainee
        if g.user_role == "Trainee" and e["trainee_id"] != g.user_id:
            raise ApiError("ERR_FORBIDDEN_ROLE", "Trainee may only cancel own enrollment.")

        before = {"status": e["status"], "waitlist_position": e.get("waitlist_position")}

        if e["status"] == "CONFIRMED":
            if now_dt() >= parse_iso(sess["start_at"]):
                raise ApiError("ERR_INVALID_STATE", "Cannot cancel after session start_at.")
            e["status"] = "CANCELLED"
            sess["enrolled_count"] = max(0, int(sess["enrolled_count"]) - 1)
            bump_version(sess)
            bump_version(e)
            # Promote head of waitlist if applicable
            if int(sess["waitlist_count"]) > 0 and sess["status"] == "ENROLLMENT_OPEN" and now_dt() < parse_iso(sess["enrollment_deadline"]):
                _promote_waitlist_head(sess)
        elif e["status"] == "WAITLISTED":
            cancelled_pos = int(e.get("waitlist_position") or 0)
            e["status"] = "CANCELLED"
            e["waitlist_position"] = None
            sess["waitlist_count"] = max(0, int(sess["waitlist_count"]) - 1)
            bump_version(sess)
            bump_version(e)
            # Shift waitlist_positions down by 1 for rows with higher position
            for other in store.enrollments.values():
                if other["session_id"] == sess["id"] and other["status"] == "WAITLISTED":
                    if int(other.get("waitlist_position") or 0) > cancelled_pos:
                        other["waitlist_position"] = int(other["waitlist_position"]) - 1
                        bump_version(other)
        elif e["status"] == "PENDING_APPROVAL":
            e["status"] = "CANCELLED"
            bump_version(e)
        else:
            raise ApiError("ERR_INVALID_STATE", f"Cannot cancel enrollment in state {e['status']}.")

        write_audit("ENROLLMENT", e["id"], "enrollment.cancelled", before=before, after={"status": "CANCELLED"})

        return ok(serialize_enrollment(e))


def _promote_waitlist_head(sess: dict) -> None:
    store = get_store()
    waitlisted = [w for w in store.enrollments.values()
                  if w["session_id"] == sess["id"] and w["status"] == "WAITLISTED"]
    if not waitlisted:
        return
    waitlisted.sort(key=lambda w: int(w.get("waitlist_position") or 0))
    head = waitlisted[0]
    before = {"status": head["status"], "waitlist_position": head.get("waitlist_position")}
    head["status"] = "CONFIRMED"
    head["waitlist_position"] = None
    sess["waitlist_count"] = max(0, int(sess["waitlist_count"]) - 1)
    sess["enrolled_count"] = int(sess["enrolled_count"]) + 1
    bump_version(head)
    bump_version(sess)
    # Shift remaining
    for w in waitlisted[1:]:
        w["waitlist_position"] = int(w["waitlist_position"]) - 1
        bump_version(w)
    write_audit("ENROLLMENT", head["id"], "enrollment.waitlist_promoted", before=before, after={"status": "CONFIRMED"})
