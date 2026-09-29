"""In-memory data store for the Certified Payroll & Prevailing Wage Compliance API.

Storage is process-local Python dicts keyed by id. Nothing is persisted to disk
and NOTHING is seeded at import time -- every collection starts empty on every
boot. Tests construct all entities through the declared HTTP endpoints.
"""

import uuid
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------------------
# Collections -- all empty at boot. Never pre-populated.
# ---------------------------------------------------------------------------
reporting_portals = {}
wage_determinations = {}
wage_rates = {}
contractors = {}
contractor_staff = {}
apprentice_programs = {}
fringe_plans = {}
projects = {}
contract_assignments = {}
workers = {}
payroll_submissions = {}
payroll_lines = {}
interviews = {}
findings = {}
restitution_payments = {}

ALL_COLLECTIONS = (
    reporting_portals,
    wage_determinations,
    wage_rates,
    contractors,
    contractor_staff,
    apprentice_programs,
    fringe_plans,
    projects,
    contract_assignments,
    workers,
    payroll_submissions,
    payroll_lines,
    interviews,
    findings,
    restitution_payments,
)

# ---------------------------------------------------------------------------
# Logical clock. Reads exactly 2026-08-01T00:00:00.000Z before any clock call
# and never falls back to wall-clock time.
# ---------------------------------------------------------------------------
CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, 0, tzinfo=timezone.utc)

_state = {"clock": CLOCK_EPOCH, "seq": 0}


def now():
    return _state["clock"]


def set_clock(instant):
    _state["clock"] = instant


def next_seq():
    _state["seq"] += 1
    return _state["seq"]


def new_id():
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Timestamp helpers -- ISO 8601 UTC with exactly three fractional digits.
# ---------------------------------------------------------------------------
def iso(instant):
    if instant is None:
        return None
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=timezone.utc)
    instant = instant.astimezone(timezone.utc)
    return instant.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (instant.microsecond // 1000)


def parse_iso(value):
    """Parse an ISO 8601 instant. Returns None when unparseable."""
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


def days(count):
    return timedelta(days=count)


def hours(count):
    return timedelta(hours=count)


# ---------------------------------------------------------------------------
# Row helpers
# ---------------------------------------------------------------------------
def base_row(versioned=True):
    """Create the common system fields for a new row."""
    row = {"id": new_id(), "created_at": now(), "_seq": next_seq()}
    if versioned:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    return row


def touch(row):
    """Advance a versioned row's version counter and updated_at stamp."""
    if row is None:
        return row
    if "version" in row:
        row["version"] = row["version"] + 1
        row["updated_at"] = now()
    return row


def ordered(collection, predicate=None):
    """Rows ordered by created_at ascending, stable on insertion sequence."""
    rows = [r for r in collection.values() if predicate is None or predicate(r)]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return rows
