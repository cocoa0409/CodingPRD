"""In-memory data store, logical clock and audit-stamp helpers.

The store starts completely empty on every process boot: nothing is seeded,
preloaded or hardcoded.  Every entity is created through the declared API.
"""

import re
import uuid
from datetime import datetime, timedelta, timezone

from errors import ApiError, invalid

# The mandatory startup default for the logical clock (PRD 2.6).
CLOCK_DEFAULT = "2026-08-01T00:00:00.000Z"

# Collection names -> dict of id -> record
COLLECTIONS = (
    "locations",
    "job_roles",
    "employees",
    "role_assignments",
    "policies",
    "pay_periods",
    "shifts",
    "service_charges",
    "pools",
    "allocations",
    "pay_lines",
    "disputes",
    "corrections",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self._seq = 0
        self.clock = CLOCK_DEFAULT

    def next_seq(self):
        self._seq += 1
        return self._seq

    def new_id(self):
        return str(uuid.uuid4())

    def now(self):
        """Current logical instant as a canonical ISO-8601 string."""
        return self.clock

    def set_clock(self, iso_string):
        self.clock = iso_string

    def values(self, name):
        return list(getattr(self, name).values())


db = Store()


# ---------------------------------------------------------------------------
# timestamp helpers
# ---------------------------------------------------------------------------

_INSTANT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,9}))?)?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


def parse_instant(value, field="value"):
    """Parse an ISO-8601 instant.  Naive strings are read as UTC."""
    if not isinstance(value, str):
        raise invalid("Field '%s' must be an ISO 8601 UTC timestamp string." % field)
    m = _INSTANT_RE.match(value.strip())
    if not m:
        raise invalid("Field '%s' must be an ISO 8601 UTC timestamp." % field)
    year, month, day, hour, minute = (int(m.group(i)) for i in range(1, 6))
    second = int(m.group(6) or 0)
    frac = m.group(7) or ""
    micro = int((frac + "000000")[:6]) if frac else 0
    tz = m.group(8)
    try:
        dt = datetime(year, month, day, hour, minute, second, micro, tzinfo=timezone.utc)
    except ValueError:
        raise invalid("Field '%s' is not a valid calendar instant." % field)
    if tz and tz not in ("Z", "z"):
        sign = 1 if tz[0] == "+" else -1
        body = tz[1:].replace(":", "")
        offset = timedelta(hours=int(body[:2]), minutes=int(body[2:4]))
        dt = dt - sign * offset
    return dt


def fmt_instant(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + (
        "%03d" % (dt.microsecond // 1000)
    ) + "Z"


_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def parse_date(value, field="value"):
    """Parse a calendar-day field.  Returned as a midnight-UTC datetime.

    Both a bare ``YYYY-MM-DD`` and a full UTC instant are accepted; the day is
    what is kept either way.
    """
    if isinstance(value, str):
        m = _DATE_RE.match(value.strip())
        if m:
            try:
                return datetime(
                    int(m.group(1)),
                    int(m.group(2)),
                    int(m.group(3)),
                    tzinfo=timezone.utc,
                )
            except ValueError:
                raise invalid("Field '%s' is not a valid calendar date." % field)
    dt = parse_instant(value, field)
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def fmt_date(dt):
    return dt.strftime("%Y-%m-%dT00:00:00.000Z")


def day_of(iso_string):
    """Midnight-UTC datetime of the calendar day an instant falls on."""
    dt = parse_instant(iso_string)
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def instant(iso_string):
    return parse_instant(iso_string)


# ---------------------------------------------------------------------------
# audit stamps
# ---------------------------------------------------------------------------

_touched = set()


def begin_request():
    _touched.clear()


def stamp_new(record, with_version=True):
    record["id"] = db.new_id()
    record["_seq"] = db.next_seq()
    record["created_at"] = db.now()
    if with_version:
        record["updated_at"] = db.now()
        record["version"] = 1
    _touched.add(id(record))
    return record


def touch(record):
    """Mark a mutation: refresh updated_at and bump version once per request."""
    if "updated_at" in record:
        record["updated_at"] = db.now()
    if id(record) in _touched:
        return record
    _touched.add(id(record))
    if "version" in record:
        record["version"] = record.get("version", 1) + 1
    return record


def touch_time_only(record):
    """Refresh updated_at without advancing the concurrency counter.

    Used for Location, whose `version` is written by policy activation alone
    (PRD 2.7).
    """
    record["updated_at"] = db.now()
    return record


def force_version_bump(record):
    record["updated_at"] = db.now()
    record["version"] = record.get("version", 1) + 1
    _touched.add(id(record))
    return record


def sort_key(record):
    return (record["created_at"], record["_seq"])


def public(record, fields):
    return {name: record.get(name) for name in fields}


def not_found(collection, error_id, key):
    record = getattr(db, collection).get(key)
    if record is None:
        raise ApiError(error_id)
    return record
