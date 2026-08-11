"""In-memory data store. Starts empty on every boot — no seeding."""

import threading
import uuid
from datetime import datetime, timezone


_lock = threading.Lock()

# Logical clock: startup default exactly 2026-05-01T00:00:00Z (PRD §2.5),
# rendered with three fractional digits per PRD §2.4's created_at/updated_at
# contract ("an ISO 8601 UTC timestamp with three fractional digits").
_DEFAULT_CLOCK = "2026-05-01T00:00:00.000Z"
_current_utc = _DEFAULT_CLOCK


def set_current_utc(dt: datetime) -> None:
    global _current_utc
    _current_utc = format_iso(dt)


def get_current_utc() -> str:
    return _current_utc


def now_dt() -> datetime:
    return parse_iso(_current_utc)


def now_iso() -> str:
    return _current_utc


def format_iso(dt: datetime) -> str:
    """ISO 8601 UTC with three fractional digits, 'Z' suffix."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % ms


def parse_iso(s):
    """Parse ISO8601 datetime. Accepts 'Z' suffix. Returns aware UTC datetime."""
    if not isinstance(s, str):
        raise ValueError("not a datetime string")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def new_id() -> str:
    return str(uuid.uuid4())


class Store:
    """All entity tables keyed by id. Fresh per process."""

    def __init__(self):
        self.properties = {}
        self.units = {}
        self.occupancy_standards = {}
        self.ami_limits = {}
        self.campaigns = {}
        self.applicants = {}
        self.applications = {}
        self.preference_claims = {}
        self.income_certifications = {}
        self.lottery_runs = {}
        self.waitlist_entries = {}
        self.unit_offers = {}
        self.purge_runs = {}
        self.compliance_reports = {}
        # Internal (never serialized): lottery-run id -> list of application
        # ids frozen at SEAL time (PRD §3.5: the snapshot is taken at the
        # exact sealing instant; EXECUTE draws one entry per snapshotted
        # application, even if more applications verify afterwards).
        self.lottery_snapshots = {}


store = Store()


def new_record():
    rid = new_id()
    ts = now_iso()
    return {"id": rid, "created_at": ts, "updated_at": ts, "version": 1}


def touch(rec):
    rec["updated_at"] = now_iso()
    rec["version"] = rec.get("version", 1) + 1
