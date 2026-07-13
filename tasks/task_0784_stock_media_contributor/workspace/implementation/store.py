"""In-memory data store, logical clock, id/timestamp helpers.

All state lives in module-level dicts keyed by id. Nothing is persisted to disk
and nothing is seeded at import time, so every fresh process starts empty.
"""

import itertools
import threading
import uuid
from datetime import datetime, timezone

# Server-startup default for the logical clock (PRD 2.5).
DEFAULT_CLOCK = datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.contributors = {}
        self.tax_forms = {}
        self.model_releases = {}
        self.assets = {}
        self.reviews = {}
        self.license_tiers = {}
        self.downloads = {}
        self.payouts = {}
        self.exclusivity_windows = {}
        self.earning_adjustments = {}
        self.takedowns = {}
        self.clock = DEFAULT_CLOCK
        self._seq = itertools.count(1)

    def now(self):
        return self.clock

    def next_seq(self):
        return next(self._seq)


db = Store()


def new_id():
    return str(uuid.uuid4())


def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits and a trailing Z."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_ts(value):
    """Parse an ISO 8601 timestamp into an aware UTC datetime. Raises ValueError."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("invalid timestamp")
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
