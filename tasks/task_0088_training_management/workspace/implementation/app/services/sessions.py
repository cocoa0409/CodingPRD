"""Session business logic: conflict detection, completion cascade."""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from ..clock import format_iso, now_dt, parse_iso, add_months
from ..errors import ApiError
from ..store import bump_version, common_fields_append_only, get_store, now_iso
from .calculations import (
    compute_final_credit,
    compute_provisional_credit,
    recompute_credit_pool_accumulated,
    recompute_instructor_avg_eval,
)


# ----- conflict detection -----


def _intervals_overlap(a_start, a_end, b_start, b_end) -> bool:
    """Half-open [start, end): overlap iff a_start < b_end and b_start < a_end."""
    return a_start < b_end and b_start < a_end


def check_classroom_conflict(
    classroom: dict,
    candidate_start,
    candidate_end,
    exclude_session_id: str | None,
) -> None:
    """A session in this classroom occupies [start_at, end_at + setup_buffer_minutes).
    Reject if any non-CANCELLED session overlaps the candidate's same-extended window."""
    store = get_store()
    sbm = int(classroom.get("setup_buffer_minutes", 30))
    cand_extended_end = candidate_end + timedelta(minutes=sbm)
    cand_extended_start = candidate_start

    for s in store.sessions.values():
        if exclude_session_id and s["id"] == exclude_session_id:
            continue
        if s.get("status") == "CANCELLED":
            continue
        if s.get("classroom_id") != classroom["id"]:
            continue
        s_start = parse_iso(s["start_at"])
        s_end = parse_iso(s["end_at"]) + timedelta(minutes=sbm)
        if _intervals_overlap(cand_extended_start, cand_extended_end, s_start, s_end):
            raise ApiError("ERR_CLASSROOM_CONFLICT", "Classroom time conflict.")


def check_online_room_capacity(
    online_room: dict,
    candidate_start,
    candidate_end,
    candidate_capacity: int,
    exclude_session_id: str | None,
) -> None:
    """Multiple sessions may share an OnlineRoom if combined capacity at any single point in time
    <= online_room.max_participants. No setup buffer for online rooms."""
    store = get_store()
    max_p = int(online_room.get("max_participants", 1))

    # Build set of breakpoints from non-cancelled sessions in this room
    overlapping = []
    for s in store.sessions.values():
        if exclude_session_id and s["id"] == exclude_session_id:
            continue
        if s.get("status") == "CANCELLED":
            continue
        if s.get("online_room_id") != online_room["id"]:
            continue
        s_start = parse_iso(s["start_at"])
        s_end = parse_iso(s["end_at"])
        if _intervals_overlap(candidate_start, candidate_end, s_start, s_end):
            overlapping.append((s_start, s_end, int(s.get("capacity", 0))))

    # Sweep-line: events at start (+cap), end (-cap)
    events: list[tuple] = []
    for s_start, s_end, cap in overlapping:
        events.append((s_start, +cap))
        events.append((s_end, -cap))
    # Add candidate
    events.append((candidate_start, +int(candidate_capacity)))
    events.append((candidate_end, -int(candidate_capacity)))

    # Sort events: end before start at same instant (half-open)? Actually
    # at instant t, a session ending at t no longer counts. So process -cap before +cap.
    events.sort(key=lambda x: (x[0], x[1]))
    running = 0
    for _, delta in events:
        running += delta
        if running > max_p:
            raise ApiError("ERR_ONLINE_ROOM_CAPACITY_EXCEEDED", "Online room capacity exceeded.")


def check_instructor_availability(instructor_id: str, candidate_start, candidate_end) -> None:
    """Need at least one AVAILABLE window fully covering [start, end); no BLOCKED overlap."""
    store = get_store()
    avs = [a for a in store.instructor_availabilities.values() if a["instructor_id"] == instructor_id]
    # Check BLOCKED overlap
    for a in avs:
        if a["kind"] != "BLOCKED":
            continue
        a_start = parse_iso(a["start_at"])
        a_end = parse_iso(a["end_at"])
        if _intervals_overlap(candidate_start, candidate_end, a_start, a_end):
            raise ApiError("ERR_INSTRUCTOR_UNAVAILABLE", "Instructor blocked during this window.")
    # Need an AVAILABLE window that fully covers
    covers = False
    for a in avs:
        if a["kind"] != "AVAILABLE":
            continue
        a_start = parse_iso(a["start_at"])
        a_end = parse_iso(a["end_at"])
        if a_start <= candidate_start and a_end >= candidate_end:
            covers = True
            break
    if not covers:
        raise ApiError("ERR_INSTRUCTOR_UNAVAILABLE", "No AVAILABLE window covers this interval.")


# ----- attendance evaluation -----


def evaluate_attendance(enrollment_id: str, session: dict) -> str:
    """Decide attendance_status for an enrollment based on its check-ins.

    Rule: 0 check-ins -> ABSENT; multiple check-ins of any channel -> PRESENT;
    a single check-in -> PARTIAL. (Pragmatic interpretation of the PRD's
    "periodic sampling".)
    """
    store = get_store()
    cins = [c for c in store.check_ins.values() if c["enrollment_id"] == enrollment_id and c["session_id"] == session["id"]]
    if not cins:
        return "ABSENT"
    if len(cins) == 1:
        return "PARTIAL"
    return "PRESENT"


