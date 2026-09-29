"""In-memory store, logical clock, id/timestamp helpers and declared constants.

Storage is process-local only: plain Python dicts keyed by id.  Nothing is
written to disk, and every byte of state vanishes when the process exits.
The store starts completely empty on every boot -- no entity is ever seeded.
"""

import random
import string
import uuid
from datetime import datetime, timezone

# ---------------------------------------------------------------- constants
HOST_COUNTRY = "US"

RUBRIC_WEIGHT_ARTISTIC_MERIT = 35
RUBRIC_WEIGHT_FEASIBILITY = 27
RUBRIC_WEIGHT_COMMUNITY_FIT = 23
RUBRIC_WEIGHT_TECHNICAL_READINESS = 15
RUBRIC_SCORE_MIN = 0
RUBRIC_SCORE_MAX = 10

EXPERTISE_MATCH_MULTIPLIER = "1.00"
EXPERTISE_MISMATCH_MULTIPLIER = "0.90"

TRIM_MIN_PANELISTS = 4
MAX_REVISION_ROUNDS = 2

FEE_WAIVER_INCOME_CEILING_CENTS = 3500000

MIN_SESSION_WEEKS = 4
MAX_SESSION_WEEKS = 16
STIPEND_PERIOD_WEEKS = 2

WITHHOLDING_EXEMPT_THRESHOLD_CENTS = 60000
NRA_WITHHOLDING_RATE = "0.30"
TREATY_WITHHOLDING_RATE = "0.15"

VISA_LEAD_DAYS = 90
VISA_EARLIEST_ENTRY_LEAD_DAYS = 30
VISA_BACKLOG_DAYS_DEFAULT = 21
VISA_BACKLOG_DAYS_HIGH_VOLUME = 45
HIGH_VOLUME_VISA_COUNTRIES = ["IN", "CN", "NG", "BR"]
VISA_J1_MIN_SESSION_WEEKS = 9

STUDIO_TURNAROUND_DAYS = 2
VENTILATION_RANK = {"NONE": 0, "LOCAL": 1, "FUME_HOOD": 2}

OBLIGATION_BASE_OPEN_STUDIO = 1
OBLIGATION_BASE_EXHIBITION = 1
OBLIGATION_BASE_ARTIST_TALK = 1
OBLIGATION_WORKSHOP_WEEKS_PER_UNIT = 4

DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

# ---------------------------------------------------------------- enums
MEDIA_TYPES = ["IMAGE", "VIDEO", "AUDIO", "TEXT", "MODEL_3D"]
CAPABILITY_TAGS = ["WELDING", "KILN", "DARKROOM", "WET_LAB", "PRINT_PRESS", "CLEAN_ONLY"]
VENTILATION_CLASSES = ["NONE", "LOCAL", "FUME_HOOD"]
ACCESSIBILITY_FEATURES = ["STEP_FREE", "ROLL_IN_SHOWER", "VISUAL_ALARM", "GROUND_FLOOR"]
CYCLE_STATUSES = ["DRAFT", "OPEN", "SCREENING", "PANEL_REVIEW", "SLATE_LOCKED", "CLOSED"]
APPLICATION_STATUSES = [
    "DRAFT", "SUBMITTED", "REVISION_REQUESTED", "PANEL_REVIEW", "SCORED",
    "OFFERED", "WAITLISTED", "REJECTED", "ACCEPTED", "DECLINED",
]
FEE_STATUSES = ["PENDING", "PAID", "WAIVED"]
PANELIST_STATUSES = ["ACTIVE", "RECUSED_FOR_CYCLE"]
ASSIGNMENT_STATUSES = ["ASSIGNED", "SCORED", "CONFLICT_DECLARED", "VACATED"]
CONFLICT_TYPES = ["SAME_AFFILIATION", "PRIOR_MENTORSHIP", "FAMILIAL", "FINANCIAL"]
SEVERE_CONFLICT_TYPES = ["FAMILIAL", "FINANCIAL"]
RESIDENCY_STATUSES = ["SCHEDULED", "IN_RESIDENCE", "COMPLETED", "TERMINATED", "WITHDRAWN"]
COMPLIANCE_STATUSES = ["TRAINING_PENDING", "CLEARED", "SUSPENDED"]
STIPEND_BASES = ["PROVISIONAL", "FINAL_SETTLED"]
TAX_FORM_TYPES = ["W9", "1042S"]
STUDIO_STATUSES = ["AVAILABLE", "MAINTENANCE", "DECOMMISSIONED"]
STUDIO_ASSIGNMENT_STATUSES = ["ACTIVE", "RELEASED"]
SELECTION_MODES = ["EXPLICIT", "AUTO_SELECTED"]
HOUSING_UNIT_STATUSES = ["AVAILABLE", "MAINTENANCE"]
HOUSING_ASSIGNMENT_STATUSES = ["ACTIVE", "RELEASED"]
VISA_CASE_TYPES = ["J1_RESEARCH_SCHOLAR", "B1_SHORT_TERM"]
VISA_STATUSES = ["INITIATED", "DOCS_REQUESTED", "DOCS_SUBMITTED", "FILED", "APPROVED", "DENIED"]
DISBURSEMENT_STATUSES = ["SCHEDULED", "PAID", "VOIDED", "REVERSED"]
OBLIGATION_TYPES = ["OPEN_STUDIO", "EXHIBITION", "COMMUNITY_WORKSHOP", "ARTIST_TALK"]
OBLIGATION_STATUSES = ["PENDING", "SATISFIED", "WAIVED", "BREACHED"]

