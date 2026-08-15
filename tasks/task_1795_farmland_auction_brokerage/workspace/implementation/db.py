"""In-memory data store. Everything lives in module-level dicts keyed by id.

The store starts empty on every boot. A global logical clock drives all
temporal behavior; a monotonic insertion sequence provides deterministic
creation-order tie-breaking.
"""

from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

_INITIAL_CLOCK = "2026-08-01T00:00:00+00:00"
_clock = datetime.fromisoformat(_INITIAL_CLOCK)


def clock_now() -> datetime:
    return _clock


def set_clock(dt: datetime) -> None:
    global _clock
    _clock = dt


# ---------------------------------------------------------------------------
# Entity stores (all start empty)
# ---------------------------------------------------------------------------

sellers = {}
agents = {}
buyers = {}
listings = {}
tracts = {}
comparables = {}
auctions = {}
bids = {}
deposits = {}
disclosures = {}
rights = {}
closings = {}
statements = {}

# Monotonic creation sequence for deterministic created_at tie-breaking.
_seq = 0


def next_seq() -> int:
    global _seq
    _seq += 1
    return _seq
