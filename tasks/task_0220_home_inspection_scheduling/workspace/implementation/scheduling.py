"""Schedule-time validation and side effects shared by /schedule and /reinspect.

Business checks run in this pinned priority order (PRD §3.3):
  1. order is in REQUESTED status            -> ERR_INVALID_STATE (409)
  2. inspector exists and is ACTIVE          -> ERR_INVALID_STATE (409) if SUSPENDED
  3. certification + FOUR_POINT eligibility  -> ERR_INSPECTOR_NOT_CERTIFIED (409)
  4. territory match                         -> ERR_TERRITORY_MISMATCH (409)
  5. travel-buffer double-booking            -> ERR_INSPECTOR_DOUBLE_BOOKED (409)
  6. same-day property conflict              -> ERR_PROPERTY_SAME_DAY_CONFLICT (409)
  7. daily-capacity                          -> ERR_DAILY_CAPACITY_EXCEEDED (409)

A SUSPENDED inspector cannot be booked. Inspector existence is checked earlier
(ERR_NOT_FOUND). The ACTIVE requirement is a state precondition of the schedule
transition (scaffold: "Inspector.status == ACTIVE"); there is no dedicated error
code for a suspended inspector, so it is reported as ERR_INVALID_STATE (the
state-category error, priority 5).
"""
from datetime import datetime, timezone, timedelta

import errors
import calculations as calc
from db import db
from services import (
    booked_minutes,
    NON_TERMINAL_ORDER_STATUSES,
)

FOUR_POINT_MAX_YEAR_BUILT = 2000  # scaffold business_constants
MIN_REINSPECTION_GAP_HOURS = 48   # scaffold business_constants


def parse_iso_datetime(value):
    """Parse an ISO 8601 datetime string into an aware UTC datetime.

    Raises ERR_INVALID_REQUEST on malformed input. Accepts a trailing 'Z'.
    """
    if not isinstance(value, str) or value == "":
        raise errors.invalid_request("scheduled_start must be an ISO 8601 string.")
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        raise errors.invalid_request("scheduled_start is not a valid ISO 8601 datetime.")
    if dt.tzinfo is None:
        # Treat a naive timestamp as UTC.
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


def calendar_date(dt):
    """YYYY-MM-DD UTC calendar date string."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d")


def _appointment_window(start_dt, duration_minutes, buffer_minutes):
    """Half-open [start, start + duration + buffer) window for overlap testing."""
    end = start_dt + timedelta(minutes=duration_minutes + buffer_minutes)
    return start_dt, end


def check_certification(order, inspector, prop):
    """Certification + FOUR_POINT eligibility (PRD §3.3)."""
    itype = order["inspection_type"]
    if itype not in inspector["certifications"]:
        raise errors.ApiError(
            errors.ERR_INSPECTOR_NOT_CERTIFIED, 409,
            "Inspector is not certified for %s." % itype,
        )
    if itype == "FOUR_POINT" and prop["year_built"] > FOUR_POINT_MAX_YEAR_BUILT:
        raise errors.ApiError(
            errors.ERR_INSPECTOR_NOT_CERTIFIED, 409,
            "FOUR_POINT not eligible for a property built after %d." % FOUR_POINT_MAX_YEAR_BUILT,
        )


def check_territory(inspector, prop):
    """Property ZIP must be inside the inspector's territory ZIP list."""
    territory = db.territories.get(inspector["territory_id"])
    if territory is None or prop["zip_code"] not in territory["zip_codes"]:
        raise errors.ApiError(
            errors.ERR_TERRITORY_MISMATCH, 409,
            "Property ZIP is not inside the inspector's territory.",
        )
    return territory


def check_double_booking(inspector, territory, start_dt, duration_minutes, exclude_order_id=None):
    """Travel-buffer half-open overlap against the inspector's other appointments."""
    buffer_minutes = territory["travel_buffer_minutes"]
    new_start, new_end = _appointment_window(start_dt, duration_minutes, buffer_minutes)
    for o in db.inspection_orders.values():
        if o["id"] == exclude_order_id:
            continue
        if o["inspector_id"] != inspector["id"]:
            continue
        if o["status"] not in NON_TERMINAL_ORDER_STATUSES and o["status"] != "DELIVERED":
            continue
        existing_start_raw = o.get("scheduled_start")
        if not existing_start_raw:
            continue
        existing_start = parse_iso_datetime(existing_start_raw)
        ex_start, ex_end = _appointment_window(
            existing_start, o["duration_minutes"] or 0, buffer_minutes
        )
        # Half-open overlap: [a_start, a_end) intersects [b_start, b_end).
        if new_start < ex_end and ex_start < new_end:
            raise errors.ApiError(
                errors.ERR_INSPECTOR_DOUBLE_BOOKED, 409,
                "scheduled_start collides with the inspector's existing appointment.",
            )


def check_same_day_property(property_id, scheduled_date, exclude_order_id=None):
    """No other non-terminal order for the same property shares the calendar date."""
    for o in db.inspection_orders.values():
        if o["id"] == exclude_order_id:
            continue
        if o["property_id"] != property_id:
            continue
        if o["status"] not in NON_TERMINAL_ORDER_STATUSES:
            continue
        if o.get("scheduled_date") == scheduled_date:
            raise errors.ApiError(
                errors.ERR_PROPERTY_SAME_DAY_CONFLICT, 409,
                "Another non-terminal order for this property occupies that date.",
            )


def check_daily_capacity(inspector, scheduled_date, duration_minutes, exclude_order_id=None):
    """Booked minutes after adding the new order must be <= daily_capacity_minutes."""
    already = booked_minutes(inspector["id"], scheduled_date, exclude_order_id=exclude_order_id)
    if already + duration_minutes > inspector["daily_capacity_minutes"]:
        raise errors.ApiError(
            errors.ERR_DAILY_CAPACITY_EXCEEDED, 409,
            "Booking would exceed the inspector's daily capacity.",
        )
