"""In-memory data store, logical clock and shared primitives.

The store starts EMPTY on every boot. Nothing is seeded, preloaded or
hardcoded -- every entity is built by clients through the declared API.
"""
import datetime
import random
import re
import string
import uuid

# --------------------------------------------------------------------------
# Logical clock
# --------------------------------------------------------------------------
# Mandatory startup default; the service never falls back to wall-clock time.
CLOCK_DEFAULT = datetime.datetime(2026, 8, 1, 0, 0, 0, 0)

_clock = {"now": CLOCK_DEFAULT}

_ISO_INSTANT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt](\d{2}):(\d{2}):(\d{2})(\.(\d{1,9}))?"
    r"([Zz]|[+-]\d{2}:\d{2})$"
)
_ISO_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def clock_now():
    """Current logical clock instant (naive UTC datetime)."""
    return _clock["now"]


def clock_date():
    """Date part of the logical clock instant."""
    return _clock["now"].date()


def set_clock(dt):
    _clock["now"] = dt


def reset_clock():
    _clock["now"] = CLOCK_DEFAULT


def parse_instant(value):
    """Parse an ISO-8601 UTC instant. Returns None when malformed."""
    if not isinstance(value, str):
        return None
    m = _ISO_INSTANT_RE.match(value.strip())
    if not m:
        return None
    frac = m.group(8) or "0"
    micro = int((frac + "000000")[:6])
    try:
        base = datetime.datetime(
            int(m.group(1)), int(m.group(2)), int(m.group(3)),
            int(m.group(4)), int(m.group(5)), int(m.group(6)), micro,
        )
    except ValueError:
        return None
    off = m.group(9)
    if off and off.upper() != "Z":
        sign = 1 if off[0] == "+" else -1
        hh = int(off[1:3])
        mm = int(off[4:6])
        base = base - sign * datetime.timedelta(hours=hh, minutes=mm)
    return base


def parse_date(value):
    """Parse an ISO-8601 calendar date. Returns None when malformed."""
    if not isinstance(value, str):
        return None
    m = _ISO_DATE_RE.match(value.strip())
    if not m:
        return None
    try:
        return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def fmt_instant(dt):
    """ISO-8601 UTC instant with exactly three fractional digits."""
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def fmt_date(d):
    if d is None:
        return None
    if isinstance(d, str):
        return d
    return d.isoformat()


def new_id():
    return str(uuid.uuid4())


def new_request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


# --------------------------------------------------------------------------
# Collections -- plain dicts keyed by id, empty at boot
# --------------------------------------------------------------------------
schools = {}
terms = {}
teachers = {}
students = {}
sections = {}
enrollments = {}
vendor_apps = {}
building_allocations = {}
app_accounts = {}
sync_runs = {}
error_queue_items = {}

_seq = {"n": 0}


def next_seq():
    _seq["n"] += 1
    return _seq["n"]


def stamp_new(record):
    """Give a brand-new record its common fields."""
    now = fmt_instant(clock_now())
    record["id"] = new_id()
    record["created_at"] = now
    record["updated_at"] = now
    record["version"] = 1
    record["_seq"] = next_seq()
    return record


def touch(record):
    """A mutation reached this record: bump updated_at and version."""
    record["updated_at"] = fmt_instant(clock_now())
    record["version"] = record.get("version", 1) + 1
    return record


def sorted_records(collection):
    """Default list ordering: created_at ascending (creation order)."""
    return sorted(collection.values(), key=lambda r: (r["created_at"], r["_seq"]))
