import uuid
from datetime import datetime, timezone


# ---- Business constants (pinned by PRD / scaffold design docs) ----
OPTICAL_ZONE_MM = 1.0
DEPTH_PER_DIOPTER_UM = 12.0
FLAP_THICKNESS_UM = 110
MIN_RESIDUAL_BED_UM = 350
MAX_SAFE_K_DIOPTERS = 48.0
MAX_TREATABLE_DIOPTERS = 8.0
MIN_AGE_YEARS = 18
HEAL_SETTLE_DAYS = 30
GUARANTEE_FEE_CENTS = 25000
LIFETIME_WINDOW_DAYS = 36500

CLOCK_DEFAULT = "2026-05-01T00:00:00Z"


class Store:
    """In-memory store. Fresh on every process boot. No seeding."""

    def __init__(self):
        self.packages = {}
        self.suites = {}
        self.surgeons = {}
        self.optometrists = {}
        self.patients = {}
        self.screenings = {}
        self.cases = {}
        self.financing = {}
        self.consents = {}
        self.enhancements = {}
        self.bookings = {}
        self.refunds = {}
        # logical clock
        self._clock = parse_dt(CLOCK_DEFAULT)

    # ---- clock ----
    def now(self):
        return self._clock

    def set_clock(self, dt):
        self._clock = dt


def new_id():
    return str(uuid.uuid4())


def parse_dt(s):
    """Parse ISO 8601 into a timezone-aware UTC datetime."""
    if not isinstance(s, str):
        raise ValueError("datetime must be a string")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits, 'Z' suffix."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


db = Store()
