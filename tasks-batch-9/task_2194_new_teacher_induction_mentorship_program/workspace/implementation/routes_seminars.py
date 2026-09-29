"""Seminar sessions and attendance records."""

from flask import Blueprint

import calc
import domain
from auth import ADMIN, LEAD, NOVICE, actor, guard, own_site, role, scope_rows
from envelope import list_response, pagination, row_response
from errors import ApiError
from store import db, iso, new_row, now, parse_iso, sorted_rows, touch
from validators import (apply_filters, body, datetime_field, enum_field, fk,
                        int_field, path_row, str_field)

bp = Blueprint("seminars", __name__)


def _recompute_session_credits(session):
    session["credited_attendance_count"] = len(
        [a for a in domain.attendances_of_session(session["id"]) if a.get("credited")])


def _refresh_session_novices(session):
    for row in domain.attendances_of_session(session["id"]):
        novice = db.novices.get(row.get("novice_id"))
        if novice is not None:
            domain.refresh_novice(novice)


@bp.post("/seminar-sessions")
@guard([ADMIN])
def create_session():
    data = body()
    cohort = fk("cohorts", data, "cohort_id")
    str_field(data, "cohort_id", 1, None)
    session_index = int_field(data, "session_index", 1, 24)
    topic = str_field(data, "topic", 1, 160)
    start = datetime_field(data, "scheduled_start")
    end = datetime_field(data, "scheduled_end")
    minutes = calc.duration_minutes(start, end)

    if cohort.get("status") not in ("FORMING", "RUNNING"):
        raise ApiError("ERR_COHORT_STATE_INVALID")

    for other in domain.sessions_of_cohort(cohort["id"]):
        if other.get("status") not in ("SCHEDULED", "HELD"):
            continue
        other_start = parse_iso(other.get("scheduled_start"))
        other_end = parse_iso(other.get("scheduled_end"))
        if other_start is None or other_end is None:
            continue
        if calc.seminar_overlap(start, end, other_start, other_end):
            raise ApiError("ERR_SEMINAR_SESSION_OVERLAP")

    week_start, week_end = calc.iso_week_bounds(start)
    booked = 0
    for other in domain.sessions_of_cohort(cohort["id"]):
        if other.get("status") not in ("SCHEDULED", "HELD"):
            continue
        other_start = parse_iso(other.get("scheduled_start"))
        if other_start is None or not (week_start <= other_start < week_end):
            continue
        booked += int(other.get("scheduled_minutes") or 0)
    if booked + minutes > calc.WEEKLY_SEMINAR_CAP_MINUTES:
        raise ApiError("ERR_COHORT_WEEKLY_SEMINAR_CAP_EXCEEDED")

    if not calc.window_ok(start, end):
        raise ApiError("ERR_INVALID_WINDOW")

    for other in domain.sessions_of_cohort(cohort["id"]):
        if other.get("session_index") == session_index:
            raise ApiError("ERR_DUPLICATE_SESSION_INDEX")

    row = new_row({
        "cohort_id": cohort["id"],
        "session_index": session_index,
        "topic": topic,
        "scheduled_start": iso(start),
        "scheduled_end": iso(end),
        "scheduled_minutes": minutes,
        "status": "SCHEDULED",
        "credited_attendance_count": 0,
        "held_at": None,
        "cancelled_at": None,
        "cancel_reason": None,
    })
    db.sessions[row["id"]] = row
    return row_response(row, 201)


@bp.get("/seminar-sessions")
@guard([ADMIN, LEAD, NOVICE])
def list_sessions():
    rows = sorted_rows(list(db.sessions.values()))
    rows = apply_filters(rows, {"cohort_id": ("cohort_id", "str"),
                                "status": ("status", "str")})
    limit, offset = pagination()
    return list_response(rows, limit, offset)


@bp.get("/seminar-sessions/<row_id>")
@guard([ADMIN, LEAD, NOVICE])
def get_session(row_id):
    return row_response(path_row("sessions", row_id))


