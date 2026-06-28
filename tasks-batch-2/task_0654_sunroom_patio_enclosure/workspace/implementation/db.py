"""In-memory data store + logical clock.

Storage is in-memory only (Python dicts keyed by id). Nothing is seeded at
startup; tests build all state via the API. start.sh re-invocation launches a
fresh process which wipes all state.
"""
import uuid
from datetime import datetime, timezone, timedelta

# Logical clock default per PRD §2.9 / endpoint /_clock/set_current_utc.
CLOCK_DEFAULT = datetime(2026, 4, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        # one dict per entity type, keyed by id
        self.homeowners = {}
        self.projects = {}
        self.measurements = {}
        self.quotes = {}
        self.financing_applications = {}
        self.permit_applications = {}
        self.engineering_reviews = {}
        self.manufacture_orders = {}
        self.install_crews = {}
        self.install_jobs = {}
        self.inspections = {}
        self.warranties = {}
        # monotonic sequence to order entities by creation deterministically
        self._seq = 0
        # logical clock
        self._clock = CLOCK_DEFAULT

    # ---- clock ----
    def now(self):
        return self._clock

    def set_clock(self, dt):
        self._clock = dt

    # ---- id / seq ----
    def new_id(self):
        return str(uuid.uuid4())

    def next_seq(self):
        self._seq += 1
        return self._seq


def iso(dt):
    """ISO 8601 UTC timestamp with exactly three fractional digits (PRD §2.4)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(s):
    """Parse an ISO 8601 timestamp (accepts trailing Z)."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


db = Store()


def reset():
    """Used only by the process at import time; tests never call this."""
    global db
    db = Store()
