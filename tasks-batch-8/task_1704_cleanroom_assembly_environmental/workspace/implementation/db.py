"""In-memory data store, logical clock, and time/record helpers.

The store starts completely empty on every boot; no seeding of any kind.
All time-dependent behavior uses a server-side logical clock that starts at
exactly 2026-08-01T00:00:00Z and never falls back to wall-clock time.
"""

import re
import threading
import uuid
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


class Store:
    def __init__(self):
        self.rooms = {}
        self.personnel = {}
        self.qualifications = {}
        self.sampling_points = {}
        self.samples = {}
        self.excursions = {}
        self.investigations = {}
        self.certifications = {}
        self.transfers = {}
        self.batches = {}
        self.travelers = {}
        self.entry_logs = {}
        self.cleaning_programs = {}
        self.cleaning_cycles = {}
        self.audits = {}
        self.findings = {}
        self.seq = 0  # global monotonic event counter


store = Store()

# One global reentrant lock; app.py wraps every request in it so each request
# executes atomically (immediate consistency, no partial cascades).
GLOBAL_LOCK = threading.RLock()


def next_seq():
    store.seq += 1
    return store.seq


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
_clock_now = _EPOCH


def now():
    """Current logical time (aware, UTC)."""
    return _clock_now


def set_clock(dt):
    global _clock_now
    _clock_now = dt


# ---------------------------------------------------------------------------
# ISO-8601 helpers
# ---------------------------------------------------------------------------

_ISO_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:?\d{2})?$"
)


def parse_iso(value):
    """Parse an ISO-8601 string into an aware UTC datetime.

    Raises ValueError for anything malformed. Naive inputs are assumed UTC.
    """
    if not isinstance(value, str):
        raise ValueError("not a string")
    text = value.strip()
    if not _ISO_RE.match(text):
        raise ValueError("malformed ISO-8601")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    # normalize offsets like +0000 -> +00:00 for fromisoformat
    if len(text) >= 5 and (text[-5] in "+-") and text[-2] != ":":
        text = text[:-2] + ":" + text[-2:]
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def is_iso(value):
    try:
        parse_iso(value)
        return True
    except (ValueError, TypeError):
        return False


def iso_ms(dt):
    """Format an aware datetime as ISO-8601 UTC with three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_iso():
    return iso_ms(now())


def trunc_second(dt):
    """Truncate to whole seconds (timestamp comparisons use second precision)."""
    return dt.replace(microsecond=0)


# ---------------------------------------------------------------------------
# Record helpers
# ---------------------------------------------------------------------------


def new_record(fields):
    """Create a record dict with common system fields populated."""
    ts = now_iso()
    rec = dict(fields)
    rec["id"] = str(uuid.uuid4())
    rec["created_at"] = ts
    rec["updated_at"] = ts
    rec["version"] = 1
    rec["_created_seq"] = next_seq()
    return rec


def mutate(rec):
    """Apply the standard per-mutation bookkeeping (updated_at, version)."""
    rec["updated_at"] = now_iso()
    rec["version"] += 1


def pub(rec):
    """Public view of a record: strip internal underscore-prefixed keys."""
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def created_sort_key(rec):
    """Default list ordering: created_at ASC, creation sequence as tie-break."""
    return (rec["created_at"], rec["_created_seq"])
