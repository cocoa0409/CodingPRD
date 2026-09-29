"""Domain constants for the Event Security & Crowd Management API.

Every value here is declared by the PRD contract under test. Tests import
these rather than repeating magic numbers so that a threshold change is a
one-line edit.
"""

API_PREFIX = "/event-security"
CLOCK_PATH = "/_clock/set_current_utc"

# ─── Logical clock ────────────────────────────────────
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

# ─── Zone safe occupancy ──────────────────────────────
MIN_SQM_PER_PERSON = 0.65
PERSONS_PER_EXIT_UNIT = 100

# ─── Composite threat score ───────────────────────────
THREAT_POINTS = {"LOW": 0, "GUARDED": 8, "ELEVATED": 18, "HIGH": 30, "SEVERE": 44}
PROTEST_POINTS = {"NONE": 0, "POSSIBLE": 6, "LIKELY": 15}
PROFILE_POINTS = {"SEATED": 0, "FAMILY": 2, "GENERAL_ADMISSION": 10, "MOSH_PIT": 20}
LAYOUT_POINTS_PER_LEVEL = 3
ALCOHOL_POINTS = 7
VIP_POINTS = 5
LOAD_POINTS_AT_FULL = 30
DENSITY_PRESSURE_CAP = 25
HISTORY_MULTIPLIER_STEP = 0.04
CROWD_FACTOR_CAP = 1.35
SCORE_CEILING = 100

# ─── Risk tier ladder (inclusive lower bounds) ────────
TIER_T2_MIN = 30
TIER_T3_MIN = 50
TIER_T4_MIN = 70

# ─── Required staff matrix ────────────────────────────
GUARDS_PER_1000_BY_TIER = {"T1": 1.5, "T2": 2.5, "T3": 4.0, "T4": 6.0}
PERIMETER_SHARE = 0.30
INGRESS_SHARE = 0.25
FLOOR_SHARE = 0.35
EXIT_SHARE = 0.10
EXIT_GUARDS_PER_DOOR = 1

# ─── Supervisor span of control ───────────────────────
SPAN_OF_CONTROL = 10
SUPERVISOR_SPAN_OF_CONTROL = 5

# ─── Screening lane requirement ───────────────────────
SURGE_FRACTION = 0.55
SURGE_WINDOW_MIN = 45
MAX_QUEUE_WAIT_MIN = 20
BAG_CARRY_RATE = 0.60
BAG_CHECK_RATE_PPH = 180
NO_BAG_RATE_PPH = 420

# ─── Minimum staffing cost floor ──────────────────────
FLOOR_HOURS_PER_STAFF = 4
MIN_FLOOR_HOURLY_CENTS = 1800

# ─── Assignment cost ──────────────────────────────────
OT_THRESHOLD_HOURS = 8
OT_MULTIPLIER = 1.5
NIGHT_DIFFERENTIAL_CENTS_PER_HOUR = 150
NIGHT_START_HOUR = 22
NIGHT_END_HOUR = 6
SUBCONTRACT_ADMIN_FEE_CENTS = 1200

# ─── Plan coverage / readiness ladder ─────────────────
COVERAGE_READY_MIN = 1.00
COVERAGE_AT_RISK_MIN = 0.90

# ─── Gate posture ─────────────────────────────────────
DENSITY_LOOKBACK_MIN = 15

# ─── Crowd density classification ─────────────────────
ROLLING_WINDOW_SIZE = 3
LEVEL_AMBER_MIN = 2.000
LEVEL_RED_MIN = 3.200
LEVEL_CRITICAL_MIN = 4.000

# ─── Screening lane throughput ────────────────────────
PROHIBITED_ITEM_HIT_RATE = 0.04
SECONDARY_SCREEN_COST_FACTOR = 2.5

# ─── Incident response SLA budgets (minutes) ──────────
SLA_MINUTES_BY_SEVERITY = {"MINOR": 15, "MODERATE": 10, "SEVERE": 5, "CRITICAL": 3}

# ─── Credential floors ────────────────────────────────
SUPERVISOR_MIN_CREDENTIAL_LEVEL = 3

# ─── Doors-open lead window (minutes before doors_open_at) ──
DOORS_OPEN_LEAD_MIN = 60

# ─── Density reading admissible window (minutes) ──────
DENSITY_WINDOW_BEFORE_DOORS_MIN = 120
DENSITY_WINDOW_AFTER_END_MIN = 120

# ─── Decimal tolerance for money / ratio comparisons ──
MONEY_TOLERANCE = 0.01
