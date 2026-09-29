"""Foundation layer: logical clock, in-memory store, id/timestamp helpers."""

import random
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from flask import g

# ---------------------------------------------------------------------------
# Logical UTC clock (PRD 2.5).  Server controlled; never wall-clock.
# ---------------------------------------------------------------------------

DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class LogicalClock(object):
    def __init__(self):
        self.current = DEFAULT_CLOCK

    def now(self):
        return self.current

    def set(self, instant):
        self.current = instant


clock = LogicalClock()


def fmt_instant(value):
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.4)."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    value = value.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        value.year,
        value.month,
        value.day,
        value.hour,
        value.minute,
        value.second,
        value.microsecond // 1000,
    )


def parse_instant(raw):
    """Parse an ISO 8601 UTC instant.  Raises ValueError when unusable."""
    if not isinstance(raw, str):
        raise ValueError("not a string")
    text = raw.strip()
    if not text:
        raise ValueError("empty")
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    # Trim over-long fractional parts so 3.9/3.10 fromisoformat copes.
    if "." in text:
        head, _, tail = text.partition(".")
        digits = ""
        rest = ""
        for idx, ch in enumerate(tail):
            if ch.isdigit():
                digits += ch
            else:
                rest = tail[idx:]
                break
        if len(digits) > 6:
            digits = digits[:6]
        while len(digits) < 6 and digits:
            digits += "0"
        text = head + ("." + digits if digits else "") + rest
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise ValueError("unparseable instant")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def add_days(instant, days):
    return instant + timedelta(days=days)


def add_calendar_years(instant, years):
    """Increment only the year field, leaving month/day/time verbatim."""
    return instant.replace(year=instant.year + int(years))


# ---------------------------------------------------------------------------
# Identifiers
# ---------------------------------------------------------------------------

_ALNUM = string.ascii_uppercase + string.digits


def new_id():
    return str(uuid.uuid4())


def new_request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


# ---------------------------------------------------------------------------
# In-memory store.  Starts empty on every boot; nothing is ever seeded.
# ---------------------------------------------------------------------------

COLLECTIONS = (
    "retention_schedules",
    "record_series",
    "legal_holds",
    "appraisals",
    "accessions",
    "archival_items",
    "storage_zones",
    "finding_aids",
    "preservation_plans",
    "migration_jobs",
    "requesters",
    "access_requests",
    "screenings",
    "interviews",
    "evidence_packages",
    "exhibit_loans",
    "deaccession_proposals",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


store = Store()


def register(collection, fields, versioned=True):
    """Create a row with the system fields from PRD 2.4 and store it."""
    now = clock.now()
    row = {"id": new_id(), "created_at": now}
    row.update(fields)
    if versioned:
        row["updated_at"] = now
        row["version"] = 1
    row["_seq"] = store.next_seq()
    collection[row["id"]] = row
    return row


def touch(row):
    """Record a mutation: bump version, refresh updated_at (PRD 2.4).

    Idempotent inside a single request: a row mutated several times while
    servicing one HTTP call advances exactly one version (PRD 2.8).
    """
    if row is None or "version" not in row:
        return row
    seen = getattr(g, "_touched", None)
    if seen is None:
        seen = set()
        g._touched = seen
    key = id(row)
    if key in seen:
        return row
    seen.add(key)
    row["version"] += 1
    row["updated_at"] = clock.now()
    return row


def sorted_rows(collection):
    """Default ordering: created_at ascending (insertion order breaks ties)."""
    return sorted(collection.values(), key=lambda r: (r["created_at"], r["_seq"]))


def serialize(row):
    out = {}
    for key, value in row.items():
        if key.startswith("_"):
            continue
        if isinstance(value, datetime):
            out[key] = fmt_instant(value)
        elif isinstance(value, Decimal):
            out[key] = float(value)
        else:
            out[key] = value
    return out
