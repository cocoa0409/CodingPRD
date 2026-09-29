"""In-memory store, logical compliance clock (PRD 2.8) and timestamp helpers.

The store is a plain set of python dicts and starts EMPTY on every boot.
Nothing is ever seeded, preloaded or persisted to disk.
"""

import itertools
import uuid
from datetime import datetime, timedelta, timezone

# PRD 2.8 -- mandatory startup default for the logical clock.
LOGICAL_CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "policy_profiles",
    "passengers",
    "bookings",
    "flight_segments",
    "ancillary_purchases",
    "checked_bags",
    "denied_boarding_records",
    "tarmac_delay_events",
    "refund_obligations",
    "consumer_complaints",
    "complaint_activities",
    "regulator_reports",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self._seq = itertools.count(1)
        self.clock = LOGICAL_CLOCK_DEFAULT

    def next_seq(self):
        return next(self._seq)

    def now(self):
        """The logical compliance clock instant."""
        return self.clock


S = Store()


# --------------------------------------------------------------------------
# datetime helpers
# --------------------------------------------------------------------------

def parse_iso(value):
    """Parse an ISO-8601 UTC instant. Raises ValueError when malformed."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    text = value.strip()
    if not text:
        raise ValueError("empty")
    if text[-1] in ("Z", "z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def fmt_sys(value):
    """created_at / updated_at / api_request_timestamp -- always 3 fractional digits."""
    if value is None:
        return None
    return "%s.%03dZ" % (value.strftime("%Y-%m-%dT%H:%M:%S"), value.microsecond // 1000)


def fmt_domain(value):
    """Domain instants: milliseconds only when the instant actually carries them."""
    if value is None:
        return None
    if value.microsecond:
        return "%s.%03dZ" % (value.strftime("%Y-%m-%dT%H:%M:%S"), value.microsecond // 1000)
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def wall_now():
    """Real wall clock, used only for created_at / updated_at bookkeeping."""
    return datetime.now(timezone.utc)


def add_days(instant, days):
    """PRD 2.7 -- exact 24-hour addition, never calendar logic."""
    if instant is None:
        return None
    return instant + timedelta(days=days)


# --------------------------------------------------------------------------
# row helpers
# --------------------------------------------------------------------------

SYS_DT_FIELDS = ("created_at", "updated_at")


def new_row(fields, versioned=True):
    stamp = wall_now()
    row = {"id": str(uuid.uuid4()), "created_at": stamp}
    if versioned:
        row["updated_at"] = stamp
        row["version"] = 1
    row.update(fields)
    row["_seq"] = S.next_seq()
    return row


def touch(row):
    """Advance a row's version and refresh its updated_at (PRD 2.4)."""
    row["version"] = row.get("version", 0) + 1
    row["updated_at"] = wall_now()
    return row


def serialize(row):
    out = {}
    for key, value in row.items():
        if key.startswith("_"):
            continue
        if isinstance(value, datetime):
            out[key] = fmt_sys(value) if key in SYS_DT_FIELDS else fmt_domain(value)
        else:
            out[key] = value
    return out


def by_seq(rows):
    """created_at ascending; _seq is the monotonic tie-break within a request."""
    return sorted(rows, key=lambda r: r["_seq"])
