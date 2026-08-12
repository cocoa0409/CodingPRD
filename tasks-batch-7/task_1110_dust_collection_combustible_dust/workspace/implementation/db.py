"""In-memory data store. Starts completely empty on every boot.

No seeding, no preload, no file persistence. All state lives in module-level
dicts of this process and dies with it.
"""
import uuid
from datetime import datetime, timezone


# ----------------------------------------------------------------------------
# Logical clock
# ----------------------------------------------------------------------------
class LogicalClock:
    def __init__(self):
        self._now = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)

    def now(self):
        return self._now

    def set(self, dt):
        self._now = dt


clock = LogicalClock()


def now_dt():
    return clock.now()


def iso(dt):
    """Format a datetime as ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    s = dt.strftime("%Y-%m-%dT%H:%M:%S")
    ms = dt.microsecond // 1000
    return f"{s}.{ms:03d}Z"


def now_iso():
    return iso(now_dt())


def new_id():
    return str(uuid.uuid4())


# ----------------------------------------------------------------------------
# Stores — keyed by id, empty at boot
# ----------------------------------------------------------------------------
sites = {}                 # id -> Site dict
dust_samples = {}          # id -> DustSample dict
collectors = {}            # id -> Collector dict
dhas = {}                  # id -> DHA dict
dha_samples = {}           # dha_id -> list of sample_ids (linked)
housekeeping_programs = {}  # id -> HousekeepingProgram dict
housekeeping_audits = {}   # id -> HousekeepingAudit dict
hot_work_permits = {}      # id -> HotWorkPermit dict
inspections = {}           # id -> Inspection dict
inspection_findings = {}   # id -> InspectionFinding dict
retrofit_projects = {}     # id -> RetrofitProject dict
retrofit_line_items = {}   # id -> RetrofitLineItem dict
incidents = {}             # id -> Incident dict
capa_actions = {}          # id -> CAPAAction dict
dp_readings = {}           # collector_id -> list of {dp_inwc, created_at, seq}

_reading_seq = [0]


def next_reading_seq():
    _reading_seq[0] += 1
    return _reading_seq[0]
