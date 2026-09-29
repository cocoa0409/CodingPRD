"""In-memory store, id minting and the logical clock.

The store is created empty on every boot.  No entity is ever seeded: the only
startup state is the logical clock's fixed default of 2026-08-01T00:00:00Z
(PRD 2.5).
"""

import re
import uuid
from datetime import datetime, timezone

CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"

_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,9}))?)?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


def parse_iso(value):
    """Parse an ISO 8601 UTC datetime.  Returns None when malformed."""
    if not isinstance(value, str):
        return None
    m = _ISO_RE.match(value.strip())
    if not m:
        return None
    year, month, day, hh, mm = (int(m.group(i)) for i in range(1, 6))
    ss = int(m.group(6) or 0)
    frac = m.group(7) or ""
    micro = int((frac + "000000")[:6]) if frac else 0
    tzpart = m.group(8)
    try:
        dt = datetime(year, month, day, hh, mm, ss, micro, tzinfo=timezone.utc)
    except ValueError:
        return None
    if tzpart and tzpart not in ("Z", "z"):
        sign = 1 if tzpart[0] == "+" else -1
        body = tzpart[1:].replace(":", "")
        offset_min = int(body[:2]) * 60 + int(body[2:4])
        # normalise to UTC
        dt = dt - sign * _minutes(offset_min)
    return dt


def _minutes(n):
    from datetime import timedelta

    return timedelta(minutes=n)


def fmt_iso(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year,
        dt.month,
        dt.day,
        dt.hour,
        dt.minute,
        dt.second,
        dt.microsecond // 1000,
    )


def new_id():
    return str(uuid.uuid4())


class Store(object):
    COLLECTIONS = (
        "facilities",
        "departments",
        "revenue_codes",
        "charge_items",
        "price_rules",
        "change_requests",
        "code_update_cycles",
        "code_update_entries",
        "payer_contracts",
        "batches",
        "captured_charges",
        "findings",
        "analyses",
        "transparency_files",
    )

    def __init__(self):
        self.reset()

    def reset(self):
        for name in self.COLLECTIONS:
            setattr(self, name, {})
        self.now = parse_iso(CLOCK_STARTUP_DEFAULT)
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq

    # -- helpers ------------------------------------------------------------
    def stamp_new(self, row, versioned=True):
        row["id"] = new_id()
        row["created_at"] = fmt_iso(self.now)
        row["_created"] = self.now
        row["_seq"] = self.next_seq()
        if versioned:
            row["updated_at"] = fmt_iso(self.now)
            row["version"] = 1
        return row

    def touch(self, row):
        row["updated_at"] = fmt_iso(self.now)
        row["version"] = row.get("version", 1) + 1
        return row

    def ordered(self, collection, predicate=None):
        rows = [r for r in collection.values() if predicate is None or predicate(r)]
        rows.sort(key=lambda r: (r["_created"], r["_seq"]))
        return rows


STORE = Store()


def serialize(row, extra=None):
    out = {k: v for k, v in row.items() if not k.startswith("_")}
    if extra:
        out.update(extra)
    return out
