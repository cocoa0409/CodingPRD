"""In-memory data store.

Pure Python dicts keyed by id.  Nothing is persisted anywhere; every fresh
process (and therefore every per-test-server reboot) starts completely empty.
No entity is ever seeded, preloaded or hardcoded at import or at startup.
"""
import uuid

from constants import DEFAULT_CLOCK_UTC
from timeutil import parse_datetime

COLLECTIONS = [
    "plans",
    "physicians",
    "families",
    "policies",
    "children",
    "memberships",
    "waitlist_entries",
    "grants",
    "bookings",
    "well_visits",
    "doses",
    "encounters",
    "service_lines",
    "invoices",
    "form_requests",
]


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = parse_datetime(DEFAULT_CLOCK_UTC)
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq

    # -- logical clock -------------------------------------------------------
    def now(self):
        """The current logical clock instant.  The host wall clock is never read."""
        return self.clock

    def today(self):
        return self.clock.date()


db = Store()


def new_id():
    return str(uuid.uuid4())


def new_row(collection, fields):
    """Create a row carrying the four common system-managed properties.

    A row minted inside the current request is registered as already-touched so
    that later writes in the same request (the sibling ladder, the invoice
    rebuild) leave it reading version 1 rather than bumping a brand-new row."""
    row = {
        "id": new_id(),
        "created_at": db.now(),
        "updated_at": db.now(),
        "version": 1,
        "_seq": db.next_seq(),
    }
    row.update(fields)
    collection[row["id"]] = row
    try:
        from flask import g, has_request_context

        if has_request_context():
            if not hasattr(g, "touched"):
                g.touched = set()
            g.touched.add(id(row))
    except Exception:  # pragma: no cover - defensive only
        pass
    return row


def by_seq(rows):
    """created_at ASC.  _seq is a hidden strictly-increasing creation counter that
    breaks ties when several rows are minted at the same logical clock instant."""
    return sorted(rows, key=lambda r: r["_seq"])


def touch(row, request_state):
    """Refresh updated_at and bump version, at most once per HTTP request."""
    key = id(row)
    if key in request_state:
        row["updated_at"] = db.now()
        return row
    request_state.add(key)
    row["updated_at"] = db.now()
    row["version"] += 1
    return row


def touch_force(row, request_state):
    """Unconditional version bump — used where the spec counts increments per
    contributing child row (policy version on each voided adjudicated line)."""
    request_state.add(id(row))
    row["updated_at"] = db.now()
    row["version"] += 1
    return row
