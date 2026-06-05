"""Temporal collision checks per scaffold §1.4 (priority 12, 13) / PRD §3.5.

Cleaner double-booking (ERR_CLEANER_DOUBLE_BOOKED): the assigned cleaner's
other non-terminal booking, with its interval extended by TRAVEL_BUFFER_MIN on
each side, must not overlap this booking's raw half-open interval.

Address double-booking (ERR_ADDRESS_DOUBLE_BOOKED): the address's other
non-terminal booking's RAW half-open interval must not overlap this booking's
raw half-open interval (no travel buffer; shared boundary instant does not
collide).

Non-terminal for collision purposes = status in {SCHEDULED, RESCHEDULED}.
"""
from datetime import timedelta

import db
from errors import err
from constants import TRAVEL_BUFFER_MIN

NON_TERMINAL = {"SCHEDULED", "RESCHEDULED"}


def _overlaps(a_start, a_end, b_start, b_end):
    """Half-open interval overlap test: [a_start, a_end) vs [b_start, b_end)."""
    return a_start < b_end and b_start < a_end


def check_cleaner_double_booked(cleaner_id, start, end, exclude_booking_id=None):
    if cleaner_id is None:
        return
    buf = timedelta(minutes=TRAVEL_BUFFER_MIN)
    for b in db.bookings.values():
        if exclude_booking_id is not None and b["id"] == exclude_booking_id:
            continue
        if b.get("cleaner_id") != cleaner_id:
            continue
        if b.get("status") not in NON_TERMINAL:
            continue
        other_start = b["scheduled_start"] - buf
        other_end = b["scheduled_end"] + buf
        if _overlaps(start, end, other_start, other_end):
            raise err("ERR_CLEANER_DOUBLE_BOOKED",
                      "assigned cleaner has an overlapping booking")


def check_address_double_booked(address_id, start, end, exclude_booking_id=None):
    for b in db.bookings.values():
        if exclude_booking_id is not None and b["id"] == exclude_booking_id:
            continue
        if b.get("address_id") != address_id:
            continue
        if b.get("status") not in NON_TERMINAL:
            continue
        if _overlaps(start, end, b["scheduled_start"], b["scheduled_end"]):
            raise err("ERR_ADDRESS_DOUBLE_BOOKED",
                      "address has an overlapping booking")
