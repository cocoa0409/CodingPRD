"""In-memory data store, logical clock and audit-stamp helpers.

Storage is process-local Python dicts keyed by id.  The store is EMPTY on every
boot: nothing is seeded, preloaded or hardcoded.  All state is created by
clients through the declared endpoints.
"""

import itertools
import re
import uuid
from datetime import datetime, timedelta, timezone

from flask import g

# PRD §2.4 — the logical clock starts here at process start and never advances
# on its own; only POST /_clock/set_current_utc moves it.
CLOCK_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        self.jurisdictions = {}
        self.licensees = {}
        self.control_persons = {}
        self.applications = {}
        self.state_licenses = {}
        self.delegates = {}
        self.authorizations = {}
        self.holdings = {}
        self.tests = {}
        self.exams = {}
        self.info_requests = {}
        self.call_reports = {}
        self.enforcements = {}
        self.license_seq = {}          # jurisdiction_id -> last minted sequence
        self.clock = CLOCK_START
        self._counter = itertools.count(1)

    def next_seq(self):
        return next(self._counter)


db = Store()


# --------------------------------------------------------------------------
# time helpers
# --------------------------------------------------------------------------

def now():
    """Current logical-clock instant."""
    return db.clock


def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD §2.4)."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})"
    r"(?:[Tt ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,6}))?)?"
    r"(Z|z|[+-]\d{2}:?\d{2})?)?$"
)


def parse_iso(value):
    """Parse an ISO 8601 instant.  Returns an aware UTC datetime or None."""
    if not isinstance(value, str):
        return None
    m = _ISO_RE.match(value.strip())
    if not m:
        return None
    year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
    hour = int(m.group(4) or 0)
    minute = int(m.group(5) or 0)
    second = int(m.group(6) or 0)
    frac = m.group(7) or ""
    micro = int((frac + "000000")[:6]) if frac else 0
    tzs = m.group(8)
    try:
        if tzs in (None, "Z", "z"):
            tzinfo = timezone.utc
        else:
            sign = 1 if tzs[0] == "+" else -1
            body = tzs[1:].replace(":", "")
            tzinfo = timezone(sign * timedelta(hours=int(body[:2]), minutes=int(body[2:4])))
        dt = datetime(year, month, day, hour, minute, second, micro, tzinfo=tzinfo)
    except ValueError:
        return None
    return dt.astimezone(timezone.utc)


def days(n):
    """Exact multiples of twenty-four hours (PRD §2.4)."""
    return timedelta(days=n)


# --------------------------------------------------------------------------
# record helpers
# --------------------------------------------------------------------------

def new_id():
    return str(uuid.uuid4())


def base_row(with_common_fields=True):
    stamp = fmt_ts(now())
    row = {"id": new_id(), "created_at": stamp}
    if with_common_fields:
        row["updated_at"] = stamp
        row["version"] = 1
    row["_seq"] = db.next_seq()
    return row


def touch(row):
    """Refresh updated_at and increment version — at most once per request."""
    if row is None or "version" not in row:
        return
    touched = getattr(g, "_touched_rows", None)
    if touched is None:
        touched = set()
        g._touched_rows = touched
    key = id(row)
    if key in touched:
        return
    touched.add(key)
    row["updated_at"] = fmt_ts(now())
    row["version"] = row["version"] + 1


def set_dt(row, name, dt):
    """Store a server-computed datetime (normalised) plus its parsed form."""
    row[name] = fmt_ts(dt) if dt is not None else None
    row["_" + name] = dt


def set_input_dt(row, name, raw, dt):
    """Store a client-supplied datetime verbatim plus its parsed form."""
    row[name] = raw
    row["_" + name] = dt


def get_dt(row, name):
    return row.get("_" + name)


def serialize(row):
    return {k: v for k, v in row.items() if not k.startswith("_")}


def sorted_rows(rows):
    """Default ordering for every list endpoint: created_at ascending."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
