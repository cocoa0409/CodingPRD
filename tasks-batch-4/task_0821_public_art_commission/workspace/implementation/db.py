"""In-memory data store and logical clock.

All state is process-local and starts empty on every boot. No seeding.
"""
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Entity tables (keyed by id -> record dict)
# ---------------------------------------------------------------------------
projects = {}
commissions = {}
calls = {}
artists = {}
submissions = {}
panelists = {}
scores = {}
contracts = {}
milestones = {}
sites = {}
artworks = {}
conservation_records = {}
loans = {}

# ---------------------------------------------------------------------------
# Logical clock -- default instant, never wall clock.
# ---------------------------------------------------------------------------
DEFAULT_CLOCK = datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)
_clock = {"now": DEFAULT_CLOCK}

# Monotonic insertion sequence (creation order / tiebreaker for created_at ASC)
_seq = {"n": 0}


def now_dt():
    return _clock["now"]


def set_clock(dt):
    _clock["now"] = dt


def next_seq():
    _seq["n"] += 1
    return _seq["n"]
