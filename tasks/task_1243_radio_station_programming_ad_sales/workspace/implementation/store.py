"""In-memory data store and logical clock.

The store starts completely empty on every boot: no seeding, no preloading,
no hardcoded entities. Every entity is constructed via the declared API.
"""
import itertools
import threading
import uuid
from datetime import datetime, timezone


_lock = threading.RLock()

# ---------------------------------------------------------------------------
# Logical clock: starts at exactly 2026-05-01T00:00:00Z and never falls back
# to wall-clock time. Mutated only via POST /_clock/set_current_utc.
# ---------------------------------------------------------------------------
_clock_state = {
    "current": datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc),
    "raw": "2026-05-01T00:00:00Z",
}

# ---------------------------------------------------------------------------
# Entity tables: dicts keyed by id. Empty at startup by contract.
# ---------------------------------------------------------------------------
stations = {}
clocks = {}
music_categories = {}
songs = {}
ratings_books = {}
rate_card_entries = {}
clearances = {}
trade_agreements = {}
trade_ledger_entries = {}
orders = {}
logs = {}
spots = {}
barter_avails = {}
endorsement_contracts = {}
live_reads = {}
discrepancies = {}
remote_events = {}

# Internal monotonically increasing sequence for stable ordering (never
# serialized; used only to break created_at ties deterministically).
_seq_counter = itertools.count(1)


def next_seq():
    return next(_seq_counter)


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """ISO 8601 UTC timestamp with exactly three fractional digits."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def get_clock():
    with _lock:
        return _clock_state["current"]


def get_clock_raw():
    with _lock:
        return _clock_state["raw"]


def set_clock(dt, raw):
    with _lock:
        _clock_state["current"] = dt
        _clock_state["raw"] = raw


def current_date():
    """The logical clock's current calendar date (UTC)."""
    return get_clock().date()


def reset_all():
    """Not used at runtime; provided for completeness. Store starts empty."""
    for tbl in (stations, clocks, music_categories, songs, ratings_books,
                rate_card_entries, clearances, trade_agreements,
                trade_ledger_entries, orders, logs, spots, barter_avails,
                endorsement_contracts, live_reads, discrepancies,
                remote_events):
        tbl.clear()


class Lock:
    """Expose the re-entrant store lock for request-scoped atomicity."""

    def __enter__(self):
        _lock.acquire()
        return self

    def __exit__(self, *exc):
        _lock.release()
        return False
