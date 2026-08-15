"""Authorization-expiry sweep and its depth-3 cascade (PRD 3.2, calculations.authorization_expiry).

Runs after every logical-clock advance: AUTHORIZED records whose authorized_until
is at or before the new reading expire (inclusive boundary). A course whose last
AUTHORIZED record lapses flips to SUSPENDED (derived); its SCHEDULED sessions are
cancelled and those sessions' ASSIGNED proctor assignments released. Registrations
are deliberately untouched.
"""
from db import db
from services.core import touch
from services.derived import authorized_teacher_count


def _cancel_session(session):
    session["status"] = "CANCELLED"
    touch(session)
    for pa in db["proctor_assignments"].values():
        if pa["session_id"] == session["id"] and pa["status"] == "ASSIGNED":
            pa["status"] = "RELEASED"
            touch(pa)


def run_expiry_sweep(now):
    expired = []
    for ta in sorted(db["teacher_authorizations"].values(), key=lambda r: r["_seq"]):
        if (ta["status"] == "AUTHORIZED" and ta["authorized_until"] is not None
                and now >= ta["authorized_until"]):
            ta["status"] = "EXPIRED"
            touch(ta)
            expired.append(ta)
    # Cascade fires on each course's 1 -> 0 authorized-count transition. An
    # expiring record was AUTHORIZED, so count == 0 afterwards means this sweep
    # took the course from 1 to 0 (multiple expiries of one course dedupe).
    for course_id in dict.fromkeys(ta["course_id"] for ta in expired):
        if authorized_teacher_count(course_id) == 0:
            for s in sorted(db["exam_sessions"].values(), key=lambda r: r["_seq"]):
                if s["course_id"] == course_id and s["status"] == "SCHEDULED":
                    _cancel_session(s)
    return len(expired)
