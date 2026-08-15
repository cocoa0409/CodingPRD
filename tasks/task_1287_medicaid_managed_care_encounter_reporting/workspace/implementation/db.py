"""In-memory data store. Starts empty on every boot — no seeding."""
import uuid
from datetime import datetime, timezone


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """ISO 8601 UTC timestamp with three fractional digits."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


class Store:
    def __init__(self):
        self.programs = {}
        self.members = {}
        self.providers = {}
        self.submitters = {}
        self.cycles = {}
        self.rate_schedules = {}
        self.encounters = {}
        self.encounter_lines = {}   # line_id -> line dict
        self.findings = {}          # finding_id -> finding dict
        self.batches = {}
        self.audits = {}
        self.penalties = {}
        self.statements = {}
        self.risk_snapshots = {}
        self.scorecards = {}
        # Logical clock: fixed startup default 2026-08-01T00:00:00Z
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
        # Raw lexical form of the clock reading (echoed verbatim in transmitted_at
        # and the clock capability's current_utc).
        self.clock_raw = "2026-08-01T00:00:00Z"


store = Store()
