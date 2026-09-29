"""In-memory data store, the logical season clock, and row bookkeeping.

The store is empty on every boot: no entity is seeded.  Every row any test
needs is created through the declared API surface.
"""

import itertools
import uuid
from datetime import datetime, timedelta, timezone

from flask import g

from errors import ApiError

# ---------------------------------------------------------------- constants
MIN_REVIEWS_TO_SCREEN = 2
MIN_SCORECARDS_PER_ENTRY = 2
RANK_LIST_MAX_MULTIPLE = 10
INVITATION_RESPONSE_WINDOW_HOURS = 120
WAVE_MIN_GAP_HOURS = 48
SOAP_OFFER_WINDOW_HOURS = 4

DEFAULT_CLOCK_UTC = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
CERT_DEADLINE_UTC = datetime(2027, 2, 25, 21, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "programs",
    "applicants",
    "applications",
    "faculty_members",
    "application_reviews",
    "interview_waves",
    "interview_slots",
    "interview_invitations",
    "interview_assignments",
    "score_cards",
    "rank_lists",
    "rank_list_entries",
    "committee_votes",
    "match_results",
    "soap_offers",
    "contracts",
    "credential_items",
    "communication_logs",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = DEFAULT_CLOCK_UTC
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


db = Store()


# ---------------------------------------------------------------- time utils
def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year,
        dt.month,
        dt.day,
        dt.hour,
        dt.minute,
        dt.second,
        dt.microsecond // 1000,
    )


def parse_iso(value):
    """Parse a client supplied instant.  Returns None when unparseable."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def now():
    """The logical current UTC instant."""
    return db.clock


def now_iso():
    return iso(db.clock)


def dt_of(row, field):
    """Parse a stored ISO instant back into a datetime (or None)."""
    return parse_iso(row.get(field))


def hours(count):
    return timedelta(hours=count)


# ---------------------------------------------------------------- row utils
def _touched():
    store = getattr(g, "_touched_rows", None)
    if store is None:
        store = set()
        g._touched_rows = store
    return store


def new_row(**fields):
    stamp = now_iso()
    row = {
        "id": str(uuid.uuid4()),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
        "_seq": db.next_seq(),
    }
    row.update(fields)
    # A freshly created row is observable at version 1; nothing later in the
    # same request may bump it again.
    _touched().add(row["id"])
    return row


def touch(row):
    """Refresh updated_at and bump version — at most once per row per request."""
    if row is None:
        return
    seen = _touched()
    if row["id"] in seen:
        return
    seen.add(row["id"])
    row["updated_at"] = now_iso()
    row["version"] = row.get("version", 1) + 1


def ordered(rows):
    """Default list order: created_at ascending (insertion order breaks ties)."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


# ---------------------------------------------------------------- lookups
def find(collection, row_id):
    if not isinstance(row_id, str):
        return None
    return getattr(db, collection).get(row_id)


def must_find(collection, row_id):
    row = find(collection, row_id)
    if row is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND")
    return row


def rows(collection):
    return list(getattr(db, collection).values())


def insert(collection, row):
    getattr(db, collection)[row["id"]] = row
    return row
