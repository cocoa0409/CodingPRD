"""In-memory data store.

Every byte of state lives in module-level dicts that are re-created fresh on
each process start. There is NO seeding, NO file persistence, NO preload — the
store is empty on boot and all entities are constructed by API calls.
"""
import uuid
from datetime import datetime, timezone


# The logical server clock. Starts, at server startup, at exactly
# 2026-01-01T00:00:00Z. Before any set_current_utc call the clock reads
# precisely this default and never falls back to wall-clock time.
DEFAULT_CLOCK = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    """A single namespace of entity dicts keyed by id."""

    def __init__(self):
        self.importers = {}
        self.bonds = {}
        self.isf_filings = {}
        self.entries = {}
        self.entry_lines = {}
        self.pga_reviews = {}
        self.exam_slots = {}
        self.monthly_statements = {}
        self.post_summary_corrections = {}
        self._clock = DEFAULT_CLOCK

    # ---- logical clock ----
    def now(self):
        return self._clock

    def set_clock(self, dt):
        self._clock = dt


# The single global store instance. Re-created (empty) on every process start.
db = Store()


def new_id():
    """Server-minted UUID with no type prefix."""
    return str(uuid.uuid4())


def iso_now(dt=None):
    """ISO 8601 UTC timestamp with exactly three fractional digits."""
    if dt is None:
        dt = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
