"""In-memory store, logical clock and common-field helpers.

Storage is process memory only: plain dicts keyed by uuid.  Nothing is written to
disk, so re-invoking start.sh wipes every byte of state.  Nothing is seeded here.
"""

import uuid
from datetime import datetime, timedelta, date

# ---------------------------------------------------------------- logical clock
# PRD §2.5: the server holds a logical UTC clock that starts at exactly this
# instant on every boot and is never read from wall-clock time.
CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, 0)

_clock = {"now": CLOCK_DEFAULT}


def now():
    return _clock["now"]


def set_clock(dt):
    previous = _clock["now"]
    _clock["now"] = dt
    return previous


def today():
    return _clock["now"].date()


# ------------------------------------------------------------------- formatting
def iso(dt):
    """Render a domain instant.

    PRD §2.5 gives the logical clock's own rendering verbatim — "the logical clock
    reads exactly ``2026-08-01T00:00:00Z``" — so an instant carrying no
    sub-second component is written without a fractional part.  Instants that do
    carry milliseconds keep them, which is what pins a derived deadline to
    ``23:59:59.999Z``.  Only the audit columns of §2.4 and the
    ``api_request_timestamp`` of §2.2 are mandated to always show three
    fractional digits; those use :func:`iso_ms`.
    """
    if dt is None:
        return None
    stamp = "%04d-%02d-%02dT%02d:%02d:%02d" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
    )
    if dt.microsecond:
        stamp += ".%03d" % (dt.microsecond // 1000,)
    return stamp + "Z"


def iso_ms(dt):
    """Render an instant with three fractional digits always (PRD §2.2, §2.4)."""
    if dt is None:
        return None
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, dt.microsecond // 1000,
    )


def iso_date(d):
    if d is None:
        return None
    return "%04d-%02d-%02d" % (d.year, d.month, d.day)


def now_iso():
    return iso(_clock["now"])


def now_iso_ms():
    return iso_ms(_clock["now"])


def parse_instant(value):
    """Parse an ISO-8601 UTC instant.  Returns None when unparseable."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1]
    elif text.endswith("+00:00"):
        text = text[:-6]
    elif text.endswith("-00:00"):
        text = text[:-6]
    text = text.replace(" ", "T")
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def parse_day(value):
    """Parse a calendar date (YYYY-MM-DD).  Returns None when unparseable."""
    dt = parse_instant(value)
    return dt.date() if dt is not None else None


def end_of_day(d):
    """Deadline instant pinned to 23:59:59.999Z on the given calendar date."""
    return datetime(d.year, d.month, d.day, 23, 59, 59, 999000)


def add_days(d, n):
    return d + timedelta(days=n)


def days_in_month(year, month):
    if month == 12:
        return 31
    return (date(year, month + 1, 1) - timedelta(days=1)).day


def add_years(d, n):
    """Calendar-year addition, clamping Feb 29 to the last day of the month."""
    year = d.year + n
    day = min(d.day, days_in_month(year, d.month))
    return date(year, d.month, day)


# ----------------------------------------------------------------------- store
class Rec(dict):
    """Attribute-accessible record."""

    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(key)

    def __setattr__(self, key, value):
        self[key] = value


KINDS = (
    "facilities",
    "periods",
    "ownership_changes",
    "responsible_persons",
    "listings",
    "ingredients",
    "substantiations",
    "review_items",
    "adverse_events",
    "inspections",
    "recalls",
    "withdrawals",
    "distribution_records",
    "ledger",
)

db = {kind: {} for kind in KINDS}

_counters = {"seq": 0}


def reset():
    for kind in KINDS:
        db[kind] = {}
    _counters["seq"] = 0
    _clock["now"] = CLOCK_DEFAULT


def next_seq():
    _counters["seq"] += 1
    return _counters["seq"]


def new_id():
    return str(uuid.uuid4())


def insert(kind, fields, common=True):
    rec = Rec(fields)
    rec["id"] = new_id()
    rec["_seq"] = next_seq()
    rec["_kind"] = kind
    stamp = now_iso_ms()
    rec["created_at"] = stamp
    if common:
        rec["updated_at"] = stamp
        rec["version"] = 1
    db[kind][rec["id"]] = rec
    return rec


_touched = set()


def begin_request():
    _touched.clear()


def touch(rec):
    """PRD §2.4: every mutation refreshes updated_at and bumps version by one.

    A resource that several cascade hops of the same request touch still rises by
    exactly 1 (PRD §2.10 / §3.1: "the version of every touched listing and
    designee each rise by exactly 1").
    """
    if rec is None:
        return rec
    if rec["id"] in _touched:
        rec["updated_at"] = now_iso_ms()
        return rec
    _touched.add(rec["id"])
    rec["updated_at"] = now_iso_ms()
    rec["version"] = int(rec.get("version", 0)) + 1
    return rec


def get(kind, rid):
    if not isinstance(rid, str) or not rid:
        return None
    return db[kind].get(rid)


def all_of(kind):
    return list(db[kind].values())


def by_seq(records):
    return sorted(records, key=lambda r: r["_seq"])


def by_created(records):
    """Ascending created_at with insertion order as the deterministic tiebreak."""
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))


def by_created_desc(records):
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]), reverse=True)
