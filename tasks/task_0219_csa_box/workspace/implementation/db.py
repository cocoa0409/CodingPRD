"""In-memory data store for the CSA Box API.

ALL state lives in module-level dicts keyed by id. Nothing is seeded or
preloaded — every entity is created by the test suite via the declared API
surface. A fresh process (start.sh re-invocation) starts completely empty.
"""
import uuid
from datetime import datetime, timezone

# ---- Entity tables (id -> record dict) ----
seasons = {}
pickup_sites = {}
share_types = {}
add_ons = {}
members = {}
subscriptions = {}
subscription_add_ons = {}
weekly_boxes = {}
vacation_holds = {}
waitlist_entries = {}
work_share_shifts = {}
ledger_entries = {}

# Monotonic sequence to order records created within the same millisecond.
_seq = 0

# Simulated clock (PRD §3.11). Defaults to real "now" until a test sets it.
_current_utc = None


def reset():
    """Wipe all state. Used only for defensive cleanliness on import."""
    global _seq, _current_utc
    for tbl in (seasons, pickup_sites, share_types, add_ons, members,
                subscriptions, subscription_add_ons, weekly_boxes,
                vacation_holds, waitlist_entries, work_share_shifts,
                ledger_entries):
        tbl.clear()
    _seq = 0
    _current_utc = None


def next_seq():
    global _seq
    _seq += 1
    return _seq


def new_id():
    # Server-minted UUID with no type prefix (PRD §2.4).
    return str(uuid.uuid4())


def now_iso():
    """Current real-wall-clock timestamp (for created_at/updated_at), ISO8601
    UTC with three fractional digits."""
    n = datetime.now(timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"


def get_clock():
    """Return the simulated current UTC time as a datetime.

    Falls back to real now until a PlatformAdmin sets it (PRD §3.11)."""
    if _current_utc is None:
        return datetime.now(timezone.utc)
    return _current_utc


def set_clock(dt):
    global _current_utc
    _current_utc = dt
