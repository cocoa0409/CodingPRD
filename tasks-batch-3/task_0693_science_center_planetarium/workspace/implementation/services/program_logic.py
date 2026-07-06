"""ProgramSession enrolled_count recompute, FULL bubble-up, waitlist (PRD §3.6)."""
from db import db


def recompute_enrolled_count(program):
    """enrolled_count == number of this session's Registrations that are ENROLLED."""
    total = 0
    for r in db.registrations.values():
        if r["program_session_id"] == program["id"] and r["status"] == "ENROLLED":
            total += 1
    program["enrolled_count"] = total
    return total


def waitlisted_registrations(program):
    """WAITLISTED registrations of a session, ordered by created_at ASC."""
    items = [
        r for r in db.registrations.values()
        if r["program_session_id"] == program["id"] and r["status"] == "WAITLISTED"
    ]
    items.sort(key=lambda r: r["_created_seq"])
    return items


def recompute_waitlist_positions(program):
    """1-based waitlist_position for WAITLISTED registrations (created_at ASC).

    Non-waitlisted registrations carry a null position.
    """
    wl = waitlisted_registrations(program)
    for idx, r in enumerate(wl, start=1):
        r["waitlist_position"] = idx
    for r in db.registrations.values():
        if r["program_session_id"] == program["id"] and r["status"] != "WAITLISTED":
            r["waitlist_position"] = None
