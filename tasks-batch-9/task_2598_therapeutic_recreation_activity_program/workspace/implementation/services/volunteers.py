"""Volunteer hour ledgers, time conflicts and withdrawal cascades."""
from datetime import datetime, time, timedelta, timezone

from db import overlaps, parse_datetime
from services import constants as C
from services.numbers import dec, divide, rhu

ACTIVE_ASSIGNMENT_STATUSES = ("PROPOSED", "CONFIRMED")


def assignment_hours(session):
    starts_at = parse_datetime(session["starts_at"])
    ends_at = parse_datetime(session["ends_at"])
    seconds = (ends_at - starts_at).total_seconds()
    return float(rhu(divide(dec(repr(seconds)), 3600), 2))


def iso_week_bounds(clock):
    monday = clock.date() - timedelta(days=clock.weekday())
    lo = datetime.combine(monday, time(0, 0, 0), tzinfo=timezone.utc)
    return lo, lo + timedelta(days=7)


def volunteer_assignments(st, volunteer_id):
    return [a for a in st.assignments.values() if a["volunteer_id"] == volunteer_id]


def scheduled_hours_week(st, volunteer_id, extra_assignments=()):
    lo, hi = iso_week_bounds(st.now())
    total = dec(0)
    rows = list(volunteer_assignments(st, volunteer_id)) + list(extra_assignments)
    for assignment in rows:
        if assignment["status"] not in ACTIVE_ASSIGNMENT_STATUSES:
            continue
        session = st.sessions.get(assignment["session_id"])
        if session is None:
            continue
        starts_at = parse_datetime(session["starts_at"])
        if starts_at is None or not (lo <= starts_at < hi):
            continue
        total += dec(repr(assignment["hours"]))
    return float(rhu(total, 2))


def credited_service_hours(st, volunteer_id):
    total = dec(0)
    for assignment in volunteer_assignments(st, volunteer_id):
        if assignment["status"] != "COMPLETED":
            continue
        session = st.sessions.get(assignment["session_id"])
        if session is None or session["status"] != "DOCUMENTED":
            continue
        total += dec(repr(assignment["hours"]))
    return float(rhu(total, 2))


def refresh_hours(st, volunteer, ctx, force_bump=False):
    values = {
        "scheduled_hours_week": scheduled_hours_week(st, volunteer["id"]),
        "credited_service_hours": credited_service_hours(st, volunteer["id"]),
    }
    if force_bump:
        for key, value in values.items():
            volunteer[key] = value
        ctx.bump(volunteer)
    else:
        ctx.set_fields(volunteer, values)


def time_conflict(st, volunteer_id, session, ignore_assignment_id=None):
    lo = parse_datetime(session["starts_at"])
    hi = parse_datetime(session["ends_at"])
    for assignment in volunteer_assignments(st, volunteer_id):
        if assignment["status"] not in ACTIVE_ASSIGNMENT_STATUSES:
            continue
        if ignore_assignment_id and assignment["id"] == ignore_assignment_id:
            continue
        other = st.sessions.get(assignment["session_id"])
        if other is None or other["id"] == session["id"]:
            continue
        o_lo = parse_datetime(other["starts_at"])
        o_hi = parse_datetime(other["ends_at"])
        if overlaps(lo, hi, o_lo, o_hi):
            return assignment
    return None


def withdraw_for_volunteer(st, volunteer, reason, ctx):
    """System withdrawal of every live assignment held by one volunteer."""
    for assignment in volunteer_assignments(st, volunteer["id"]):
        if assignment["status"] not in ACTIVE_ASSIGNMENT_STATUSES:
            continue
        assignment["status"] = "WITHDRAWN"
        assignment["withdrawn_reason"] = reason
        ctx.bump(assignment)
    refresh_hours(st, volunteer, ctx, force_bump=True)


def withdraw_for_session(st, session, reason, ctx):
    """System withdrawal of every live assignment attached to one session."""
    affected = []
    for assignment in st.assignments.values():
        if assignment["session_id"] != session["id"]:
            continue
        if assignment["status"] not in ACTIVE_ASSIGNMENT_STATUSES:
            continue
        assignment["status"] = "WITHDRAWN"
        assignment["withdrawn_reason"] = reason
        ctx.bump(assignment)
        affected.append(assignment["volunteer_id"])
    for volunteer_id in dict.fromkeys(affected):
        volunteer = st.volunteers.get(volunteer_id)
        if volunteer is not None:
            refresh_hours(st, volunteer, ctx, force_bump=True)


def complete_for_session(st, session, ctx):
    """Session documentation closes out every CONFIRMED assignment."""
    affected = []
    for assignment in st.assignments.values():
        if assignment["session_id"] != session["id"]:
            continue
        if assignment["status"] != "CONFIRMED":
            continue
        assignment["status"] = "COMPLETED"
        ctx.bump(assignment)
        affected.append(assignment["volunteer_id"])
    for volunteer_id in dict.fromkeys(affected):
        volunteer = st.volunteers.get(volunteer_id)
        if volunteer is not None:
            refresh_hours(st, volunteer, ctx, force_bump=True)


def program_lead_present(st, session_id, ignore_assignment_id=None):
    """Another CONFIRMED PROGRAM_LEAD held by an ADULT_COMMUNITY volunteer."""
    for assignment in st.assignments.values():
        if assignment["session_id"] != session_id:
            continue
        if ignore_assignment_id and assignment["id"] == ignore_assignment_id:
            continue
        if assignment["status"] != "CONFIRMED":
            continue
        if assignment["role_type"] != "PROGRAM_LEAD":
            continue
        volunteer = st.volunteers.get(assignment["volunteer_id"])
        if volunteer is not None and volunteer["volunteer_type"] == "ADULT_COMMUNITY":
            return True
    return False


def hour_cap_exceeded(total):
    return dec(repr(total)) > dec(C.VOLUNTEER_WEEKLY_HOUR_CAP)
