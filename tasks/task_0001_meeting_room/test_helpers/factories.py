"""Payload factories from scaffold Table 1 input fields."""
import uuid
from datetime import datetime, timedelta, timezone


def _future_time(hours_ahead: int = 24, minutes_ahead: int = 0) -> str:
    """Return an ISO 8601 UTC timestamp in the future."""
    dt = datetime.now(timezone.utc) + timedelta(hours=hours_ahead, minutes=minutes_ahead)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _future_date(days_ahead: int = 7) -> str:
    """Return a YYYY-MM-DD date string in the future."""
    dt = datetime.now(timezone.utc) + timedelta(days=days_ahead)
    return dt.strftime("%Y-%m-%d")


def _unique_name(prefix: str = "Room") -> str:
    """Generate a unique name to avoid ERR_ROOM_NAME_TAKEN."""
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# Room factory
# ---------------------------------------------------------------------------

def create_room_payload(**overrides) -> dict:
    """Create a valid room payload. All input fields with sensible defaults."""
    defaults = {
        "name": _unique_name("Room"),
        "capacity": 10,
        "floor": 1,
        "amenities": ["PROJECTOR", "WHITEBOARD"],
        "tier": "STANDARD",
        "hourly_rate_cents": 6000,
        "peak_multiplier": 1.5,
        "peak_hours_start": "09:00",
        "peak_hours_end": "17:00",
    }
    defaults.update(overrides)
    return defaults


def create_premium_room_payload(**overrides) -> dict:
    """Create a valid PREMIUM room payload."""
    payload = create_room_payload(tier="PREMIUM", **overrides)
    return payload


# ---------------------------------------------------------------------------
# Booking factory
# ---------------------------------------------------------------------------

def create_booking_payload(room_id: str, **overrides) -> dict:
    """Create a valid booking payload for the given room."""
    start = overrides.pop("start_time", None) or _future_time(hours_ahead=24)
    end = overrides.pop("end_time", None) or _future_time(hours_ahead=25)
    defaults = {
        "room_id": room_id,
        "title": "Test Meeting",
        "start_time": start,
        "end_time": end,
        "attendee_count": 5,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Series factory
# ---------------------------------------------------------------------------

def create_series_payload(room_id: str, **overrides) -> dict:
    """Create a valid series payload for the given room."""
    defaults = {
        "room_id": room_id,
        "title": "Recurring Standup",
        "recurrence_rule": "WEEKLY",
        "start_time": "10:00",
        "duration_minutes": 60,
        "attendee_count": 5,
        "series_start_date": _future_date(days_ahead=7),
        "series_end_date": _future_date(days_ahead=35),
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Waitlist factory
# ---------------------------------------------------------------------------

def create_waitlist_payload(room_id: str, **overrides) -> dict:
    """Create a valid waitlist payload for the given room."""
    start = overrides.pop("start_time", None) or _future_time(hours_ahead=48)
    end = overrides.pop("end_time", None) or _future_time(hours_ahead=49)
    defaults = {
        "room_id": room_id,
        "title": "Waitlist Meeting",
        "start_time": start,
        "end_time": end,
        "attendee_count": 5,
    }
    defaults.update(overrides)
    return defaults
