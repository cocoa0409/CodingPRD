"""Session/attendance shared operations: seat-count recompute and cancel
cascade (PRD §3.5, §2.5)."""
from db import db


def recompute_booked_seat_count(session):
    """booked_seat_count = number of AttendanceRecords on the session whose
    status is BOOKED or PRESENT."""
    count = sum(
        1 for r in db.attendance.values()
        if r["session_id"] == session["id"] and r["status"] in ("BOOKED", "PRESENT")
    )
    if session["booked_seat_count"] != count:
        session["booked_seat_count"] = count
        db.touch(session)


def cancel_session_cascade(session):
    """Drive session SCHEDULED/OPEN -> CANCELLED, its BOOKED/PRESENT records ->
    CANCELLED, then booked_seat_count = 0. Used by /cancel and by center
    suspension. Each touched entity gets version++/updated_at."""
    session["status"] = "CANCELLED"
    db.touch(session)
    for rec in db.attendance.values():
        if rec["session_id"] == session["id"] and rec["status"] in ("BOOKED", "PRESENT"):
            rec["status"] = "CANCELLED"
            db.touch(rec)
    # recompute -> 0 (a versioned mutation only if it changed)
    if session["booked_seat_count"] != 0:
        session["booked_seat_count"] = 0
        db.touch(session)