def get_pinned_snapshot(session: dict) -> dict[str, Any]:
    store = get_store()
    cv = store.course_versions.get(session.get("pinned_course_version_id"))
    if cv:
        return cv.get("snapshot", {})
    # Fallback: read from course
    c = store.courses.get(session["course_id"])
    return {
        "credit_value": (c or {}).get("credit_value", 0),
        "duration_hours": (c or {}).get("duration_hours", 0),
    }


# ----- session completion cascade -----


def cascade_complete_session(session: dict) -> None:
    """Walk every CONFIRMED enrollment, finalize attendance, advance to COMPLETED/FAILED/NO_SHOW,
    write final_credit, recompute credit pools, issue certificates."""
    store = get_store()
    snapshot = get_pinned_snapshot(session)
    credit_value = snapshot.get("credit_value", 0)

    confirmed_enrolls = [e for e in store.enrollments.values()
                         if e["session_id"] == session["id"] and e["status"] == "CONFIRMED"]

    for e in confirmed_enrolls:
        att = evaluate_attendance(e["id"], session)
        e["attendance_status"] = att
        # find exam attempt for this enrollment (latest submitted)
        attempts = [a for a in store.exam_attempts.values()
                    if a["enrollment_id"] == e["id"] and a.get("submitted_at")]
        exam = attempts[-1] if attempts else None

        if att == "ABSENT":
            e["status"] = "NO_SHOW"
            e["final_credit"] = 0
        else:
            if exam is not None and not exam.get("passed", False):
                e["status"] = "FAILED"
            else:
                e["status"] = "COMPLETED"
            e["final_credit"] = compute_final_credit(credit_value, att, exam)

        bump_version(e)

        # Audit
        from ..audit import write_audit
        write_audit(
            "ENROLLMENT",
            e["id"],
            "enrollment.completed_or_failed",
            before={"status": "CONFIRMED"},
            after={"status": e["status"], "final_credit": e["final_credit"]},
        )

        # Recompute credit pool(s) for this trainee
        for pool in store.credit_pools.values():
            if pool["trainee_id"] == e["trainee_id"]:
                recompute_credit_pool_accumulated(pool)
                bump_version(pool)

        # Certificate issuance
        if e["status"] == "COMPLETED":
            tpl_id = store.cert_template_by_course.get(session["course_id"])
            if tpl_id:
                tpl = store.certificate_templates.get(tpl_id)
                if tpl:
                    issue = True
                    if tpl.get("requires_attendance") and att != "PRESENT":
                        issue = False
                    if tpl.get("requires_exam_pass") and (exam is None or not exam.get("passed")):
                        issue = False
                    if issue:
                        _issue_certificate(tpl, e, session)

    # Recompute instructor avg_evaluation_score
    recompute_instructor_avg_eval(session["instructor_id"])


def _issue_certificate(template: dict, enrollment: dict, session: dict) -> dict:
    from ..store import new_id
    store = get_store()
    issued = now_iso()
    issued_dt = parse_iso(issued)
    expires_dt = add_months(issued_dt, int(template["validity_months"]))
    cert_id = new_id()
    base = common_fields_append_only()
    # base already contains an id; override
    code = new_id().replace("-", "")
    while code in store.verification_code_uniq:
        code = new_id().replace("-", "")
    row = {
        "id": base["id"],
        "created_at": base["created_at"],
        "updated_at": base["created_at"],
        "version": 0,
        "trainee_id": enrollment["trainee_id"],
        "certificate_template_id": template["id"],
        "source_enrollment_id": enrollment["id"],
        "issued_at": issued,
        "expires_at": format_iso(expires_dt),
        "status": "VALID",
        "verification_code": code,
    }
    store.certificates[base["id"]] = row
    store.verification_code_uniq[code] = base["id"]
    return row


# ----- session cancellation cascade -----


def cascade_cancel_session(session: dict) -> None:
    """Cancel all non-terminal enrollments; possibly mark cancellation_fee_charged."""
    store = get_store()
    cur_now = now_dt()
    sa = parse_iso(session["start_at"])
    threshold = sa - timedelta(hours=48)

    # cancel enrollments
    for e in list(store.enrollments.values()):
        if e["session_id"] != session["id"]:
            continue
        if e["status"] in ("PENDING_APPROVAL", "CONFIRMED", "WAITLISTED"):
            before = {"status": e["status"]}
            e["status"] = "CANCELLED"
            e["waitlist_position"] = None
            bump_version(e)
            from ..audit import write_audit
            write_audit("ENROLLMENT", e["id"], "enrollment.cancelled_by_session", before=before, after={"status": "CANCELLED"})

    session["enrolled_count"] = 0
    session["waitlist_count"] = 0
    if cur_now >= threshold or session.get("status") == "IN_PROGRESS":
        session["cancellation_fee_charged"] = True
