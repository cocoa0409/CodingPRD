"""Visit scheduling constraints (PRD §3.5)."""
from datetime import timedelta

import db
import errors
from errors import ApiError
from money import D

NON_TERMINAL = {"SCHEDULED", "EN_ROUTE", "IN_PROGRESS"}


def _intervals_overlap_open(a_start, a_end, b_start, b_end):
    """Half-open overlap: true overlap, endpoint touch allowed."""
    return a_start < b_end and b_start < a_end


def check_caregiver_double_booked(caregiver_id, start, end):
    """PRD §3.5: caregiver half-open interval must not overlap any non-terminal
    visit for the SAME caregiver."""
    for v in db.visits.values():
        if v["caregiver_id"] != caregiver_id:
            continue
        if v["status"] not in NON_TERMINAL:
            continue
        if _intervals_overlap_open(start, end, v["_scheduled_start_dt"], v["_scheduled_end_dt"]):
            raise ApiError(errors.ERR_CAREGIVER_DOUBLE_BOOKED, 409,
                           "caregiver double-booked")


def check_client_conflict(client_id, start, end, travel_buffer_minutes):
    """PRD §3.5: visit interval expanded by travel_buffer_minutes on each side,
    treated as CLOSED, must not overlap any non-terminal visit for the SAME client."""
    buf = timedelta(minutes=travel_buffer_minutes)
    bstart = start - buf
    bend = end + buf
    for v in db.visits.values():
        if v["client_id"] != client_id:
            continue
        if v["status"] not in NON_TERMINAL:
            continue
        # Closed buffered interval: a touch within the buffer conflicts -> use <=.
        if bstart <= v["_scheduled_end_dt"] and v["_scheduled_start_dt"] <= bend:
            raise ApiError(errors.ERR_CLIENT_VISIT_CONFLICT, 409,
                           "client visit conflict (within travel buffer)")


def iso_week_key(dt):
    """ISO year-week of a datetime."""
    iso = dt.isocalendar()
    return (iso[0], iso[1])


def check_weekly_hours(caregiver, start, end):
    """PRD §3.5: scheduling must not push the caregiver's total scheduled billable
    hours within the visit's ISO week above caregiver.max_weekly_hours."""
    week = iso_week_key(start)
    new_hours = D((end - start).total_seconds()) / D(3600)
    existing = D(0)
    for v in db.visits.values():
        if v["caregiver_id"] != caregiver["id"]:
            continue
        if v["status"] not in NON_TERMINAL:
            continue
        if iso_week_key(v["_scheduled_start_dt"]) != week:
            continue
        dur = D((v["_scheduled_end_dt"] - v["_scheduled_start_dt"]).total_seconds()) / D(3600)
        existing += dur
    total = existing + new_hours
    if total > D(caregiver["max_weekly_hours"]):
        raise ApiError(errors.ERR_WEEKLY_HOURS_EXCEEDED, 409,
                       "weekly scheduled hours exceeded")
