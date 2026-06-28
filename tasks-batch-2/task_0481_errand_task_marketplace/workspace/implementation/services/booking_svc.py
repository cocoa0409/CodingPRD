"""Booking-domain services shared by one-off bookings and recurring series:
build a booking record, offer (pin quote + window), and the claim/schedule checks."""
import errors
from errors import err
from db import db, parse_iso, iso_millis, clock_now
from services import core


def build_booking(*, client_id, category_id, dispatch_mode, scheduled_start_dt,
                  estimated_hours, tip_cents, series_id=None, status="DRAFT",
                  tasker_id=None):
    rec = {
        "client_id": client_id,
        "category_id": category_id,
        "tasker_id": tasker_id,
        "series_id": series_id,
        "dispatch_mode": dispatch_mode,
        "scheduled_start": iso_millis(scheduled_start_dt),
        "scheduled_end": None,
        "estimated_hours": estimated_hours,
        "actual_hours": None,
        "status": status,
        "estimated_labor_cents": None,
        "estimated_service_fee_cents": None,
        "estimated_total_cents": None,
        "tip_cents": tip_cents,
        "reschedule_count": 0,
        "proposed_start": None,
        "reschedule_pending": False,
        "cancelled_by": None,
        "_scheduled_start_dt": scheduled_start_dt,
        "_scheduled_end_dt": None,
        "_proposed_start_dt": None,
    }
    core.stamp_create(rec)
    return rec


def apply_offer(booking, category):
    """Pin quote estimate and compute the scheduled window (DRAFT->OFFERED side effects)."""
    end_dt = core.schedule_window_end(booking["_scheduled_start_dt"], booking, category)
    booking["_scheduled_end_dt"] = end_dt
    booking["scheduled_end"] = iso_millis(end_dt)
    core.quote_estimate(booking, category)


def run_schedule_checks(tasker, booking, start_dt, end_dt):
    """Window containment (pri 8) then buffered overlap (pri 9)."""
    if not core.window_contained(tasker["id"], start_dt, end_dt):
        raise err(errors.ERR_OUTSIDE_AVAILABILITY, "Booking not inside any OPEN availability window")
    if core.has_overlap(tasker["id"], start_dt, end_dt, booking["id"]):
        raise err(errors.ERR_SCHEDULE_CONFLICT, "Booking collides with another active booking")
