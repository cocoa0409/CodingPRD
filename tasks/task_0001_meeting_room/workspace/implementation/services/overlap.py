import db
from datetime import datetime, timezone


def parse_dt(s):
    """Parse ISO 8601 datetime string to datetime object."""
    if isinstance(s, datetime):
        return s
    s = s.replace("Z", "+00:00")
    return datetime.fromisoformat(s)


def has_overlap(room_id, start_time, end_time, exclude_booking_id=None):
    """Check if a time range overlaps with any CONFIRMED or CHECKED_IN booking on the room.

    Uses half-open interval: [start, end)
    Returns True if there IS a conflict.
    """
    st = parse_dt(start_time)
    et = parse_dt(end_time)

    for b in db.bookings.values():
        if b["room_id"] != room_id:
            continue
        if b["status"] not in ("CONFIRMED", "CHECKED_IN"):
            continue
        if exclude_booking_id and b["id"] == exclude_booking_id:
            continue
        b_st = parse_dt(b["start_time"])
        b_et = parse_dt(b["end_time"])
        if st < b_et and b_st < et:
            return True
    return False