ROLE_NAMES = [
    "ProgramAdmin", "Applicant", "Panelist", "PanelChair",
    "FinanceOfficer", "VisaCoordinator", "FacilitiesManager", "Funder",
]

COLLECTION_NAMES = [
    "cycles", "disciplines", "applicants", "applications", "portfolio_items",
    "panelists", "panel_assignments", "residencies", "studios",
    "studio_assignments", "housing_units", "housing_assignments",
    "visa_cases", "disbursements", "obligations",
]


def parse_instant(text):
    """Parse an ISO 8601 instant into an aware UTC datetime, or return None."""
    if not isinstance(text, str) or not text.strip():
        return None
    raw = text.strip()
    if raw.endswith("z") or raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso_ms(dt):
    """Render an aware datetime as ISO 8601 UTC with exactly 3 fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return "%s.%03dZ" % (dt.strftime("%Y-%m-%dT%H:%M:%S"), dt.microsecond // 1000)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTION_NAMES:
            setattr(self, name, {})
        self.clock = parse_instant(DEFAULT_CLOCK_UTC)
        self._seq = 0
        self._last_wall = None

    def next_seq(self):
        self._seq += 1
        return self._seq

    def wall_now(self):
        """Monotonically non-decreasing wall clock, used only for row metadata."""
        now = datetime.now(timezone.utc)
        if self._last_wall is not None and now <= self._last_wall:
            now = self._last_wall
        self._last_wall = now
        return now

    def wall_now_iso(self):
        return iso_ms(self.wall_now())

    # -- logical clock ---------------------------------------------------
    def now(self):
        """The logical clock instant. Business logic NEVER reads the wall clock."""
        return self.clock

    def today(self):
        """The UTC calendar date of the logical clock."""
        return self.clock.date()


store = Store()

_ID_ALPHABET = string.ascii_uppercase + string.digits


def new_id():
    return str(uuid.uuid4())


def new_request_id():
    return "req_" + "".join(random.choice(_ID_ALPHABET) for _ in range(20))


def create_row(collection, data, versioned=True):
    """Insert a new row, assigning id/created_at (and updated_at/version)."""
    row = dict(data)
    row["id"] = new_id()
    row["created_at"] = store.wall_now_iso()
    row["_seq"] = store.next_seq()
    if versioned:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    collection[row["id"]] = row
    return row


def touch(row):
    """Advance a row's updated_at and version by exactly one step."""
    if row is None:
        return None
    row["updated_at"] = store.wall_now_iso()
    if "version" in row:
        row["version"] = row["version"] + 1
    return row


def by_seq(rows):
    """Ascending creation order -- oldest row first."""
    return sorted(rows, key=lambda r: r["_seq"])
