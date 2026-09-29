"""In-memory data store, logical clock, id/timestamp minting and version bumping.

Storage is process-local Python dicts keyed by id.  Nothing is seeded, preloaded
or hardcoded: every row is created by a declared endpoint.
"""
import itertools
import random
import re
import string
import threading
import uuid
from datetime import date, datetime, timedelta, timezone

# PRD section 2.6: on startup the logical clock reads exactly this instant and
# never falls back to real wall-clock time.
LOGICAL_CLOCK_DEFAULT = "2026-08-01T00:00:00.000Z"

_ISO_DT_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}[Tt ]\d{2}:\d{2}(:\d{2}(\.\d{1,12})?)?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_instant(value):
    """Parse an ISO 8601 instant into a tz-aware UTC datetime, or return None."""
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not _ISO_DT_RE.match(raw):
        return None
    text = raw.replace("t", "T").replace(" ", "T")
    if text.endswith("z") or text.endswith("Z"):
        text = text[:-1] + "+00:00"
    # Normalise a fractional part longer than 6 digits (datetime limit).
    m = re.match(r"^(.*?)(\.\d+)(.*)$", text)
    if m:
        frac = m.group(2)[:7]
        text = m.group(1) + frac + m.group(3)
    # Normalise +HHMM to +HH:MM
    m = re.match(r"^(.*)([+-])(\d{2})(\d{2})$", text)
    if m:
        text = "%s%s%s:%s" % (m.group(1), m.group(2), m.group(3), m.group(4))
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_day(value):
    """Parse a YYYY-MM-DD string into a date, or return None."""
    if not isinstance(value, str) or not _ISO_DATE_RE.match(value.strip()):
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


def format_instant(moment):
    """ISO 8601 UTC with exactly three fractional digits."""
    moment = moment.astimezone(timezone.utc)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (moment.microsecond // 1000)) + "Z"


def now_stamp():
    """Wall-clock server timestamp used for created_at / updated_at / meta."""
    return format_instant(datetime.now(timezone.utc))


def new_id():
    return str(uuid.uuid4())


def new_request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


class Store(object):
    """All collections live here.  Every collection starts empty on boot."""

    TABLES = (
        "plants",
        "haulers",
        "escort_crews",
        "set_crews",
        "orders",
        "sections",
        "sites",
        "permits",
        "route_legs",
        "escort_assignments",
        "set_jobs",
        "marriage_joints",
        "anchor_certs",
        "claims",
    )

    def __init__(self):
        self.lock = threading.RLock()
        self.reset()

    def reset(self):
        for table in self.TABLES:
            setattr(self, table, {})
        self.clock = parse_instant(LOGICAL_CLOCK_DEFAULT)
        self._counter = itertools.count(1)

    def next_seq(self):
        return next(self._counter)

    # --- logical clock -----------------------------------------------------
    def clock_instant(self):
        return self.clock

    def clock_date(self):
        return self.clock.date()

    def set_clock(self, moment):
        self.clock = moment.astimezone(timezone.utc)


db = Store()


def base_row(with_version=True):
    """Common fields per PRD section 2.4."""
    stamp = now_stamp()
    row = {"id": new_id(), "created_at": stamp}
    if with_version:
        row["updated_at"] = stamp
        row["version"] = 1
    row["_seq"] = db.next_seq()
    return row


def mark(row):
    """Bump a row's version/updated_at at most once per request (PRD 2.4/2.9)."""
    from flask import g

    if row is None or "version" not in row:
        return
    touched = getattr(g, "touched_rows", None)
    if touched is None:
        touched = set()
        g.touched_rows = touched
    key = row["id"]
    if key in touched:
        return
    touched.add(key)
    row["version"] = row["version"] + 1
    row["updated_at"] = now_stamp()


def public(row, drop=()):
    """Strip internal bookkeeping keys from a stored row."""
    out = {}
    for key, value in row.items():
        if key.startswith("_") or key in drop:
            continue
        out[key] = value
    return out


def sorted_rows(rows):
    """Collections are always sorted by created_at ascending (PRD 2.3)."""
    return sorted(rows, key=lambda r: (r.get("created_at", ""), r.get("_seq", 0)))


def day_range(start, end):
    current = start
    while current <= end:
        yield current
        current = current + timedelta(days=1)
