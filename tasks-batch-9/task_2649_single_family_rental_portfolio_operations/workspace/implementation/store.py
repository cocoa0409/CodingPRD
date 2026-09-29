"""In-memory data store.

The store is EMPTY on every boot.  Nothing is ever seeded, preloaded or
hardcoded: every entity a test needs is built through the declared endpoints.
"""
import datetime
import itertools
import random
import string
import threading
import uuid

# ---------------------------------------------------------------------------
# Collections (dict keyed by entity id)
# ---------------------------------------------------------------------------
COLLECTIONS = [
    "markets",
    "scope_templates",
    "homes",
    "underwriting_cases",
    "vendors",
    "vendor_certifications",
    "renovation_projects",
    "work_orders",
    "prospects",
    "showing_slots",
    "rental_applications",
    "leases",
    "compliance_obligations",
]

DB = {name: {} for name in COLLECTIONS}

_seq_counter = itertools.count(1)
_lock = threading.RLock()

# ---------------------------------------------------------------------------
# Logical clock — boots at 2026-08-01T00:00:00Z, settable by System
# ---------------------------------------------------------------------------
CLOCK_BOOT = datetime.datetime(2026, 8, 1, 0, 0, 0, tzinfo=datetime.timezone.utc)
# PRD SS2.4 renders the boot value verbatim as `2026-08-01T00:00:00Z`, and a read of the
# clock returns the instant that was supplied, so the literal string is kept alongside the
# parsed datetime rather than re-rendered with three fractional digits.
CLOCK_BOOT_TEXT = "2026-08-01T00:00:00Z"
_clock = {"now": CLOCK_BOOT, "text": CLOCK_BOOT_TEXT}


def clock_now():
    """Current logical instant (timezone aware UTC datetime)."""
    return _clock["now"]


def clock_set(dt, text=None):
    _clock["now"] = dt
    _clock["text"] = text if text else fmt_instant(dt)


def clock_text():
    """The logical clock instant exactly as it was supplied (PRD SS2.4)."""
    return _clock["text"]


def clock_date():
    """Current logical date as a `datetime.date`."""
    return _clock["now"].date()


# ---------------------------------------------------------------------------
# Identifiers / timestamps
# ---------------------------------------------------------------------------
def new_id():
    return str(uuid.uuid4())


def next_seq():
    with _lock:
        return next(_seq_counter)


def iso_now():
    """Wall-clock instant, ISO 8601 UTC with exactly three fractional digits."""
    return fmt_instant(datetime.datetime.now(datetime.timezone.utc))


def fmt_instant(dt):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    dt = dt.astimezone(datetime.timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


# ---------------------------------------------------------------------------
# Row helpers
# ---------------------------------------------------------------------------
def base_row():
    """System fields shared by every persisted entity."""
    return {
        "id": new_id(),
        "created_at": iso_now(),
        "updated_at": iso_now(),
        "version": 1,
        "_seq": next_seq(),
    }


def insert(collection, row):
    DB[collection][row["id"]] = row
    return row


def get(collection, row_id):
    if not isinstance(row_id, str):
        return None
    return DB[collection].get(row_id)


def all_rows(collection):
    """Every row of a collection in creation order."""
    return sorted(DB[collection].values(), key=lambda r: (r["created_at"], r["_seq"]))


def touch(row):
    """Refresh `updated_at` and bump `version` by exactly 1 per request.

    Cascades may reach the same row through several hops; the PRD requires each
    touched row's version to be incremented by 1, so the bump is de-duplicated
    per request.
    """
    if row is None:
        return row
    try:
        from flask import g

        touched = getattr(g, "touched_rows", None)
        if touched is None:
            touched = set()
            g.touched_rows = touched
    except Exception:  # pragma: no cover - outside a request context
        touched = None
    key = (id(row), row.get("id"))
    if touched is not None and key in touched:
        row["updated_at"] = iso_now()
        return row
    if touched is not None:
        touched.add(key)
    row["version"] = int(row.get("version", 1)) + 1
    row["updated_at"] = iso_now()
    return row
