"""Session lifecycle + SessionDay weather + rainy-day reroute computation."""

from datetime import timedelta

from clock import clock, parse_iso_date
from db import db, init_lean_fields, now_iso_virtual, touch
from errors import APIError
from services.enrollments import (
    cascade_session_cancel,
    cascade_session_close,
)


# ---------- Session open ----------

def open_session(session):
    if session["status"] != "DRAFT":
        raise APIError("ERR_INVALID_STATE")
    # Preconditions
    if session["week_count"] < 1:
        raise APIError("ERR_INVALID_STATE")
    if session["weekly_capacity"] < 1:
        raise APIError("ERR_INVALID_STATE")
    if session["age_min"] > session["age_max"]:
        raise APIError("ERR_INVALID_STATE")
    # Materialize SessionDay rows: one per business day per ISO week
    week_start = parse_iso_date(session["week_start"])
    for wi in range(session["week_count"]):
        for dow in range(5):  # Mon..Fri business days
            day_date = week_start + timedelta(days=7 * wi + dow)
            sd = init_lean_fields({
                "session_id": session["id"],
                "week_index": wi,
                "day_date": day_date.isoformat(),
                "weather_status": "NORMAL",
                "rainy_day_used": 0,
                "outdoor_headcount": 0,
            })
            db.session_days[sd["id"]] = sd
    session["status"] = "OPEN"
    touch(session)
    return session


# ---------- Session close ----------

def close_session(session):
    if session["status"] != "OPEN":
        raise APIError("ERR_INVALID_STATE")
    # Precondition: every week has reached week_start + 7 days on the clock.
    # i.e., for week_index in [0, week_count), week_start + 7*(wi+1) days <= now.
    week_start = parse_iso_date(session["week_start"])
    from datetime import datetime, timezone, time as dtime
    now = clock.now()
    last_week_end = datetime.combine(
        week_start + timedelta(days=7 * session["week_count"]),
        dtime.min,
        tzinfo=timezone.utc,
    )
    if now < last_week_end:
        raise APIError("ERR_INVALID_STATE", "Not all weeks have elapsed.")
    cascade_session_close(session)
    session["status"] = "CLOSED"
    touch(session)
    return session


# ---------- Session cancel ----------

def cancel_session(session):
    if session["status"] == "DRAFT":
        session["status"] = "CANCELLED"
        touch(session)
        return session
    if session["status"] == "OPEN":
        cascade_session_cancel(session)
        session["status"] = "CANCELLED"
        touch(session)
        return session
    raise APIError("ERR_INVALID_STATE")


# ---------- Weather / rainy-day ----------

def _confirmed_attendees_for_day(session_day):
    """COUNT(Enrollment WHERE session_id=sd.session_id, week_index=sd.week_index, status=CONFIRMED)."""
    return sum(
        1
        for e in db.enrollments.values()
        if e["session_id"] == session_day["session_id"]
        and e["week_index"] == session_day["week_index"]
        and e["status"] == "CONFIRMED"
    )


def _pool_already_used_in_week(session_day):
    """Sum rainy_day_used over OTHER SessionDay rows in same (session, week_index) with weather_status=RAINY."""
    return sum(
        sd["rainy_day_used"]
        for sd in db.session_days.values()
        if sd["session_id"] == session_day["session_id"]
        and sd["week_index"] == session_day["week_index"]
        and sd["id"] != session_day["id"]
        and sd["weather_status"] == "RAINY"
    )


def reroute_preview(session_day):
    """Diagnostic preview — what would happen if marked RAINY now."""
    session = db.sessions[session_day["session_id"]]
    confirmed = _confirmed_attendees_for_day(session_day)
    used = _pool_already_used_in_week(session_day)
    remaining = max(0, session["rainy_day_pool_per_week"] - used)
    would_reroute = min(confirmed, remaining)
    overflow = confirmed - would_reroute
    return {
        "confirmed_attendees_for_day": confirmed,
        "pool_already_used_in_week": used,
        "pool_remaining": remaining,
        "would_reroute": would_reroute,
        "outdoor_overflow": overflow,
    }, overflow > 0


def set_weather(session_day, new_weather):
    """Per SessionDay state machine."""
    if new_weather not in {"NORMAL", "RAINY", "CLOSED"}:
        raise APIError("ERR_VALIDATION", "weather_status invalid.")

    # Temporal check (priority 11 — ERR_INVALID_WEEK_INDEX for past day_date)
    today = clock.now().date()
    day_date = parse_iso_date(session_day["day_date"])
    if day_date < today:
        raise APIError("ERR_INVALID_WEEK_INDEX")

    old = session_day["weather_status"]
    session = db.sessions[session_day["session_id"]]

    # Legal pair enumeration per state machine (PRD §3.8): any pair
    # not in this set — including the same-state no-op like NORMAL→NORMAL
    # — must be rejected with ERR_INVALID_STATE.
    legal_pairs = {
        ("NORMAL", "RAINY"),
        ("NORMAL", "CLOSED"),
        ("RAINY", "NORMAL"),
        ("CLOSED", "NORMAL"),
    }
    if (old, new_weather) not in legal_pairs:
        raise APIError("ERR_INVALID_STATE")

    # NORMAL→RAINY also requires session=OPEN
    if (old, new_weather) == ("NORMAL", "RAINY") and session["status"] != "OPEN":
        raise APIError("ERR_INVALID_STATE", "Session is not OPEN.")

    if (old, new_weather) == ("NORMAL", "RAINY"):
        confirmed = _confirmed_attendees_for_day(session_day)
        used = _pool_already_used_in_week(session_day)
        remaining = max(0, session["rainy_day_pool_per_week"] - used)
        session_day["rainy_day_used"] = min(confirmed, remaining)
        session_day["outdoor_headcount"] = confirmed - session_day["rainy_day_used"]
    elif (old, new_weather) == ("NORMAL", "CLOSED"):
        session_day["rainy_day_used"] = 0
        session_day["outdoor_headcount"] = 0
    elif (old, new_weather) == ("RAINY", "NORMAL"):
        confirmed = _confirmed_attendees_for_day(session_day)
        session_day["rainy_day_used"] = 0
        session_day["outdoor_headcount"] = confirmed
    elif (old, new_weather) == ("CLOSED", "NORMAL"):
        confirmed = _confirmed_attendees_for_day(session_day)
        session_day["rainy_day_used"] = 0
        session_day["outdoor_headcount"] = confirmed

    session_day["weather_status"] = new_weather
    return session_day
