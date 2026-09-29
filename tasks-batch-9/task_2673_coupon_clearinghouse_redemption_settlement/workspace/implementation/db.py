"""In-memory data store and logical clock.

The store starts completely empty on every boot: nothing is seeded, preloaded
or hardcoded.  All persistence is plain Python dicts, so re-invoking start.sh
wipes every byte of state.
"""

import copy
import threading
import uuid
from datetime import datetime, timedelta, date

# PRD 2.5: the logical clock starts at exactly this instant on every boot.
CLOCK_START = datetime(2026, 8, 1, 0, 0, 0, 0)

COLLECTIONS = (
    "manufacturers",
    "retailers",
    "offers",
    "submissions",
    "lots",
    "items",
    "purchase_records",
    "statements",
    "invoices",
    "disputes",
    "clips",
    "events",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.clock = CLOCK_START
        self.seq = 0
        for name in COLLECTIONS:
            setattr(self, name, {})

    def next_seq(self):
        self.seq += 1
        return self.seq


db = Store()


# --------------------------------------------------------------------------
# transaction support: every request is all-or-nothing (PRD 2.11)
# --------------------------------------------------------------------------

def snapshot():
    return copy.deepcopy(db.__dict__)


def restore(snap):
    db.__dict__.clear()
    db.__dict__.update(snap)


# --------------------------------------------------------------------------
# clock helpers
# --------------------------------------------------------------------------

def now():
    return db.clock


def now_iso():
    return fmt_instant(db.clock)


def today():
    return db.clock.date()


def fmt_instant(dt):
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def fmt_date(d):
    return "%04d-%02d-%02d" % (d.year, d.month, d.day)


def parse_date(text):
    """Strict YYYY-MM-DD."""
    if not isinstance(text, str) or len(text) != 10:
        return None
    if text[4] != "-" or text[7] != "-":
        return None
    try:
        return date(int(text[0:4]), int(text[5:7]), int(text[8:10]))
    except (ValueError, TypeError):
        return None


def parse_instant(text):
    """ISO 8601 UTC instant; tolerant about fractional digits and offsets."""
    if not isinstance(text, str):
        return None
    raw = text.strip()
    if not raw:
        return None
    if raw.endswith("Z") or raw.endswith("z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        try:
            parsed = datetime.strptime(raw, "%Y-%m-%dT%H:%M:%S")
        except ValueError:
            return None
    if parsed.tzinfo is not None:
        offset = parsed.utcoffset() or timedelta(0)
        parsed = parsed.replace(tzinfo=None) - offset
    return parsed


def add_days(d, count):
    return d + timedelta(days=count)


# --------------------------------------------------------------------------
# row helpers
# --------------------------------------------------------------------------

def new_id():
    return str(uuid.uuid4())


def base_row(versioned=True, created_at=None):
    row = {
        "id": new_id(),
        "created_at": created_at or now_iso(),
    }
    if versioned:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    row["_seq"] = db.next_seq()
    return row


_local = threading.local()


def begin_request():
    _local.touched = set()


def _touched_set():
    touched = getattr(_local, "touched", None)
    if touched is None:
        touched = set()
        _local.touched = touched
    return touched


def touch(row):
    """Bump version / updated_at once per row per request (PRD 2.4, 2.8)."""
    if row is None or "version" not in row:
        return row
    touched = _touched_set()
    rid = row.get("id")
    if rid in touched:
        return row
    touched.add(rid)
    row["version"] = row["version"] + 1
    row["updated_at"] = now_iso()
    return row


def sort_rows(rows, descending=False):
    ordered = sorted(rows, key=lambda r: (r.get("created_at") or "", r.get("_seq") or 0))
    if descending:
        ordered.reverse()
    return ordered
