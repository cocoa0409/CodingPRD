"""Domain constants for the Studio Operations API test suite.

Values here are transcribed from the PRD's global specifications: the logical
clock default, the enumerations of §2.10, the rounding/precision rules of §2.8
and the fixed multipliers and ceilings named in §3.5, §3.7 and §3.8.
"""

# ─── Logical clock (PRD §2.4) ──────────────────────────────────────────────
# "Before any operator sets it, the clock reads 2026-08-01T00:00:00Z."
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

# ─── Roles (PRD §2.1) ──────────────────────────────────────────────────────
ROLE_STUDIO_ADMIN = "StudioAdmin"
ROLE_SAMPLE_COORDINATOR = "SampleCoordinator"
ROLE_PRODUCER = "Producer"
ROLE_PHOTOGRAPHER = "Photographer"
ROLE_RETOUCHER = "Retoucher"
ROLE_QC_REVIEWER = "QCReviewer"
ROLE_CONTENT_OPS = "ContentOps"

ALL_ROLES = [
    ROLE_STUDIO_ADMIN,
    ROLE_SAMPLE_COORDINATOR,
    ROLE_PRODUCER,
    ROLE_PHOTOGRAPHER,
    ROLE_RETOUCHER,
    ROLE_QC_REVIEWER,
    ROLE_CONTENT_OPS,
]

# ─── Enumerations (PRD §2.10) ──────────────────────────────────────────────
CATEGORIES = ["APPAREL_TOP", "APPAREL_BOTTOM", "FOOTWEAR", "ACCESSORY", "HOME"]
ANGLE_CODES = ["FRONT", "BACK", "SIDE", "FLAT", "DETAIL", "VIDEO_360"]
ASSET_KINDS = ["STILL_ANGLE", "DETAIL", "ON_MODEL", "VIDEO"]
STATION_TYPES = ["MODEL", "MANNEQUIN", "STILL_LIFE"]
TALENT_TYPES = ["MODEL", "STYLIST", "PHOTOGRAPHER", "RETOUCHER"]
PROVIDER_KINDS = ["IN_HOUSE", "OUTSOURCED"]
USAGE_SCOPES = ["ECOM_ONLY", "ECOM_PLUS_SOCIAL", "FULL_BUYOUT"]
TERRITORIES = ["US", "GLOBAL"]
PRIORITY_TIERS = ["A", "B", "C"]

# ─── State vocabularies ────────────────────────────────────────────────────
CONTENT_STATES = [
    "NOT_STARTED", "SAMPLE_READY", "SCHEDULED", "SHOT",
    "IN_POST", "DELIVERED", "BLOCKED",
]
CUSTODY_STATES = [
    "EXPECTED", "RECEIVED", "IN_STUDIO", "ON_SET",
    "RETURN_PENDING", "RETURNED", "LOST",
]
MATCH_STATES = ["UNMATCHED", "MISMATCH_HOLD", "MATCHED"]
RELEASE_STATES = ["PENDING", "SIGNED", "EXPIRED"]
SESSION_STATES = ["BOOKED", "LOCKED", "SHOOTING", "WRAPPED", "CANCELLED"]
BOOKING_STATES = ["HELD", "CONFIRMED", "RELEASED", "CANCELLED"]
ITEM_STATES = ["PLANNED", "ASSIGNED", "CAPTURED", "BLOCKED", "WAIVED"]
ASSET_STATES = [
    "INGESTED", "IN_RETOUCH", "QC_PENDING",
    "APPROVED", "REJECTED", "DELIVERED",
]
TASK_STATES = ["QUEUED", "IN_PROGRESS", "SUBMITTED", "REWORK", "APPROVED", "ABANDONED"]
SLA_STATES = ["IN_SLA", "AT_RISK", "BREACHED"]
COLOR_CHECK_STATES = ["NOT_MEASURED", "PASS", "FAIL"]

# ─── Fixed multipliers and ceilings ────────────────────────────────────────
# "the overtime leg is hourly_rate_cents multiplied by one and a half" (§3.5)
OVERTIME_MULTIPLIER = 1.5
# "counting at most two loops" (§3.8)
MAX_REWORK = 2
# "the studio halves it and rounds up to a whole hour" for tier A (§3.8)
RUSH_SLA_FACTOR = 0.5
# "strictly greater than three quarters of a delta-E unit" (§3.7)
COLOR_CONSISTENCY_DRIFT_MAX = 0.75
# "once late_return_count reaches 3 strikes" (§3.3)
VENDOR_HOLD_STRIKES = 3
# "strictly greater than four fifths of that sla_hours" (§3.8)
AT_RISK_SLA_FRACTION = 0.8

# ─── Pagination (PRD §2.3) ─────────────────────────────────────────────────
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ─── Defaults declared in §3.1 / §3.2 / §3.4 / §3.6 ────────────────────────
DEFAULT_SAMPLE_SLA_DAYS = 14
DEFAULT_BUFFER_MINUTES = 0
DEFAULT_MAX_CONCURRENT_SESSIONS = 1
DEFAULT_MINIMUM_CALL_HOURS = 4
DEFAULT_MAX_DAILY_MINUTES = 480
DEFAULT_CAPACITY_ASSETS_PER_DAY = 40
DEFAULT_PRIORITY_TIER = "C"
DEFAULT_COLOR_CHART_CODE = "XRITE_CC24"
DEFAULT_COLOR_TOLERANCE_DELTA_E = 2.00
DEFAULT_STYLE_QUOTE_CENTS = 0

# ─── Precision tolerances used by assertions ───────────────────────────────
CENT_TOLERANCE = 0
DECIMAL_TOLERANCE = 0.01

# A far-future calibration instant, used whenever a test needs a station whose
# colour calibration is unambiguously current under the default clock.
CALIBRATED_FAR_FUTURE = "2026-12-31T00:00:00Z"
