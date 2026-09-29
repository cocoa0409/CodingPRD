"""In-memory data store, the logical program clock and shared helpers.

Storage is a set of plain dicts keyed by row id.  Nothing is persisted, nothing
is seeded: every boot starts completely empty and every row a test needs is
built through the declared endpoints.
"""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

# --- collections ---------------------------------------------------------
# One dict per resource kind, keyed by the row's `id`.
COLLECTIONS = (
    "policyholders",
    "insurers",
    "dwellings",
    "offers",
    "policies",
    "cycles",
    "grants",
    "contractors",
    "projects",
    "inspections",
    "events",
    "layers",
    "claims",
    "allocations",
)

DB = {name: {} for name in COLLECTIONS}

# Monotonic insertion counter used only as a stable tie-break for the
# created_at ascending default sort (many rows can share a logical instant).
_SEQ = {"n": 0}

# The logical program clock.  PRD 2.5: it begins at exactly 2026-08-01T00:00:00Z
# and never falls back to real time.
CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
_CLOCK = {"now": CLOCK_EPOCH}


def reset():
    for name in COLLECTIONS:
        DB[name] = {}
    _SEQ["n"] = 0
    _CLOCK["now"] = CLOCK_EPOCH


def next_seq():
    _SEQ["n"] += 1
    return _SEQ["n"]


def new_id():
    return str(uuid.uuid4())


# --- clock ----------------------------------------------------------------

def clock_now():
    return _CLOCK["now"]


def set_clock(dt):
    _CLOCK["now"] = dt


def now_iso():
    return iso(_CLOCK["now"])


# --- timestamp formatting / parsing ---------------------------------------

def iso(dt):
    """ISO 8601 UTC instant with exactly three fractional-second digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def parse_dt(value):
    """Parse an ISO 8601 instant; returns None when the value is unusable."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def dt_of(row, field):
    """Parse a stored timestamp field back into a datetime."""
    if row is None:
        return None
    return parse_dt(row.get(field))


def plus_days(dt, days):
    return dt + timedelta(days=days)


def plus_minutes(dt, minutes):
    return dt + timedelta(minutes=minutes)


def whole_days_between(later, earlier):
    """Floor of (later - earlier) in whole days; negative spans give zero."""
    if later is None or earlier is None:
        return 0
    delta = later - earlier
    if delta.total_seconds() <= 0:
        return 0
    return int(delta.total_seconds() // 86400)


# --- money / rounding -----------------------------------------------------

def dec(value):
    """Exact Decimal from an int, str or float without binary noise."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def round_half_up(value):
    """Round exactly once, half up, to a whole cent (an int)."""
    return int(dec(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# --- row lifecycle --------------------------------------------------------

def insert(collection, row, audited=True):
    """Insert a freshly minted row, stamping identity and audit fields."""
    now = now_iso()
    body = {"id": new_id(), "created_at": now}
    if audited:
        body["updated_at"] = now
        body["version"] = 1
    body.update(row)
    body["_seq"] = next_seq()
    DB[collection][body["id"]] = body
    return body


def touch(row):
    """PRD 2.4/2.9: any change to a row refreshes updated_at and bumps version.

    Applied to cascaded rows exactly as it is to the direct target.
    """
    if row is None:
        return row
    if "version" in row:
        row["updated_at"] = now_iso()
        row["version"] = row["version"] + 1
    return row


def public(row):
    """The wire representation: every stored field except internal bookkeeping."""
    if row is None:
        return None
    return {k: v for k, v in row.items() if not k.startswith("_")}


def all_rows(collection):
    """Every row in insertion-stable created_at ascending order."""
    rows = list(DB[collection].values())
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return rows


def find(collection, **predicates):
    out = []
    for row in all_rows(collection):
        if all(row.get(k) == v for k, v in predicates.items()):
            out.append(row)
    return out
