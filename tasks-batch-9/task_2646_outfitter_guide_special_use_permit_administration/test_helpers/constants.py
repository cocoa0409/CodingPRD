"""Domain thresholds and canonical test data values from the PRD."""

API_PREFIX = "/osup"

# The logical clock reads this instant before any repositioning.
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

# Canonical clock position used by most scenarios: a date inside the 2027
# planning year but before the season opens.
SCENARIO_CLOCK_UTC = "2027-01-05T00:00:00Z"

# --- Allocation and demand ---
CONSTRAINED_DEMAND_RATIO = 0.8          # available > 0 and ratio >= 0.8 is CONSTRAINED
DEMAND_RATIO_DECIMALS = 4
SCORE_DECIMALS = 2
COMPLETENESS_TARGET = 100.0             # a plan may only be submitted at exactly 100.0

# --- Guide client capacity ---
FIELD_ALLOWANCE = {"TRAINEE": 0, "ASSISTANT": 4, "LEAD": 8}
CERT_CAP = {"NONE": 0, "BASIC_FIRST_AID": 4, "WFR": 8, "WEMT": 12}
EXPERIENCE_SEASONS_PER_STEP = 3
EXPERIENCE_BONUS_CAP = 2
MAX_AUTHORIZED_GUIDES_PER_PERMIT = 8

# --- Permit terms ---
PERMIT_TERM_CLEAR_DAY_BUFFER = 14

# --- Insurance and bonding ---
DEFAULT_MIN_LIABILITY_COVERAGE_CENTS = 100_000_000
BOND_CENTS_PER_SERVICE_DAY = 5_000
BOND_FLOOR_CENTS = 250_000
BOND_CEILING_CENTS = 5_000_000

# --- Fees ---
DEDUCTION_CAP_RATE = 0.15
MINIMUM_FEE_CENTS = 30_000
GRADUATED_TIER_ONE_CEILING_CENTS = 2_500_000
GRADUATED_TIER_TWO_CEILING_CENTS = 10_000_000
GRADUATED_TIER_ONE_BP = 300
GRADUATED_TIER_TWO_BP = 400
GRADUATED_TIER_THREE_BP = 500
FLAT_RATE_BP = 300

# --- Performance evaluation ---
EVALUATION_WEIGHTS = {
    "resource_protection_score": 0.35,
    "client_safety_score": 0.25,
    "reporting_timeliness_score": 0.20,
    "fee_compliance_score": 0.20,
}
RATING_BANDS = {"SUPERIOR": 90.0, "SATISFACTORY": 75.0, "MARGINAL": 60.0}
PENALTY_MULTIPLIER = {
    "SUPERIOR": 0.5,
    "SATISFACTORY": 1.0,
    "MARGINAL": 1.5,
    "UNSATISFACTORY": 2.0,
}
PENALTY_POINTS_CAP = 30.0

# --- Noncompliance ---
SEVERITY_POINTS = {"MINOR": 2, "MODERATE": 5, "MAJOR": 10}
INSTRUMENT_MATRIX = {
    "MINOR": ["WARNING"],
    "MODERATE": ["WARNING", "SUSPENSION"],
    "MAJOR": ["SUSPENSION", "REVOCATION"],
}
POINTS_WINDOW_DAYS = 1095
NONCOMPLIANT_POINTS_THRESHOLD = 12
PROBATION_POINTS_THRESHOLD = 5
SUSPENSION_BASE_DAYS = 30

# --- Prospectus scoring weights ---
SCORING_WEIGHTS = {
    "experience": 0.30,
    "guide_roster": 0.30,
    "assurance": 0.20,
    "need_match": 0.20,
}
EXPERIENCE_POINTS_PER_PRIOR_PERMIT = 25
DEFAULT_MIN_QUALIFYING_SCORE = 60.0

# --- Operating plan sections ---
PLAN_SECTION_NAMES = [
    "sanitation_section",
    "campsite_section",
    "stock_section",
    "resource_protection_section",
]
PLAN_SECTION_POINTS = 25.0
PLAN_REVISION_LIMIT = 2

# --- Pagination ---
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
