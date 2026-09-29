"""In-memory data store, logical clock and shared record helpers.

The store starts completely empty on every boot.  Nothing is seeded,
preloaded or hardcoded: every entity is created through the API.
"""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

# Logical clock default (PRD 2.5)
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

ENTITY_COLLECTIONS = (
    "carriers",
    "npas",
    "rate_centers",
    "blocks",
    "allocation_requests",
    "filings",
    "findings",
    "orders",
    "relief_plans",
    "comments",
    "port_requests",
    "routing_records",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in ENTITY_COLLECTIONS:
            setattr(self, name, {})
        self.clock = DEFAULT_CLOCK
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def now():
    """Current logical clock instant."""
    return db.clock


def new_id():
    return str(uuid.uuid4())


def fmt_dt(value):
    """ISO 8601 UTC with exactly three fractional-second digits (PRD 2.4)."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
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


def fmt_instant(value):
    """ISO 8601 UTC rendering for domain instants (PRD 2.5).

    Section 2.4 pins the three-fractional-digit rendering to ``created_at`` and
    ``updated_at`` only.  Every other instant in the PRD -- the logical clock
    itself ("the logical clock reads exactly 2026-08-01T00:00:00Z"), the
    deadlines derived from it ("becomes due on 2027-01-28T00:00:00Z") and the
    instants a client supplies and the server echoes back -- is written at
    second precision, so that is how they are published.  A sub-second instant
    still renders its milliseconds rather than silently truncating.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    value = value.astimezone(timezone.utc)
    if value.microsecond:
        return fmt_dt(value)
    return "%04d-%02d-%02dT%02d:%02d:%02dZ" % (
        value.year,
        value.month,
        value.day,
        value.hour,
        value.minute,
        value.second,
    )


def parse_dt(raw):
    """Parse an ISO 8601 instant.  Returns None when unparseable."""
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text:
        return None
    if text.endswith("z") or text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except (ValueError, TypeError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def days(count):
    return timedelta(days=count)


def r2(value):
    """Round a Decimal to two places, half-up, and hand back a JSON number."""
    if value is None:
        return None
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def base_record(**fields):
    """A record carrying the full common-field set (PRD 2.4)."""
    record = {
        "id": new_id(),
        "created_at": now(),
        "updated_at": now(),
        "version": 1,
        "_seq": db.next_seq(),
    }
    record.update(fields)
    return record


def light_record(**fields):
    """A record carrying only id + created_at (PublicComment, RoutingRecord)."""
    record = {
        "id": new_id(),
        "created_at": now(),
        "_seq": db.next_seq(),
    }
    record.update(fields)
    return record


def touch(record):
    """Bump version + updated_at, at most once per HTTP request (PRD 2.9)."""
    if record is None:
        return
    try:
        from flask import g

        seen = getattr(g, "touched", None)
        if seen is None:
            seen = set()
            g.touched = seen
        if record["id"] in seen:
            return
        seen.add(record["id"])
    except RuntimeError:
        pass
    record["version"] = record.get("version", 1) + 1
    record["updated_at"] = now()


def by_created(records):
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))


def by_created_desc(records):
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]), reverse=True)
