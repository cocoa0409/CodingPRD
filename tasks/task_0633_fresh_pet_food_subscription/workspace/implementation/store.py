"""In-memory data store and the logical clock.

ALL state lives in module-level dicts that are constructed empty at import time.
There is NO seeding, NO preloading, NO persistence. A fresh process => empty store.
"""
import uuid
from datetime import datetime, timezone


# --- Logical clock (PRD §2.4) ---------------------------------------------
# Default on startup is exactly 2026-01-01T00:00:00Z.
DEFAULT_CLOCK = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self.current = DEFAULT_CLOCK

    def now(self):
        return self.current

    def set(self, dt):
        self.current = dt


clock = Clock()


# --- Entity collections (all empty at boot) -------------------------------
accounts = {}
pets = {}
recipes = {}
subscriptions = {}
weight_logs = {}
orders = {}
shipments = {}
referral_credits = {}

# Monotonic insertion counter to break created_at ties for stable sort
# and to drive default created-order list sorting (PRD §2.3).
_seq = {"n": 0}


def next_seq():
    _seq["n"] += 1
    return _seq["n"]


def new_id():
    return str(uuid.uuid4())


def iso_millis(dt):
    """ISO 8601 UTC with three fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
