"""In-memory data store. The store starts EMPTY on every boot — no seeding."""
import uuid
from datetime import datetime, timezone, timedelta

# Logical clock (§2.5): starts at exactly 2026-05-01T00:00:00Z, never wall-clock.
_CLOCK_DEFAULT = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.seasons = {}               # id -> MeasurementSeason
        self.specs = {}                 # id -> MeasureSpecification
        self.members = {}               # id -> Member
        self.enrollment_segments = {}   # id -> MemberEnrollmentSegment
        self.providers = {}             # id -> Provider
        self.runs = {}                  # id -> MeasureRun
        self.population_entries = {}    # id -> PopulationEntry
        self.samples = {}               # id -> Sample
        self.chases = {}                # id -> ChartChase
        self.abstractions = {}          # id -> Abstraction
        self.over_reads = {}            # id -> OverReadReview
        self.batches = {}               # id -> SupplementalDataBatch
        self.records = {}               # id -> SupplementalRecord
        self.gap_items = {}             # id -> GapItem
        self.engagements = {}           # id -> AuditEngagement
        self.findings = {}              # id -> AuditFinding
        self.clock = _CLOCK_DEFAULT

    def reset_clock(self):
        self.clock = _CLOCK_DEFAULT


db = Store()


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """Logical-clock timestamp as ISO8601 UTC with 3 fractional digits."""
    return format_ts(db.clock)


def format_ts(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % ms


def parse_dt(value):
    """Parse an ISO8601 datetime (accepts trailing Z). Returns aware UTC datetime
    or None on failure."""
    if value is None or not isinstance(value, str):
        return None
    s = value.strip()
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def subtract_months(day, months):
    """Subtract `months` calendar months from a date (date part semantics)."""
    y = day.year
    m = day.month - months
    while m <= 0:
        m += 12
        y -= 1
    # clamp day-of-month
    if m == 12:
        next_month_first = datetime(y + 1, 1, 1).date()
    else:
        next_month_first = datetime(y, m + 1, 1).date()
    this_month_first = datetime(y, m, 1).date()
    last_day = (next_month_first - this_month_first).days
    d = min(day.day, last_day)
    return datetime(y, m, d).date()
