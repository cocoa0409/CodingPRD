"""In-memory data store and the logical clock.

Nothing here is persisted and NOTHING is seeded: every dict below starts empty
on every boot, so a start.sh re-invocation wipes every byte of state.  All
entities that any test needs are built through the declared API surface.
"""

import itertools
import uuid
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Logical clock (PRD 2.4): starts at exactly 2026-08-01T00:00:00Z on boot and
# moves only when a ComplianceOfficer advances it.  The host wall clock is
# never consulted for any domain comparison.
# ---------------------------------------------------------------------------
CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_state = {"clock": CLOCK_EPOCH}

_seq = itertools.count(1)

# ---------------------------------------------------------------------------
# Tables -- all empty at import time.
# ---------------------------------------------------------------------------
builders = {}
underwriting_reviews = {}
homeowners = {}
neutrals = {}
policies = {}
coverage_terms = {}
transfers = {}
claims = {}
assessments = {}
reserve_entries = {}
escalation_cases = {}


def clock_now():
    """Current logical-clock instant (timezone-aware UTC datetime)."""
    return _state["clock"]


def clock_set(instant):
    _state["clock"] = instant


def clock_date():
    """Current logical-clock calendar date."""
    return _state["clock"].date()


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(_seq)


def iso_ms(dt):
    """ISO 8601 UTC with exactly three fractional-second digits."""
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def wall_now_iso():
    """Audit-field timestamp.  Audit stamps are wall-clock; every *domain*
    date/instant (reported_date, assessment_date, denial_date,
    default_declared_at, every comparison) reads the logical clock."""
    return iso_ms(datetime.now(timezone.utc))


def stamp_create(row, versioned=True):
    """Attach id / created_at (+ updated_at, version when the row is mutable)."""
    row["id"] = new_id()
    row["created_at"] = wall_now_iso()
    if versioned:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    row["_seq"] = next_seq()
    return row


def touch(row):
    """One mutating request bumps version by exactly one, no matter how many
    fields inside the row it rewrites."""
    row["updated_at"] = wall_now_iso()
    row["version"] = row.get("version", 0) + 1
    return row


def public(row):
    return {k: v for k, v in row.items() if not k.startswith("_")}


def sort_key_created(row):
    return (row["created_at"], row["_seq"])


# ---------------------------------------------------------------------------
# Version bookkeeping.
#
# PRD 2.4: "A single mutating request bumps `version` on a given row by exactly
# one, no matter how many fields inside that row it rewrites."  Cascades touch
# the same row more than once (the reassessment that re-scores and then
# suspends, the payment that pays a claim and then closes it), so rows are
# *registered* for a bump and flushed exactly once when the request finishes.
# ---------------------------------------------------------------------------
from flask import g  # noqa: E402


def mark(row):
    """Bump an already-persisted row's version -- at most once per request.

    The bump is applied immediately (so the response body a handler builds
    right afterwards carries the new version), but a per-request identity list
    keeps a second mark() on the same row from bumping it again.
    """
    if row is None:
        return row
    bumped = getattr(g, "_bumped_rows", None)
    if bumped is None:
        bumped = []
        g._bumped_rows = bumped
    if not any(r is row for r in bumped):
        bumped.append(row)
        touch(row)
    return row


def flush_touches():
    """Kept as the end-of-request hook; bumps are already applied by mark()."""
    g._bumped_rows = []
