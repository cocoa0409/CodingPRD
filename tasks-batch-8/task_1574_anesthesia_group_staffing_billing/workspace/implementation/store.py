"""In-memory data store + logical clock. No persistence, no seeding."""
import uuid
from datetime import datetime, timezone


def now_iso():
    """Wall-clock timestamp for created_at/updated_at: ISO 8601 UTC, 3 fractional digits."""
    n = datetime.now(timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"


def fmt_iso(dt):
    """Format an aware datetime as ISO 8601 UTC with 3 fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


class Store:
    def __init__(self):
        self.sites = {}
        self.providers = {}
        self.rosters = {}
        self.cases = {}
        self.assignments = {}
        self.call_assignments = {}
        self.attestations = {}
        self.claims = {}
        self.fee_schedules = {}
        self.agreements = {}
        self.stipend_entries = {}
        self.audits = {}
        self.findings = {}
        # Logical clock: exact startup default per PRD 2.4; never wall-clock fallback.
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
        self.seq = 0

    def next_seq(self):
        self.seq += 1
        return self.seq

    def new_record(self, **fields):
        ts = now_iso()
        rec = {"id": str(uuid.uuid4()), "created_at": ts, "updated_at": ts, "version": 1}
        rec.update(fields)
        rec["_seq"] = self.next_seq()
        return rec

    def bump(self, rec):
        rec["version"] += 1
        rec["updated_at"] = now_iso()

    # ---- logical clock helpers ----
    def clock_date_str(self):
        return self.clock.astimezone(timezone.utc).strftime("%Y-%m-%d")

    def clock_minute(self):
        c = self.clock.astimezone(timezone.utc)
        return c.hour * 60 + c.minute


db = Store()
