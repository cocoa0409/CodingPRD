"""In-memory data store, logical clock, and identity/timestamp helpers.

Storage is process-local dicts only. The store starts completely empty on
every boot; no seeding of any kind. The logical clock starts at exactly
2026-08-01T00:00:00Z and never falls back to wall-clock time.
"""

import itertools
import uuid
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Collections
# ---------------------------------------------------------------------------

db = {
    "fisheries": {},
    "operators": {},
    "vessels": {},
    "observers": {},
    "debriefers": {},
    "em_reviewers": {},
    "coverage_plans": {},
    "selection_runs": {},
    "selection_notices": {},
    "deployments": {},
    "safety_inspections": {},
    "haul_samples": {},
    "harassment_reports": {},
    "em_enrollments": {},
    "em_trips": {},
    "invoices": {},
}

_seq_counter = itertools.count(1)

# ---------------------------------------------------------------------------
# Logical clock (PRD section 2.7)
# ---------------------------------------------------------------------------

CLOCK = {"now": datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)}


def clock_now():
    return CLOCK["now"]


def clock_set(dt):
    CLOCK["now"] = dt


# ---------------------------------------------------------------------------
# Identity / sequence / timestamps
# ---------------------------------------------------------------------------


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(_seq_counter)


def now_wall():
    return datetime.now(timezone.utc)


def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.4)."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def fmt_clock(dt):
    """Canonical logical-clock rendering: no fraction when the value lands on a
    whole second (the startup reading is '2026-08-01T00:00:00Z'), otherwise
    three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond == 0:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return fmt_ts(dt)


# ---------------------------------------------------------------------------
# Entity lifecycle helpers
# ---------------------------------------------------------------------------


def new_entity(fields):
    """Create a primary-resource dict with the common system fields (2.4).

    Timestamps read the logical clock (PRD 2.7: the program runs on a logical
    clock rather than wall-clock time and never falls back to wall-clock)."""
    e = dict(fields)
    e["id"] = new_id()
    ts = fmt_ts(clock_now())
    e["created_at"] = ts
    e["updated_at"] = ts
    e["version"] = 1
    e["_seq"] = next_seq()
    return e


def new_inspection(fields):
    """SafetyInspection: immutable; carries only id and created_at (2.4)."""
    e = dict(fields)
    e["id"] = new_id()
    e["created_at"] = fmt_ts(clock_now())
    e["_seq"] = next_seq()
    return e


def touch(e):
    """Register a modification: refresh updated_at and bump version (2.4)."""
    e["updated_at"] = fmt_ts(clock_now())
    e["version"] += 1