@bp.post("/seminar-sessions/<row_id>/status")
@guard([ADMIN])
def set_session_status(row_id):
    session = path_row("sessions", row_id)
    data = body()
    status = enum_field(data, "status", ("HELD", "CANCELLED"))
    cancel_reason = str_field(data, "cancel_reason", 1, 1000,
                              required=status == "CANCELLED")
    cohort = db.cohorts.get(session.get("cohort_id"))

    if session.get("status") != "SCHEDULED":
        raise ApiError("ERR_SESSION_STATE_INVALID")
    if status == "HELD":
        end = parse_iso(session.get("scheduled_end"))
        if end is None or now() < end:
            raise ApiError("ERR_SESSION_STATE_INVALID")
        if cohort is None or cohort.get("status") not in ("FORMING", "RUNNING"):
            raise ApiError("ERR_COHORT_STATE_INVALID")
        session["status"] = "HELD"
        session["held_at"] = iso(now())
        _recompute_session_credits(session)
        touch(session)
        if cohort.get("status") == "FORMING":
            cohort["status"] = "RUNNING"
            touch(cohort)
        _refresh_session_novices(session)
    else:
        session["status"] = "CANCELLED"
        session["cancelled_at"] = iso(now())
        session["cancel_reason"] = cancel_reason
        session["credited_attendance_count"] = 0
        touch(session)
        _refresh_session_novices(session)
    return row_response(session)


# ----------------------------------------------------------------- attendances

@bp.post("/seminar-attendances")
@guard([ADMIN, LEAD])
def record_attendance():
    data = body()
    session = fk("sessions", data, "session_id")
    novice = fk("novices", data, "novice_id")
    str_field(data, "session_id", 1, None)
    str_field(data, "novice_id", 1, None)
    status = enum_field(data, "attendance_status", calc.ATTENDANCE_STATUSES)
    minutes = int_field(data, "minutes_attended", 0, 480)
    if role() == LEAD:
        own_site(novice.get("site_id"))

    if session.get("status") != "SCHEDULED":
        raise ApiError("ERR_SESSION_STATE_INVALID")
    if novice.get("cohort_id") != session.get("cohort_id"):
        raise ApiError("ERR_COHORT_MISMATCH")
    for other in domain.attendances_of_session(session["id"]):
        if other.get("novice_id") == novice["id"]:
            raise ApiError("ERR_DUPLICATE_ATTENDANCE")

    ratio, credited = calc.attendance_credit(status, minutes,
                                             session.get("scheduled_minutes"))
    row = new_row({
        "session_id": session["id"],
        "novice_id": novice["id"],
        "attendance_status": status,
        "minutes_attended": minutes,
        "credit_ratio": float(ratio),
        "credited": credited,
        "recorded_by_user_id": actor(),
    })
    db.attendances[row["id"]] = row
    _recompute_session_credits(session)
    touch(session)
    domain.refresh_novice(novice)
    return row_response(row, 201)


@bp.get("/seminar-attendances")
@guard([ADMIN, LEAD, NOVICE])
def list_attendances():
    rows = sorted_rows(list(db.attendances.values()))
    rows = scope_rows(rows,
                      novice_getter=lambda r: db.novices.get(r.get("novice_id")),
                      novice_id_getter=lambda r: r.get("novice_id"))
    rows = apply_filters(rows, {"session_id": ("session_id", "str"),
                                "novice_id": ("novice_id", "str"),
                                "attendance_status": ("attendance_status", "str"),
                                "credited": ("credited", "bool")})
    limit, offset = pagination()
    return list_response(rows, limit, offset)


@bp.get("/seminar-attendances/<row_id>")
@guard([ADMIN, LEAD, NOVICE])
def get_attendance(row_id):
    row = path_row("attendances", row_id)
    novice = db.novices.get(row.get("novice_id"))
    if role() == LEAD and novice is not None:
        own_site(novice.get("site_id"))
    elif role() == NOVICE and row.get("novice_id") != actor():
        raise ApiError("ERR_OWNERSHIP_VIOLATION")
    return row_response(row)
