"""Domain thresholds and rate tables taken from the PRD's calculations (§2.9, §3)."""

CLOCK_STARTUP_ISO = "2026-08-01T00:00:00Z"

# --- §3.2 credential compliance -------------------------------------------
ROLE_MIN_CREDENTIAL_LEVEL = {"DIRECTOR": 4, "LEAD_TEACHER": 3, "ASSISTANT": 1}
CREDENTIAL_COMPLIANCE_CAP_PCT = 100.00

# --- §3.4 observation ------------------------------------------------------
SUBSCALE_CODES = [
    "SPACE_FURNISHINGS",
    "PERSONAL_CARE",
    "LANGUAGE_REASONING",
    "ACTIVITIES",
    "INTERACTION",
    "PROGRAM_STRUCTURE",
]
RELIABILITY_ADMISSIBLE_PCT = 83.33
ANCHOR_AGREEMENT_CERTIFY_MIN = 85.00
RESCORE_LIMIT = 2
SCORE_MIN = 1.0
SCORE_MAX = 7.0
OBSERVER_COOLDOWN_HOURS = 48

# --- §3.5 tiering ----------------------------------------------------------
OBSERVATION_FRACTION_BANDS = [(6.00, 1.00), (5.00, 0.80), (4.00, 0.60), (3.00, 0.40)]
OBSERVATION_FRACTION_FLOOR = 0.20
CREDENTIAL_FRACTION_BANDS = [(95.00, 1.00), (85.00, 0.80), (70.00, 0.60), (55.00, 0.40)]
CREDENTIAL_FRACTION_FLOOR = 0.20
POINTS_TIER_CUTOFFS = [(85.00, 5), (70.00, 4), (55.00, 3), (40.00, 2)]
BLOCK_TIER_CEILING = {0: 1, 1: 2, 2: 4, 3: 5}
COMPLIANCE_FLOOR_BY_TIER = {1: 0.00, 2: 60.00, 3: 80.00, 4: 90.00, 5: 95.00}
VALIDITY_MONTHS_HIGH = 36
VALIDITY_MONTHS_LOW = 24
RERATING_WINDOW_LEAD_DAYS = 90

# --- §3.3 / §3.6 loop ceilings --------------------------------------------
SELF_ASSESSMENT_RETURN_LIMIT = 2
APPEAL_INFO_ROUND_LIMIT = 2
DISPUTE_TRIAGE_LIMIT = 3
PUBLICATION_QUIET_PERIOD_DAYS = 10
APPEAL_FILING_WINDOW_DAYS = 30

# --- §3.7 subsidy ----------------------------------------------------------
BASE_DAILY_RATE_CENTS = {"INFANT": 4500, "TODDLER": 3800, "PRESCHOOL": 3200}
TIER_MULTIPLIER = {1: 1.00, 2: 1.05, 3: 1.15, 4: 1.30, 5: 1.50}
REGION_FACTOR = {"URBAN": 1.00, "RURAL": 1.08, "FRONTIER": 1.15}

# --- §3.8 grants -----------------------------------------------------------
CATEGORY_CEILING_SHARE = {"EQUIPMENT": 0.40, "PROF_DEV": 0.30, "FACILITY": 0.25, "ADMIN": 0.10}
CATEGORY_MATCH_RATE = {"EQUIPMENT": 0.90, "PROF_DEV": 1.00, "FACILITY": 0.75, "ADMIN": 0.50}
PROF_DEV_REQUIREMENT_SHARE = 0.25
PROF_DEV_PENALTY_SHARE = 0.50

# --- §3.9 coaching ---------------------------------------------------------
ADMIN_FEE_BANDS = [(50_000, 0.12), (200_000, 0.09)]
ADMIN_FEE_TOP_RATE = 0.06
HOURS_CEILING_BY_TIER = {1: 40.0, 2: 32.0, 3: 24.0, 4: 16.0, 5: 8.0}
SPEND_CEILING_BY_TIER = {1: 900_000, 2: 750_000, 3: 600_000, 4: 400_000, 5: 250_000}
STATE_BASE_FUNDING_BALANCE_CENTS = 500_000

# --- Pagination (§2.3) -----------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
