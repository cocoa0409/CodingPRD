"""In-memory data store, identifier minting, timestamps and the logical clock.

Storage is process-local only: every ``start.sh`` invocation begins with a
completely empty store.  Nothing is seeded, preloaded or hardcoded here.
"""

import itertools
import random
import string
import uuid
from datetime import datetime, timedelta, timezone

from flask import g

# --------------------------------------------------------------------------
# The logical production clock (PRD 2.5).  Reads exactly 2026-08-01T00:00:00Z
# until an operator moves it; never falls back to wall-clock time.
# --------------------------------------------------------------------------
CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_clock = {"now": CLOCK_DEFAULT}


def clock_now():
    return _clock["now"]


def clock_set(instant):
    _clock["now"] = instant


# --------------------------------------------------------------------------
# Collections
# --------------------------------------------------------------------------
COLLECTIONS = (
    "projects",
    "budget_lines",
    "deliverables",
    "deliverable_versions",
    "change_orders",
    "talent_engagements",
    "locations",
    "shoot_days",
    "compliance_certs",
    "crew_members",
    "crew_bookings",
    "equipment_reservations",
)

db = {name: {} for name in COLLECTIONS}
# Append-only ledger of client review verdicts; consumed_review_rounds counts
# the REQUEST_CHANGES entries recorded against a deliverable's cuts.
db["review_decisions"] = []

_seq = itertools.count(1)


def next_seq():
    return next(_seq)


def new_id():
    return str(uuid.uuid4())


def request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def iso(instant):
    """ISO 8601 UTC with exactly three fractional digits."""
    if instant is None:
        return None
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=timezone.utc)
    instant = instant.astimezone(timezone.utc)
    return instant.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (instant.microsecond // 1000)


def real_now():
    return datetime.now(timezone.utc)


def parse_instant(raw):
    """Parse an ISO 8601 instant; returns None when unparseable."""
    if not isinstance(raw, str):
        return None
    text = raw.strip()
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


def add_days(instant, days):
    return instant + timedelta(days=days)


# --------------------------------------------------------------------------
# Common system-managed fields (PRD 2.4)
# --------------------------------------------------------------------------
def new_row(**fields):
    stamp = real_now()
    row = {
        "id": new_id(),
        "created_at": iso(stamp),
        "updated_at": iso(stamp),
        "version": 1,
        "_seq": next_seq(),
        "_created": stamp,
    }
    row.update(fields)
    return row


def touch(row):
    """Record a mutation: bump ``version`` and refresh ``updated_at``.

    Idempotent within one request so that a transition plus the ledger
    movement it causes advance a row's version exactly once.
    """
    if row is None:
        return
    try:
        seen = g._touched_rows
    except (AttributeError, RuntimeError):
        seen = None
    if seen is None:
        seen = set()
        try:
            g._touched_rows = seen
        except RuntimeError:
            pass
    if row["id"] in seen:
        return
    seen.add(row["id"])
    row["version"] += 1
    row["updated_at"] = iso(real_now())


def by_seq(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
