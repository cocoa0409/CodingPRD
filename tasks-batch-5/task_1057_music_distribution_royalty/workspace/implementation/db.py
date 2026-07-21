"""In-memory data store, logical clock and common-field helpers.

The store starts empty on every boot. Nothing is seeded.
"""

import itertools
import threading
import uuid
from datetime import datetime, timedelta, timezone

# PRD §2.5 — the logical clock's startup value.
SERVER_DEFAULT_CLOCK_UTC = "2026-07-01T00:00:00Z"

_lock = threading.RLock()
_seq = itertools.count(1)


def next_seq():
    return next(_seq)


class Database:
    """Every collection is a dict id -> row dict, insertion ordered."""

    def __init__(self):
        self.subscription_plans = {}
        self.stores = {}
        self.artists = {}
        self.subscriptions = {}
        self.releases = {}
        self.tracks = {}
        self.collaborators = {}
        self.split_sheets = {}
        self.split_shares = {}
        self.deliveries = {}
        self.royalty_statements = {}
        self.royalty_lines = {}
        self.payouts = {}
        self.tax_forms = {}
        self.clock = parse_iso(SERVER_DEFAULT_CLOCK_UTC)


def parse_iso(value):
    """Parse an ISO 8601 instant into an aware UTC datetime, or raise ValueError."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_iso(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


db = Database()


def now():
    """Current value of the logical clock (aware UTC datetime)."""
    return db.clock


def set_clock(dt):
    db.clock = dt


def new_id():
    return str(uuid.uuid4())


def common_fields(with_version=True):
    """id / created_at / updated_at / version — PRD §2.4."""
    stamp = now()
    row = {
        "id": new_id(),
        "created_at": stamp,
    }
    if with_version:
        row["updated_at"] = stamp
        row["version"] = 1
    row["_seq"] = next_seq()
    return row


def touch(row):
    """Refresh updated_at and advance version by exactly 1."""
    row["updated_at"] = now()
    row["version"] = row.get("version", 1) + 1
    return row


def days(n):
    return timedelta(days=n)


def minutes(n):
    return timedelta(minutes=n)
