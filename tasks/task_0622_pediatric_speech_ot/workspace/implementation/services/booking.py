"""Appointment booking battery (PRD §3.5). Shared by direct booking and waitlist accept."""

from datetime import timedelta

import errors
from errors import ApiError
from db import db
from clock import parse_iso, week_of, whole_minutes_between
from services.common import new_record, touch, lookup
from services import calc, engine

CHILD_BUFFER_MINUTES = 15


def book_appointment(child_id, therapist_id, authorization_id, plan_of_care_id,
                     start_time_dt, end_time_dt, from_waitlist_entry_id=None):
    """Run the full scheduling battery and create a SCHEDULED appointment.

    Existence of child/therapist/authorization/plan FKs must already be checked
    by the caller (they validate body FKs per PRD §2.5). This function runs the
    ordered business checks (PRD §3.5):
      6  referential  -> ERR_THERAPIST_DISCIPLINE_MISMATCH
      7  auth window  -> ERR_AUTH_WINDOW_VIOLATION
      8  therapist 2x -> ERR_THERAPIST_DOUBLE_BOOKED
      9  child 2x     -> ERR_CHILD_DOUBLE_BOOKED
      10 weekly cap   -> ERR_THERAPIST_WEEKLY_CAP_EXCEEDED
      12 visit cap    -> ERR_VISIT_CAP_EXCEEDED  (the last word)
    Returns the created appointment record.
    """
    child = db.children[child_id]
    therapist = db.therapists[therapist_id]
    auth = db.authorizations[authorization_id]
    plan = db.plans_of_care[plan_of_care_id]

    # ---- priority 6: referential checks (ERR_THERAPIST_DISCIPLINE_MISMATCH) ----
    # therapist.discipline == authorization.discipline;
    # plan.child_id == auth.child_id == body child_id; plan is ACTIVE.
    if therapist["discipline"] != auth["discipline"]:
        raise ApiError(errors.ERR_THERAPIST_DISCIPLINE_MISMATCH, 409,
                       "Therapist discipline does not match authorization discipline.")
    if not (plan["child_id"] == auth["child_id"] == child_id):
        raise ApiError(errors.ERR_THERAPIST_DISCIPLINE_MISMATCH, 409,
                       "Plan/authorization/child mismatch.")
    if plan["status"] != "ACTIVE":
        raise ApiError(errors.ERR_THERAPIST_DISCIPLINE_MISMATCH, 409,
                       "Plan of care is not ACTIVE.")

    # ---- priority 7: authorization window (ERR_AUTH_WINDOW_VIOLATION) ----
    # The authorization must not be in a lifecycle state that bars booking by its
    # window/expiry. EXPIRED (clock past valid_until) and the terminal CLOSED both
    # bar any new reservation -> ERR_AUTH_WINDOW_VIOLATION (PRD §3.4 expiry, §3.5).
    # EXHAUSTED is NOT a window violation: PRD §3.4 says a reservation against an
    # EXHAUSTED authorization is rejected with ERR_VISIT_CAP_EXCEEDED, and §3.5
    # makes the visit-cap test "the last word". REAUTH_REQUESTED remains bookable
    # while available_visits > 0 (PRD §3.4), and otherwise falls to the capacity
    # check. So the window check only rejects EXPIRED/CLOSED here, then validates
    # the temporal interval against the window.
    valid_from = parse_iso(auth["valid_from"])
    valid_until = parse_iso(auth["valid_until"])
    if auth["status"] in ("EXPIRED", "CLOSED"):
        raise ApiError(errors.ERR_AUTH_WINDOW_VIOLATION, 409,
                       "Authorization is not ACTIVE.")
    if not (valid_from <= start_time_dt and end_time_dt <= valid_until):
        raise ApiError(errors.ERR_AUTH_WINDOW_VIOLATION, 409,
                       "Appointment interval falls outside the authorization window.")

    # ---- priority 8: therapist double-booking (ERR_THERAPIST_DOUBLE_BOOKED) ----
    # Half-open [start, end); adjacency (end == next start) allowed.
    for appt in db.appointments.values():
        if appt["therapist_id"] != therapist_id or appt["status"] != "SCHEDULED":
            continue
        s2 = parse_iso(appt["start_time"])
        e2 = parse_iso(appt["end_time"])
        if start_time_dt < e2 and s2 < end_time_dt:
            raise ApiError(errors.ERR_THERAPIST_DOUBLE_BOOKED, 409,
                           "Therapist already booked for an overlapping interval.")

    # ---- priority 9: child double-booking with 15-min buffer (ERR_CHILD_DOUBLE_BOOKED) ----
    # Conflict when start < e2 + 15m AND s2 < end + 15m (existing expanded by 15m on end).
    buffer = timedelta(minutes=CHILD_BUFFER_MINUTES)
    for appt in db.appointments.values():
        if appt["child_id"] != child_id or appt["status"] != "SCHEDULED":
            continue
        s2 = parse_iso(appt["start_time"])
        e2 = parse_iso(appt["end_time"])
        if start_time_dt < (e2 + buffer) and s2 < (end_time_dt + buffer):
            raise ApiError(errors.ERR_CHILD_DOUBLE_BOOKED, 409,
                           "Child has a conflicting session within the 15-minute buffer.")

    # ---- priority 10: therapist weekly-minutes cap (ERR_THERAPIST_WEEKLY_CAP_EXCEEDED) ----
    duration = whole_minutes_between(start_time_dt, end_time_dt)
    wk = week_of(start_time_dt)
    already = calc.scheduled_minutes(therapist_id, wk)
    if already + duration > therapist["weekly_visit_minutes_cap"]:
        raise ApiError(errors.ERR_THERAPIST_WEEKLY_CAP_EXCEEDED, 409,
                       "Therapist weekly minutes cap would be exceeded.")

    # ---- priority 12: visit-cap capacity (ERR_VISIT_CAP_EXCEEDED) -- the last word ----
    if auth["available_visits"] < 1:
        raise ApiError(errors.ERR_VISIT_CAP_EXCEEDED, 402,
                       "No available visits remain on the authorization.")

    # ---- create the appointment; reserve a visit ----
    appt = new_record({
        "child_id": child_id,
        "therapist_id": therapist_id,
        "authorization_id": authorization_id,
        "plan_of_care_id": plan_of_care_id,
        "start_time": _iso_in(start_time_dt),
        "end_time": _iso_in(end_time_dt),
        "duration_minutes": duration,
        "from_waitlist_entry_id": from_waitlist_entry_id,
        "status": "SCHEDULED",
    })
    db.appointments[appt["id"]] = appt

    # Authorization.reserved_visits += 1; recompute; EXHAUSTED if available == 0;
    # version increments (handled by reconcile_authorization via touch).
    engine.reconcile_authorization(auth)
    # Child active_appointment_count changes.
    engine.recompute_child(child)
    return appt


def _iso_in(dt):
    """Store start/end as the canonical ISO form (three fractional digits, Z)."""
    from clock import format_iso
    return format_iso(dt)
