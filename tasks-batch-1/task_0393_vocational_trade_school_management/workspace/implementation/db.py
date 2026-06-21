"""In-memory data store. Empty on every boot — no seeding."""
import uuid
from datetime import datetime, timezone


def now_ts():
    """ISO 8601 UTC, three fractional digits, 'Z' suffix."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def new_id():
    return str(uuid.uuid4())


class Store:
    """Holds one dict per entity collection, plus the singleton clock."""

    def __init__(self):
        # Each collection: id -> entity dict
        self.programs = {}
        self.cohorts = {}
        self.students = {}
        self.externship_sites = {}
        self.enrollment_agreements = {}
        self.attendance_entries = {}
        self.sap_standings = {}
        self.aid_disbursements = {}
        self.refund_cases = {}
        self.externship_assignments = {}
        self.licensure_exam_attempts = {}
        self.placement_outcomes = {}
        # Monotonic sequence so creation order is stable even within the same
        # millisecond (created_at ties). Used for default ascending sort.
        self._seq = 0
        # SystemClock singleton — created lazily on first access.
        self._clock = None

    def next_seq(self):
        self._seq += 1
        return self._seq

    def clock(self):
        if self._clock is None:
            ts = now_ts()
            self._clock = {
                "id": new_id(),
                "current_term_index": 0,
                "created_at": ts,
                "updated_at": ts,
                "version": 1,
                "_seq": self.next_seq(),
            }
        return self._clock


# Module-level singleton store instance.
store = Store()
