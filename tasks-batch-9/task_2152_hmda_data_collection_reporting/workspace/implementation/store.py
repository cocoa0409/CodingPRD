"""In-memory data store, logical clock and row bookkeeping.

Everything lives in plain Python dicts keyed by id.  The store starts empty on
every boot; no entity is ever seeded here.
"""

import itertools
import uuid
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Logical clock (PRD 2.5) -- before any caller sets it the clock reads exactly
# 2026-08-01T00:00:00Z and it never falls back to real wall-clock time.
# ---------------------------------------------------------------------------
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_clock = {"now": DEFAULT_CLOCK}


def now():
    return _clock["now"]


def set_clock(value):
    _clock["now"] = value


# ---------------------------------------------------------------------------
# Collections
# ---------------------------------------------------------------------------
institutions = {}
applications = {}
demographic_entries = {}
geocode_assignments = {}
census_tracts = {}
edit_runs = {}
edit_exceptions = {}
filing_submissions = {}
disclosure_statements = {}
audit_samples = {}
audit_findings = {}
fair_lending_analyses = {}

_seq = itertools.count(1)


def new_id():
    return str(uuid.uuid4())


def iso(dt):
    """ISO 8601 UTC with exactly three fractional-second digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def new_row(versioned=True):
    """Mint the common resource properties described in PRD 2.4."""
    row = {
        "id": new_id(),
        "created_at": now(),
        "_seq": next(_seq),
    }
    if versioned:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    return row


def touch(row):
    """Refresh updated_at without moving the version counter."""
    if "updated_at" in row:
        row["updated_at"] = now()


def bump(row):
    """A mutation of the row: refresh updated_at and increment version by 1."""
    if "version" in row:
        row["version"] = row["version"] + 1
        row["updated_at"] = now()
    return row


def ordered(rows):
    """Creation order -- PRD 2.3 orders list results by created_at ascending."""
    return sorted(rows, key=lambda r: r["_seq"])
