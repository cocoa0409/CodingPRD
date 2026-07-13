"""In-store services: artist time is exclusive, with a trailing sanitation buffer."""
from datetime import timedelta

from db import db
from errors import ApiError
from util import parse_dt

SANITATION_BUFFER_MINUTES = 15
DURATION_MINUTES = {"BROW": 30, "MAKEOVER": 60}
OCCUPYING_STATUSES = ("CONFIRMED", "RESCHEDULE_PENDING")


def occupied_interval(start_at, duration_minutes):
    """Half-open [start_at, start_at + duration + buffer)."""
    start = parse_dt(start_at) if isinstance(start_at, str) else start_at
    end = start + timedelta(minutes=duration_minutes + SANITATION_BUFFER_MINUTES)
    return start, end


def assert_no_artist_conflict(artist_id, start_at, duration_minutes, exclude_booking_id=None):
    new_start, new_end = occupied_interval(start_at, duration_minutes)
    for booking in db.bookings.values():
        if booking["artist_id"] != artist_id:
            continue
        if booking["id"] == exclude_booking_id:
            continue
        if booking["status"] not in OCCUPYING_STATUSES:
            continue
        # a RESCHEDULE_PENDING booking still occupies its ORIGINAL start_at window
        other_start, other_end = occupied_interval(booking["start_at"], booking["duration_minutes"])
        if new_start < other_end and other_start < new_end:
            raise ApiError("ERR_ARTIST_TIME_CONFLICT", "the artist is already booked in that window")
