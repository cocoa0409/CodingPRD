"""In-memory data store and logical clock.

The store starts EMPTY on every boot.  Nothing is ever seeded, preloaded or
hardcoded here: every row is created through the declared API surface.
"""
import itertools
import re
import uuid
from datetime import datetime, timedelta, timezone

# PRD 2.1 -- the ten declared roles.
ROLES = (
    "IntakeCoordinator",
    "ParentGuardian",
    "CollectionSite",
    "ProcessingTechnologist",
    "MedicalDirector",
    "RegistryOperator",
    "TransplantCenter",
    "BillingAdministrator",
    "FacilitiesEngineer",
    "PlatformAdmin",
)

# PRD 2.7 -- before any call to POST /_clock/set_current_utc the logical clock
# reads exactly 2026-08-01T00:00:00Z.  Wall-clock time is never consulted.
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class _DB(object):
    def __init__(self):
        self.clock = DEFAULT_CLOCK
        self._seq = itertools.count(1)
        self.unit_sequence = 0
        self.enrollments = {}
        self.accounts = {}
        self.kits = {}
        self.collections = {}
        self.units = {}
        self.runs = {}
        self.tests = {}
        self.screenings = {}
        self.tanks = {}
        self.excursions = {}
        self.listings = {}
        self.invoices = {}
        self.reservations = {}

    def next_seq(self):
        return next(self._seq)


db = _DB()


def now():
    return db.clock


def set_clock(dt):
    db.clock = dt


_TS_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2}):(\d{2})(\.\d+)?"
    r"([Zz]|[+-]\d{2}:?\d{2})?$"
)


def parse_ts(value):
    """Parse an RFC 3339 UTC timestamp.  Returns None when unparseable."""
    if not isinstance(value, str):
        return None
    m = _TS_RE.match(value.strip())
    if not m:
        return None
    frac = m.group(7) or ".0"
    try:
        micro = int(round(float(frac) * 1000000))
    except ValueError:
        return None
    if micro >= 1000000:
        micro = 999999
    try:
        base = datetime(
            int(m.group(1)), int(m.group(2)), int(m.group(3)),
            int(m.group(4)), int(m.group(5)), int(m.group(6)),
            micro, tzinfo=timezone.utc,
        )
    except ValueError:
        return None
    off = m.group(8)
    if off and off not in ("Z", "z"):
        sign = 1 if off[0] == "+" else -1
        digits = off[1:].replace(":", "")
        hours = int(digits[:2])
        minutes = int(digits[2:4])
        base = base - sign * timedelta(hours=hours, minutes=minutes)
    return base


_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def parse_date(value):
    """Parse a calendar date (`YYYY-MM-DD`) into midnight UTC.

    A full RFC 3339 UTC instant is also accepted and truncated to its date, so
    that a client may supply either form for a `_date` field.
    """
    if not isinstance(value, str):
        return None
    m = _DATE_RE.match(value.strip())
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)),
                            tzinfo=timezone.utc)
        except ValueError:
            return None
    parsed = parse_ts(value)
    if parsed is None:
        return None
    return parsed.replace(hour=0, minute=0, second=0, microsecond=0)


def iso(dt):
    """Serialize a datetime as ISO 8601 UTC with three fractional digits."""
    if dt is None:
        return None
    if isinstance(dt, str):
        return dt
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def pdt(value):
    """Parse a stored ISO string back into a datetime (None-safe)."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    return parse_ts(value)


def new_id():
    return str(uuid.uuid4())


def base_row(with_common=True):
    """Common system fields (PRD 2.4).  QualityTest passes with_common=False."""
    stamp = iso(now())
    row = {"id": new_id(), "created_at": stamp}
    if with_common:
        row["updated_at"] = stamp
        row["version"] = 1
    row["_seq"] = db.next_seq()
    return row


def touch(row):
    """Every mutation bumps updated_at and version (PRD 2.4)."""
    if "version" in row:
        row["updated_at"] = iso(now())
        row["version"] = row["version"] + 1
    return row


def by_created(rows):
    """created_at ASC with insertion order as the deterministic tie-break."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def public(row):
    """Strip internal bookkeeping keys from a row before serialization."""
    if row is None:
        return None
    return {k: v for k, v in row.items() if not k.startswith("_")}


def public_list(rows):
    return [public(r) for r in rows]
