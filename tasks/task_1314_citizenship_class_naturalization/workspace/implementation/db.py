"""In-memory data store and logical clock."""
import uuid
from datetime import datetime, timezone, timedelta


class Rec:
    """Generic record with attribute access."""

    def __init__(self, **kw):
        self.__dict__.update(kw)


DEFAULT_CLOCK_RAW = "2026-08-01T00:00:00Z"
DEFAULT_CLOCK_DT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.program = None            # single Program Rec or None
        self.applicants = {}
        self.screenings = {}
        self.sections = {}
        self.enrollments = {}
        self.attendance = {}
        self.volunteers = {}
        self.training = {}
        self.workshops = {}
        self.seats = {}
        self.packets = {}
        self.fee_waivers = {}
        self.cases = {}
        self.mocks = {}
        self.ceremonies = {}
        self.receipt_seq = 0
        self.insert_seq = 0
        self.clock_raw = DEFAULT_CLOCK_RAW
        self.clock_dt = DEFAULT_CLOCK_DT


db = Store()


def now_dt():
    return db.clock_dt


def now_raw():
    return db.clock_raw


def new_id():
    return str(uuid.uuid4())


def next_seq():
    db.insert_seq += 1
    return db.insert_seq


def new_receipt_number():
    db.receipt_seq += 1
    return "NRC-%06d" % db.receipt_seq


def parse_dt(value):
    """Parse an ISO-8601 string into an aware UTC datetime. Raises ValueError."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_dt(dt):
    """Format an aware datetime as ISO-8601 UTC with three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def add_months(dt, months):
    """Add calendar months to a datetime, clamping the day of month."""
    total = dt.month - 1 + months
    year = dt.year + total // 12
    month = total % 12 + 1
    if month == 12:
        next_first = datetime(year + 1, 1, 1)
    else:
        next_first = datetime(year, month + 1, 1)
    last_day = (next_first - datetime(year, month, 1)).days
    day = min(dt.day, last_day)
    return dt.replace(year=year, month=month, day=day)


# --- Program defaults (used until/unless a Program row overrides them) ---
PROGRAM_DEFAULTS = {
    "n400_fee_cents": 76000,
    "biometric_fee_cents": 8501,
    "translation_stipend_cents": 3001,
    "poverty_base_cents": 1565000,
    "poverty_per_additional_cents": 550000,
    "full_waiver_threshold_pct": 150,
    "partial_waiver_threshold_pct": 200,
    "attendance_complete_bp": 8000,
    "attendance_midterm_floor_bp": 5000,
    "readiness_certify_threshold": 70,
    "rfe_deadline_days": 84,
    "accreditation_valid_months": 24,
    "general_training_hours": 10,
    "legal_supervised_hours": 8,
    "renewal_training_hours": 4,
    "promotion_offer_hours": 72,
    "mock_buffer_minutes": 15,
    "mock_max_attempts": 3,
}


def prog_param(name):
    if db.program is not None:
        return getattr(db.program, name)
    return PROGRAM_DEFAULTS[name]


def stamp_new(rec):
    """Assign id/created_at/updated_at/version and insertion sequence."""
    rec.id = new_id()
    rec.created_at = now_dt()
    rec.updated_at = now_dt()
    rec.version = 1
    rec._seq = next_seq()


def stamp_new_appendonly(rec):
    """Append-only events carry only id and created_at."""
    rec.id = new_id()
    rec.created_at = now_dt()
    rec._seq = next_seq()


def bump(rec):
    """Version bump + updated_at refresh for a mutation."""
    rec.version += 1
    rec.updated_at = now_dt()
