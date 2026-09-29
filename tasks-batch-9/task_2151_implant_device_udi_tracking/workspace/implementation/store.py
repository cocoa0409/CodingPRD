"""In-memory data store, id/timestamp minting and the logical clock.

Storage is process-local dictionaries keyed by id.  Nothing is ever persisted to
disk and NOTHING is seeded at import time: every collection starts empty on a
fresh boot and is only ever populated through the declared HTTP endpoints.
"""
import random
import string
import uuid
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------- constants
LOGICAL_CLOCK_DEFAULT = "2026-08-01T00:00:00Z"

COLLECTIONS = (
    "vendors",
    "agreements",
    "catalog_items",
    "lots",
    "device_units",
    "patients",
    "cases",
    "implant_records",
    "charges",
    "registry_submissions",
    "field_actions",
    "recall_notifications",
    "invoices",
    "explant_records",
)


def _canonical(dt):
    """ISO 8601 UTC with exactly three fractional-second digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_iso(value):
    """Parse an ISO-8601 instant.  Returns an aware UTC datetime or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value):
    """Parse a plain YYYY-MM-DD calendar date.  Returns a date or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if len(text) != 10:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def expiry_instant(expiration_date):
    """The expiry INSTANT of a lot: its expiration_date at 23:59:59.999Z."""
    d = parse_date(expiration_date)
    if d is None:
        return None
    return datetime(d.year, d.month, d.day, 23, 59, 59, 999000, tzinfo=timezone.utc)


class Store(object):
    def __init__(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self._seq = 0
        self.ops_run_index = 0
        self.clock_dt = parse_iso(LOGICAL_CLOCK_DEFAULT)
        self.clock_str = LOGICAL_CLOCK_DEFAULT

    # -------------------------------------------------------- logical clock
    def set_clock(self, dt, raw):
        self.clock_dt = dt
        # Preserve the caller's rendering when it is already a UTC literal so
        # that business stamps read back byte-identical to what was set.
        text = raw.strip() if isinstance(raw, str) else None
        if text and (text.endswith("Z") or text.endswith("z")):
            self.clock_str = text
        else:
            self.clock_str = _canonical(dt)

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def reset():
    global db
    db = Store()


# ----------------------------------------------------------------- helpers
def new_id():
    return str(uuid.uuid4())


def request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def wall_now():
    return _canonical(datetime.now(timezone.utc))


def clock_dt():
    return db.clock_dt


def clock_iso():
    return db.clock_str


def iso(dt):
    if dt is None:
        return None
    return _canonical(dt)


def iso_like(dt, sample):
    """Render `dt` in the same fractional-second style as `sample`.

    Derived instants (a registry deadline, a recall due date) are reported in
    the same rendering as the instant they were measured from, so a client that
    set the clock as `...T00:00:00Z` reads the derived stamp back the same way.
    """
    if dt is None:
        return None
    if isinstance(sample, str) and "." in sample:
        return _canonical(dt)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def plus_days(dt, days):
    return dt + timedelta(days=days)


def base_record():
    stamp = wall_now()
    return {
        "id": new_id(),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
        "_seq": db.next_seq(),
    }


def touch(entity):
    """Advance a row's version once per request and refresh updated_at.

    Every row touched anywhere along a cascade chain has its updated_at
    refreshed and its version incremented (PRD 2.4/2.12).  A row mutated
    several times inside a single request advances exactly one version.
    """
    if entity is None:
        return
    try:
        from flask import g, has_request_context

        if has_request_context():
            seen = getattr(g, "_touched", None)
            if seen is None:
                seen = set()
                g._touched = seen
            if entity["id"] in seen:
                entity["updated_at"] = wall_now()
                return
            seen.add(entity["id"])
    except Exception:  # pragma: no cover - defensive only
        pass
    entity["version"] = entity.get("version", 1) + 1
    entity["updated_at"] = wall_now()


def ordered(values):
    """Deterministic created_at ASC ordering (never id order)."""
    return sorted(values, key=lambda e: (e["created_at"], e["_seq"]))
