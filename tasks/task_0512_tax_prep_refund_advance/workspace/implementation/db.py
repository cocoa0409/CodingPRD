"""In-memory data store (PRD §2.4, §3.9).

All state lives in module-level dicts keyed by id; NOTHING is seeded at startup.
Every entity is created by a caller through a declared endpoint. The logical
clock starts at exactly 2026-05-01T00:00:00Z on each fresh boot and never falls
back to wall-clock time until set via /_clock/set_current_utc (PRD §3.9)."""
import uuid
from datetime import datetime, timezone

# ---- Logical clock default (PRD §3.9) --------------------------------------
CLOCK_START = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.offices = {}
        self.credentials = {}
        self.preparers = {}
        self.clients = {}
        self.appointments = {}
        self.returns = {}
        self.documents = {}
        self.fee_lines = {}
        self.audit_protections = {}
        self.efile_submissions = {}
        self.refund_transfers = {}
        self.refund_advances = {}
        # logical clock (a tz-aware datetime)
        self.clock = CLOCK_START
        # monotonic sequence so created_at ties have a deterministic ordering
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def new_id():
    return str(uuid.uuid4())


def clock_iso():
    dt = db.clock
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def created_ts():
    """Timestamp string based on the logical clock for created_at/updated_at."""
    return clock_iso()
