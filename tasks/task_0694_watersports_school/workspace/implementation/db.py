"""In-memory data store.

ALL state lives in module-level dicts keyed by entity id. Nothing is persisted
to disk; every start.sh re-invocation imports this module fresh, so the store
starts empty on every boot. NO entity data is seeded here or anywhere at startup.
"""
import itertools
import threading
import uuid
from datetime import datetime, timezone

_lock = threading.RLock()

# One dict per entity collection, keyed by id.
schools = {}
courses = {}
levels = {}
instructors = {}
equipment = {}
students = {}
waivers = {}
memberships = {}
enrollments = {}
sessions = {}
bookings = {}
rentals = {}
certification_cards = {}

# Monotonic certification card serial per school.
_card_serials = {}  # school_id -> int

# Monotonic counter to preserve insertion order for stable created_at tie-breaks.
_seq_counter = itertools.count(1)


def lock():
    return _lock


def new_id() -> str:
    return str(uuid.uuid4())


def next_seq() -> int:
    return next(_seq_counter)


def now_iso() -> str:
    """Wall-clock ISO 8601 UTC with three fractional digits for created_at/updated_at.

    These are real-time stamps for record bookkeeping (PRD §2.5), distinct from
    the logical clock used for business rules (PRD §2.4)."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def next_card_serial(school_id: str) -> int:
    n = _card_serials.get(school_id, 0) + 1
    _card_serials[school_id] = n
    return n
