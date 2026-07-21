"""In-memory data store and logical clock for the Property-Tax Appeal API.

Storage is process-local Python dicts keyed by id. Nothing is persisted to
disk and nothing is seeded at import/startup — every entity is created through
the declared API surface, so each fresh boot starts empty.
"""

import datetime
import itertools
import uuid

UTC = datetime.timezone.utc
DEFAULT_CLOCK = datetime.datetime(2026, 7, 1, 0, 0, 0, tzinfo=UTC)


class DB:
    def __init__(self):
        self.analysts = {}
        self.clients = {}
        self.jurisdictions = {}
        self.fee_agreements = {}
        self.parcels = {}
        self.assessments = {}
        self.exemption_claims = {}
        self.appeals = {}
        self.evidence = {}
        self.hearings = {}
        self.settlement_offers = {}
        self.invoices = {}
        self.payments = {}
        self.clock = DEFAULT_CLOCK
        self._seq = itertools.count(1)


db = DB()


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(db._seq)


def now():
    return db.clock


def fmt(dt):
    """Format a datetime as ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_dt(value):
    """Parse an ISO 8601 datetime string. Raises ValueError on failure."""
    if isinstance(value, datetime.datetime):
        dt = value
    elif isinstance(value, str):
        s = value.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.datetime.fromisoformat(s)
    else:
        raise ValueError("not a datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)
