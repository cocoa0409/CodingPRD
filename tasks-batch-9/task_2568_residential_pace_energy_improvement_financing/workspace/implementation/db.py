"""In-memory store plus the logical program clock.

The store starts EMPTY on every boot: nothing is seeded, preloaded or
hardcoded here. Every row is built by a test through the declared API surface.
"""

import random
import string
import uuid
from datetime import datetime, timezone

# PRD 2.4: before any client moves it the logical clock reads exactly this
# instant, and it never falls back to real wall-clock time.
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_clock = {"now": DEFAULT_CLOCK}

COLLECTIONS = (
    "properties",
    "liens",
    "products",
    "contractors",
    "applications",
    "measures",
    "agreements",
    "certificates",
    "disbursements",
    "complaints",
    "assessments",
    "installments",
    "transfers",
)

STORES = {name: {} for name in COLLECTIONS}


def reset():
    for name in COLLECTIONS:
        STORES[name] = {}
    _clock["now"] = DEFAULT_CLOCK


# --------------------------------------------------------------------------
# Logical clock
# --------------------------------------------------------------------------
def now():
    return _clock["now"]


def set_now(value):
    previous = _clock["now"]
    _clock["now"] = value
    return previous


def today():
    return _clock["now"].date()


def iso(value):
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.4)."""
    if value is None:
        return None
    if value.tzinfo is not None:
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


def now_iso():
    return iso(now())


def parse_instant(text):
    """Parse an ISO 8601 instant; returns None when unparseable."""
    if not isinstance(text, str) or not text.strip():
        return None
    raw = text.strip()
    if raw.endswith("Z") or raw.endswith("z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


# --------------------------------------------------------------------------
# Identifiers / rows
# --------------------------------------------------------------------------
def new_id():
    return str(uuid.uuid4())


def request_id():
    return "req_" + "".join(
        random.choice(string.ascii_uppercase + string.digits) for _ in range(20)
    )


def create(collection, data):
    row = dict(data)
    row["id"] = new_id()
    stamp = now_iso()
    row["created_at"] = stamp
    row["updated_at"] = stamp
    row["version"] = 1
    STORES[collection][row["id"]] = row
    return row


def touch(row):
    """A mutation refreshes updated_at and bumps version (PRD 2.4)."""
    row["updated_at"] = now_iso()
    row["version"] = int(row.get("version", 1)) + 1
    return row


def get(collection, row_id):
    if not isinstance(row_id, str):
        return None
    return STORES[collection].get(row_id)


def rows(collection):
    return list(STORES[collection].values())


def public(row):
    """Serialize a row, hiding internal bookkeeping keys."""
    return {key: value for key, value in row.items() if not key.startswith("_")}


def by_created_at(items):
    return sorted(items, key=lambda item: item["created_at"])
