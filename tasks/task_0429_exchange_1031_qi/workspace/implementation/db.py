"""In-memory data store and the server logical clock.

All state lives in module-level dicts keyed by id. The store starts EMPTY on every
boot — nothing is seeded, preloaded, or hardcoded. Every entity is created by the
tests via the declared API surface. A fresh process therefore wipes all state.
"""
from datetime import datetime, timezone

# --- Entity stores (id -> dict) ---
exchangers = {}
exchanges = {}
relinquished_properties = {}
qualified_trusts = {}
identifications = {}
identified_properties = {}
replacement_properties = {}
disbursements = {}

# Monotonic counter to deterministically order resources created within the same
# logical-clock instant. created_at ties are broken by this sequence on list sorts.
_seq = 0

# --- Logical clock (PRD §2.7) ---
# At startup the clock reads exactly 2026-01-01T00:00:00Z and until an explicit set
# call is made it stays at this default and never falls back to real wall-clock time.
_DEFAULT_CLOCK = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
_clock = _DEFAULT_CLOCK


def now_logical():
    """Return the current logical clock instant (timezone-aware UTC)."""
    return _clock


def set_clock(dt):
    """Set the logical clock to an absolute UTC instant."""
    global _clock
    _clock = dt


def next_seq():
    global _seq
    _seq += 1
    return _seq
