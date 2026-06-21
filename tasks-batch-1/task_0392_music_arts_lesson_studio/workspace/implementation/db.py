"""In-memory data store. Pure Python dicts keyed by id.

Storage starts EMPTY on every boot — no seeding, no preloaded entities.
The per-test-server harness reboots the process before each test, so all
state lives only in module-level dicts populated via the API surface.

Common fields (PRD §2.4): every resource carries
  id (UUID, no prefix), created_at, updated_at (ISO 8601 UTC, ms), version (int).
version starts at 1 and increments by 1 on every mutation.
"""
import uuid
from datetime import datetime, timezone

# One dict per entity type, keyed by id.
studios = {}
families = {}
students = {}
instructors = {}
rooms = {}
enrollments = {}
lesson_occurrences = {}
makeup_credits = {}
invoices = {}
payments = {}
recital_events = {}
recital_registrations = {}
instrument_rentals = {}
# Auxiliary store: practice logs (not a top-level API resource, but needed for
# recomputing student progress fields).
practice_logs = {}

# Monotonic sequence used purely as a tiebreaker for created_at ordering when
# two records share the same wall-clock millisecond. Ascending creation order.
_seq = [0]


def now_iso():
    n = datetime.now(timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"


def next_seq():
    _seq[0] += 1
    return _seq[0]


def new_id():
    return str(uuid.uuid4())


def init_record(fields):
    """Build a record with common fields stamped in."""
    ts = now_iso()
    rec = {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }
    rec.update(fields)
    return rec


def touch(rec):
    """Mark a record mutated: refresh updated_at, bump version (PRD §2.4/§2.9)."""
    rec["updated_at"] = now_iso()
    rec["version"] = rec["version"] + 1
