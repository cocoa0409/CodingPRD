"""In-memory data store + server-held logical clock.

The store starts completely empty on every boot. Nothing is seeded, preloaded
or hardcoded; every record is created through the declared API surface.
"""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

TS_FMT = "%Y-%m-%dT%H:%M:%S.%f"

# PRD 2.5 -- the logical clock starts here on every fresh boot.
CLOCK_ORIGIN = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def new_id():
    return str(uuid.uuid4())


def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime(TS_FMT)[:-3] + "Z"


def parse_dt(text):
    """Parse an ISO 8601 instant. Returns None when unparseable."""
    if not isinstance(text, str):
        return None
    raw = text.strip()
    if not raw:
        return None
    candidate = raw
    if candidate.endswith("Z") or candidate.endswith("z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def rh(value, places):
    """Round half up to `places` decimal places."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    quant = Decimal(1).scaleb(-places)
    return value.quantize(quant, rounding=ROUND_HALF_UP)


def dec(value, places=None):
    d = value if isinstance(value, Decimal) else Decimal(str(value))
    if places is None:
        return d
    return rh(d, places)


def clamp(value, low, high):
    if value < low:
        return low
    if value > high:
        return high
    return value


class Store(object):
    """A single flat namespace of dicts keyed by entity id."""

    COLLECTIONS = (
        "varieties",
        "filings",
        "trial_sites",
        "trials",
        "propagators",
        "agreements",
        "quotas",
        "tag_orders",
        "reports",
        "line_items",
        "grants",
        "cases",
        "tests",
        "engagements",
    )

    def __init__(self):
        for name in self.COLLECTIONS:
            setattr(self, name, {})
        self.now = CLOCK_ORIGIN
        self._seq = 0

    # -- clock -------------------------------------------------------
    def now_iso(self):
        return fmt_dt(self.now)

    def next_seq(self):
        self._seq += 1
        return self._seq

    # -- record lifecycle -------------------------------------------
    def stamp_new(self, record, versioned=True):
        record["created_at"] = self.now_iso()
        if versioned:
            record["updated_at"] = self.now_iso()
            record["version"] = 1
        record["_seq"] = self.next_seq()
        return record

    def touch(self, record):
        record["updated_at"] = self.now_iso()
        record["version"] = int(record.get("version", 1)) + 1
        return record

    # -- ordered access ---------------------------------------------
    def ordered(self, collection, *tiebreaks):
        """Records ordered by created_at ascending, then the given keys.

        Insertion order is the implicit final tiebreak (stable sort).
        """
        items = list(getattr(self, collection).values())
        items.sort(key=lambda r: r["_seq"])
        for key in reversed(tiebreaks):
            items.sort(key=key)
        items.sort(key=lambda r: r["created_at"])
        return items


store = Store()


def days_between(later, earlier):
    """Whole days from `earlier` to `later` (floor, non-negative caller's job)."""
    delta = later - earlier
    return delta.total_seconds() / 86400.0


def add_days(dt, days):
    return dt + timedelta(days=days)
