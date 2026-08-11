"""In-memory data store, deterministic id minting, and the PRD's logical clock.

NOTHING is seeded here.  Every collection starts empty on every boot; tests
build all preconditions through the declared API surface.
"""
import datetime
import threading

# PRD 2.4: "Before any caller sets it, the logical clock reads exactly
# 2026-05-01T00:00:00Z."  The host wall clock is never consulted.
CLOCK_DEFAULT_UTC = datetime.datetime(2026, 5, 1, 0, 0, 0, tzinfo=datetime.timezone.utc)

# --------------------------------------------------------------------------
# Global constants (scaffold global_constants; every value is quoted verbatim)
# --------------------------------------------------------------------------
DOMESTIC_COUNTRY_CODE = "US"

PRESORT_5D_MIN_PIECES = 12
PRESORT_AADC_MIN_PIECES = 9
PRESORT_MIXED_AADC_MIN_PIECES = 6

PRESORT_5D_RATE_CENTS = "23.9"
PRESORT_AADC_RATE_CENTS = "28.1"
PRESORT_MIXED_AADC_RATE_CENTS = "31.8"
MARKETING_NO_PRESORT_RATE_CENTS = "51.0"
MARKETING_RETAIL_TIER_RATE_CENTS = "51.6"
FIRST_CLASS_AUTOMATION_MIN_PIECES = 6
FIRST_CLASS_AUTOMATION_RATE_CENTS = "58.0"
FIRST_CLASS_RETAIL_RATE_CENTS = "73.0"
EDDM_SATURATION_RATE_CENTS = "22.3"
EDDM_HDPLUS_RATE_CENTS = "25.6"

EDDM_MIN_PIECES_PER_JOB = 5
EDDM_MAX_PIECES_PER_JOB_DAY = 50
EDDM_HDPLUS_MIN_RESIDENTIAL_PIECES = 3

HANDLING_BASE_CENTS = 250
HANDLING_PCT = "0.08"
VOLUME_CREDIT_PCT = "0.05"
VOLUME_CREDIT_MIN_PIECES = 6

RUN_SETUP_MINUTES = 12
SPLIT_RUN_SETUP_PASSES = 2
SINGLE_PASS_SETUP_PASSES = 1
DEFAULT_MACHINE_DAILY_CAPACITY_MINUTES = 480
INK_SAFETY_RESERVE_UL = 500
MAX_TEMPLATE_CHARACTER_COUNT = 2000
MIN_TEMPLATE_CHARACTER_COUNT = 1

RETURN_FEE_CENTS_FIRST_CLASS = 0
RETURN_FEE_CENTS_MARKETING_MAIL = 89
REPRINT_CAP_PER_CAMPAIGN_PER_RECORD = 1

PROOF_APPROVAL_VALID_DAYS = 30

TRANSIT_DAYS_FIRST_CLASS = 3
TRANSIT_DAYS_MARKETING_MAIL = 10
TRANSIT_DAYS_EDDM = 12
PRODUCTION_LEAD_DAYS = 3
BLACKOUT_SHIFT_MAX_DAYS = 5
DRIP_MIN_GAP_DAYS = 2
DRIP_MAX_STEPS = 8

MAX_RECORDS_PER_LIST = 100000
MIN_JOB_PIECE_COUNT = 1

TRANSIT_DAYS = {
    "FIRST_CLASS": TRANSIT_DAYS_FIRST_CLASS,
    "MARKETING_MAIL": TRANSIT_DAYS_MARKETING_MAIL,
    "EDDM": TRANSIT_DAYS_EDDM,
}

ROLES = (
    "PlatformAdmin",
    "AccountOwner",
    "CampaignManager",
    "ListOperator",
    "ProductionOperator",
    "ComplianceOfficer",
)


class Store(object):
    """Plain in-memory dictionaries.  No persistence of any kind."""

    def __init__(self):
        self.lock = threading.RLock()
        self.reset()

    def reset(self):
        self.accounts = {}
        self.campaigns = {}
        self.handwriting_styles = {}
        self.templates = {}
        self.mailing_lists = {}
        self.list_records = {}
        self.mail_jobs = {}
        self.eddm_routes = {}
        self.proofs = {}
        self.machines = {}
        self.ink_lots = {}
        self.production_runs = {}
        self.drip_schedules = {}
        self.drip_steps = {}
        self.ledger_entries = {}
        self.return_events = {}
        self.reprint_requests = {}
        self.blackout_dates = {}
        self.clock = CLOCK_DEFAULT_UTC
        self._id_seq = 0
        self._req_seq = 0

    # -- deterministic, monotonically increasing UUID-shaped ids ------------
    # The logical clock is coarse, so many rows share a created_at and list
    # order then falls back to the id tie-break.  Minting ids whose ascending
    # order equals creation order makes that tie-break deterministic.
    def mint_id(self):
        self._id_seq += 1
        n = self._id_seq
        return "%08x-%04x-4000-8000-%012x" % (n & 0xFFFFFFFF, (n >> 32) & 0xFFFF, n)

    def next_request_id(self):
        self._req_seq += 1
        return self._req_seq


db = Store()


# --------------------------------------------------------------------------
# The one and only renderer for server-written instants.
# PRD 2.4: ISO 8601 UTC with three fractional digits.
# --------------------------------------------------------------------------
def render_instant(dt):
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(datetime.timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def render_date(d):
    if d is None:
        return None
    if isinstance(d, str):
        return d
    return "%04d-%02d-%02d" % (d.year, d.month, d.day)


def now():
    """The logical clock's current instant."""
    return db.clock


def today():
    """The calendar-date part of the logical clock's current instant."""
    return db.clock.date()


def parse_instant(value):
    """Parse an ISO 8601 datetime string; returns None when unparseable."""
    if not isinstance(value, str) or not value:
        return None
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(datetime.timezone.utc)


def parse_date(value):
    """Parse a YYYY-MM-DD calendar date; returns None when unparseable."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if len(text) != 10:
        return None
    try:
        return datetime.date.fromisoformat(text)
    except ValueError:
        return None
