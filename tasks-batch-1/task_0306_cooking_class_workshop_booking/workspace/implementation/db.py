"""In-memory data store. Everything is process-local and starts EMPTY on boot.

No seeding, no preloaded entities. Tests construct all state via the API surface.
"""
import threading
import uuid
from datetime import datetime, timezone

# A single global lock makes each request's cascade atomic relative to others.
LOCK = threading.RLock()

# One dict per entity type, keyed by id.
instructors = {}
members = {}
templates = {}
series = {}
sessions = {}
ingredient_lines = {}
bookings = {}
waitlist_entries = {}
substitutions = {}
gift_cards = {}
gift_card_txns = {}
no_show_records = {}

# Monotonic sequence used as a deterministic created_at tiebreaker / sort key.
_seq = 0

# Logical clock. None => fall back to real wall clock.
_clock_override = None


def reset():
    """Clear every store (used only for safety; boot already starts empty)."""
    for d in (
        instructors, members, templates, series, sessions, ingredient_lines,
        bookings, waitlist_entries, substitutions, gift_cards, gift_card_txns,
        no_show_records,
    ):
        d.clear()
    global _seq, _clock_override
    _seq = 0
    _clock_override = None


def new_id():
    return str(uuid.uuid4())


def next_seq():
    global _seq
    _seq += 1
    return _seq


def _now_dt():
    if _clock_override is not None:
        return _clock_override
    return datetime.now(timezone.utc)


def iso_now():
    """Current real wall-clock time as ISO 8601 UTC with three fractional digits.

    Used for created_at/updated_at audit fields (always real time).
    """
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def set_clock(dt):
    global _clock_override
    _clock_override = dt


def current_utc():
    """Logical clock used by refund tier / late-cancel arithmetic."""
    return _now_dt()
