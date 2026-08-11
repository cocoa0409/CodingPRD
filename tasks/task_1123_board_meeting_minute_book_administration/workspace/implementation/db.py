"""In-memory data store plus the logical governance clock.

The store starts completely empty on every boot. No seeding of any kind:
every entity a test needs is built through the declared API surface.
"""

import itertools
import uuid
from datetime import datetime, timezone

# --- Logical governance clock ------------------------------------------------
# Startup default before any administrative call: 2026-05-01T00:00:00Z.
_CLOCK = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


def clock_now():
    return _CLOCK


def set_clock(dt):
    global _CLOCK
    _CLOCK = dt


# --- Entity stores ------------------------------------------------------------
# Plain dicts keyed by id; insertion-ordered. Values are dict rows.
corporations = {}
bylaws = {}
directors = {}
committees = {}
committee_memberships = {}
meetings = {}
meeting_notices = {}
agenda_items = {}
board_packages = {}
package_documents = {}
attendance_records = {}
resolutions = {}
vote_records = {}
conflict_disclosures = {}
minutes = {}
audit_requests = {}

# Monotonic insertion sequence, used as a deterministic tie-break after
# created_at when listing resources (multiple creates can share a clock value).
_seq_counter = itertools.count(1)


def next_seq():
    return next(_seq_counter)


def new_id():
    return str(uuid.uuid4())


def touch(row):
    """Refresh updated_at from the logical clock and bump the OCC version."""
    row["updated_at"] = clock_now()
    row["version"] = int(row.get("version", 0)) + 1


def new_row():
    """Common system fields for a freshly created row."""
    now = clock_now()
    return {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": next_seq(),
    }
