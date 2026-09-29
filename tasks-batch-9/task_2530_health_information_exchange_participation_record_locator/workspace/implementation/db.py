"""In-memory data store, logical clock, id and timestamp minting.

The store starts completely empty on every boot; no entity is ever seeded,
preloaded or hardcoded here.  Every row is produced by an API caller through
one of the declared endpoints.
"""
import json
import re
import uuid
from datetime import datetime, timedelta, timezone

# PRD 2.5: the logical clock reads exactly this value before it is ever set.
CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,9}))?)?"
    r"(Z|z|\+00:00|\+0000)$"
)
_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")

# Table names (one dict per entity family).
TABLES = (
    "participants",
    "conformance_tests",
    "consent_policies",
    "threshold_configs",
    "patient_records",
    "clusters",
    "match_links",
    "directives",
    "queries",
    "audit_entries",
    "break_glass",
    "subscriptions",
    "data_feeds",
    "samples",
    "invoices",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.clock = CLOCK_EPOCH
        self._seq = 0
        for name in TABLES:
            setattr(self, name, {})

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


# ---------------------------------------------------------------- identifiers
def new_id():
    """UUID string with no prefix (PRD 2.4)."""
    return str(uuid.uuid4())


def new_request_id():
    import random
    import string

    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(16))


# ----------------------------------------------------------------- timestamps
def fmt_dt(value):
    """ISO 8601 UTC with exactly three fractional digits and a Z suffix."""
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


def clock():
    return db.clock


def now_iso():
    return fmt_dt(db.clock)


def real_now_iso():
    """Wall clock, used only for the envelope's api_request_timestamp."""
    return fmt_dt(datetime.now(timezone.utc))


def parse_iso(text):
    """Strict ISO 8601 UTC parser.  Returns None when the text is not valid."""
    if not isinstance(text, str):
        return None
    m = _ISO_RE.match(text.strip())
    if not m:
        return None
    year, month, day, hour, minute = (int(m.group(i)) for i in range(1, 6))
    second = int(m.group(6) or 0)
    frac = m.group(7) or ""
    micro = int((frac + "000000")[:6]) if frac else 0
    try:
        return datetime(
            year, month, day, hour, minute, second, micro, tzinfo=timezone.utc
        )
    except ValueError:
        return None


def parse_date(text):
    if not isinstance(text, str):
        return None
    m = _DATE_RE.match(text.strip())
    if not m:
        return None
    try:
        return datetime(
            int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=timezone.utc
        )
    except ValueError:
        return None


def plus_minutes(value, minutes):
    return value + timedelta(minutes=minutes)


def plus_days(value, days):
    return value + timedelta(days=days)


# --------------------------------------------------------------- entity plumb
INTERNAL_KEYS = ("_seq", "_kind")
META_KEYS = ("id", "created_at", "updated_at", "version")


def create(table, kind, fields, versioned=True):
    row = {
        "id": new_id(),
        "created_at": now_iso(),
    }
    if versioned:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    row.update(fields)
    row["_seq"] = db.next_seq()
    row["_kind"] = kind
    table[row["id"]] = row
    return row


def touch(row):
    """Advance updated_at and bump version by exactly one."""
    row["updated_at"] = now_iso()
    row["version"] = int(row.get("version") or 1) + 1
    return row


def snapshot(row):
    payload = {
        k: v
        for k, v in row.items()
        if k not in INTERNAL_KEYS and k not in META_KEYS
    }
    return json.dumps(payload, sort_keys=True, default=str)


def commit(row, before):
    """Bump version/updated_at only when the row's data actually changed."""
    if snapshot(row) != before:
        touch(row)
        return True
    return False


def by_created(rows):
    """Ascending created_at, ties broken by insertion order."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def serialize(row):
    return {k: v for k, v in row.items() if k not in INTERNAL_KEYS}
