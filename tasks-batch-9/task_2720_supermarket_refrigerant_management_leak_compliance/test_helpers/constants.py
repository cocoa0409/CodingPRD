"""
Pinned constants of the Supermarket Refrigerant Leak Compliance API.

Every value below is stated literally in the PRD. Tests import these instead of
re-typing magic numbers so that a drift in the contract shows up in one place.
"""

# ─── Logical clock (§2.4) ──────────────────────────────────────────────

#: The instant the service holds at start-up, before any clock call.
CLOCK_START = "2026-08-01T00:00:00Z"

#: The instant nearly every scenario pins as "now".
CLOCK_AUGUST_1 = "2026-08-01T00:00:00Z"

# ─── Envelope (§2.2) ──────────────────────────────────────────────────

API_REQUEST_ID_PREFIX = "req_"
RESPONSE_TYPE_OBJECT = "object"
RESPONSE_TYPE_ARRAY = "array"
RESPONSE_TYPE_ERROR = "error"

# ─── Pagination (§2.3) ────────────────────────────────────────────────

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ─── Applicability and leak-rate thresholds (§3.1) ────────────────────

#: A system is REGULATED once its nameplate charge reaches this mass.
REGULATED_FULL_CHARGE_LBS = 50.0

THRESHOLD_PCT_COMMERCIAL_REFRIGERATION = 20.0
THRESHOLD_PCT_INDUSTRIAL_PROCESS = 30.0
THRESHOLD_PCT_COMFORT_COOLING = 10.0

#: A system below this nameplate charge only needs a TYPE_I certified technician.
TYPE_I_MAX_FULL_CHARGE_LBS = 5.0

# ─── Cylinders and recovery equipment (§3.2) ──────────────────────────

#: DOT fill limit as a fraction of nominal water capacity.
FILL_LIMIT_FRACTION = 0.80

#: A recovery machine stays CERTIFIED for this many days after its check.
EQUIPMENT_VERIFICATION_VALID_DAYS = 365

# ─── Service records (§3.3, §3.8) ─────────────────────────────────────

MIN_DURATION_MINUTES = 1
MAX_DURATION_MINUTES = 1440

#: Decontamination buffer added after a machine's occupancy ends.
DECONTAMINATION_BUFFER_MINUTES = 60

#: Service records are retained for this many calendar years.
RETENTION_YEARS = 3

# ─── Leak rate (§3.4) ─────────────────────────────────────────────────

#: Trailing window of the ROLLING_AVERAGE variant, and the annualizing numerator.
ROLLING_WINDOW_DAYS = 365
ANNUALIZING_DAYS = 365

# ─── Leak events, repairs and extensions (§3.5, §3.6) ─────────────────

REPAIR_WINDOW_DAYS = 30
VERIFICATION_WINDOW_DAYS = 10
EXTENSION_DAY_CAP = 30
MIN_REQUESTED_DAYS = 1
MAX_REQUESTED_DAYS = 30
EXTENSION_DECISION_WINDOW_DAYS = 15
MIN_JUSTIFICATION_LENGTH = 10

#: A second failed verification mandates a retrofit due this many days out.
RETROFIT_MANDATE_DAYS = 90

#: Failed verifications needed before the retrofit mandate fires.
FAILED_VERIFICATION_MANDATE_COUNT = 2

# ─── Retrofit plans (§3.7) ────────────────────────────────────────────

PLAN_COST_MIN_EXCLUSIVE_USD = 0.00
PLAN_COST_MAX_USD = 5000000.00

COMPAT_WEIGHT_GWP = 0.45
COMPAT_WEIGHT_PRESSURE = 0.30
COMPAT_WEIGHT_FAMILY = 0.25

COMPAT_PRESSURE_SAME = 100.0
COMPAT_PRESSURE_DIFFERENT = 40.0
COMPAT_FAMILY_SAME_CLASS = 100.0
COMPAT_FAMILY_HFC_HFO = 70.0
COMPAT_FAMILY_OTHER = 50.0

COMPAT_SCORE_COMPATIBLE_MIN = 75.0
COMPAT_SCORE_CONDITIONAL_MIN = 50.0

#: A RETIRE plan bypasses chemistry scoring entirely.
RETIRE_PLAN_SCORE = 100.0
RETIRE_PLAN_GWP_REDUCTION_PCT = 0.0

# ─── Regulatory reports (§3.9) ────────────────────────────────────────

REPORT_DUE_DAYS_AFTER_PERIOD_END = 60
LATE_FILING_DAILY_RATE_USD = 165.00

SURCHARGE_RATE_UNDER_1000 = 0.05
SURCHARGE_RATE_UNDER_5000 = 0.10
SURCHARGE_RATE_5000_AND_OVER = 0.18
SURCHARGE_BRACKET_LOW_USD = 1000.00
SURCHARGE_BRACKET_HIGH_USD = 5000.00

# ─── Inspections (§3.9) ───────────────────────────────────────────────

INSPECTION_RESPONSE_DAYS = 30

CITATION_DAILY_RATE_MINOR_USD = 275.55
CITATION_DAILY_RATE_MODERATE_USD = 1250.00
CITATION_DAILY_RATE_MAJOR_USD = 4500.00

MULTIPLIER_COMPLIANT = 1.00
MULTIPLIER_AT_RISK = 1.25
MULTIPLIER_NON_COMPLIANT = 1.50

PENALTY_EXPOSURE_CAP_USD = 250000.00
