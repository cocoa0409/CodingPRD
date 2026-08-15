"""In-memory data store, logical clock, and timestamp helpers.

Storage is process-local dicts keyed by id. The store starts completely
empty on every boot; the logical clock starts at 2026-08-01T00:00:00Z.
"""

import itertools
import threading
import uuid
from datetime import datetime, timezone

from errors import ApiError


def iso(dt):
    """Format an aware datetime as ISO 8601 UTC with three fractional digits."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(value):
    """Parse an ISO 8601 timestamp to an aware UTC datetime.

    Raises ApiError(ERR_INVALID_REQUEST) on anything malformed.
    """
    if not isinstance(value, str):
        raise ApiError(400, "ERR_INVALID_REQUEST", "expected an ISO 8601 timestamp string")
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except (ValueError, TypeError):
        raise ApiError(400, "ERR_INVALID_REQUEST", f"malformed ISO 8601 timestamp: {value!r}")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


class DB:
    def __init__(self):
        self.lock = threading.RLock()
        self.clock = datetime(2026, 8, 1, tzinfo=timezone.utc)
        self.seq = itertools.count(1)
        self.vessels = {}
        self.permits = {}
        self.holdings = {}
        self.openings = {}
        self.trips = {}
        self.catch_reports = {}
        self.declarations = {}
        self.transfers = {}
        self.observers = {}
        self.assignments = {}
        self.crew_contracts = {}
        self.expenses = {}
        self.settlements = {}
        self.gear_assets = {}
        self.gear_events = {}
        self.vms_pings = {}
        self.violations = {}


db = DB()


def new_id():
    return str(uuid.uuid4())


def now_iso():
    return iso(db.clock)


def next_seq():
    return next(db.seq)
