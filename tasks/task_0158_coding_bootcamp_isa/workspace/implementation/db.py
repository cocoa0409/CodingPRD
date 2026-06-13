"""In-memory data store.

Every collection is a plain dict keyed by the entity id (a server-minted UUID
string with no type prefix — PRD §2.4). The store starts EMPTY on every boot and
is NEVER seeded, preloaded, or hardcoded with entities. Each fresh process under
`--isolation per-test-server` wipes all state.
"""
import uuid
from datetime import datetime, timezone

from response import now_iso


class Store:
    def __init__(self):
        # one dict per entity, keyed by id
        self.cohorts = {}
        self.applicants = {}
        self.enrollments = {}
        self.isa_contracts = {}
        self.scholarships = {}
        self.deposits = {}
        self.income_reports = {}
        self.payments = {}
        self.deferment_requests = {}
        self.refund_requests = {}
        self.placement_outcomes = {}
        self.attendance_records = {}
        self.cirr_reports = {}

        # server-controlled logical clock (PRD §2.10); defaults to wall-clock UTC
        # but tests advance it deliberately via POST /_clock/set_current_utc.
        self.current_clock = datetime.now(timezone.utc)

        # monotonic sequence to break created_at ties deterministically
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def new_id():
    return str(uuid.uuid4())


def stamp_create(record, common_fields=True):
    """Populate id + created_at (+ updated_at/version for mutable resources)."""
    record["id"] = new_id()
    record["created_at"] = now_iso()
    record["_seq"] = db.next_seq()
    if common_fields:
        record["updated_at"] = record["created_at"]
        record["version"] = 1
    return record


def touch(record):
    """Refresh updated_at and bump version on any mutation (PRD §2.5)."""
    if "version" in record:
        record["updated_at"] = now_iso()
        record["version"] += 1


def clock_iso():
    """Server logical-clock instant as an ISO 8601 UTC string with ms precision.

    Used for time-gated domain-event timestamps (enrolled_at, requested_at,
    admitted_at) so tests can drive the cooling-off window via the clock (PRD §2.10).
    """
    dt = db.current_clock
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
