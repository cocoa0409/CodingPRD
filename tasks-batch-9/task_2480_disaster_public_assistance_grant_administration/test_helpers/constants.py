"""Domain thresholds and shared literals taken from the PRD."""

# --- Numeric policy constants stated in the PRD -------------------------------
PER_CAPITA_INDICATOR_CENTS = 189
SMALL_PURCHASE_CEILING_CENTS = 2_500_000
SIMPLIFIED_ACQUISITION_THRESHOLD_CENTS = 25_000_000
MIN_COMPETITIVE_BIDS = 2
OVERTIME_MULTIPLIER = 1.5
FRINGE_CAP_PCT = 0.40
MITIGATION_CAP_PCT_SMALL = 0.20
MITIGATION_CAP_PCT_LARGE = 0.15
SINGLE_AUDIT_THRESHOLD_CENTS = 75_000_000
REPORT_GRACE_DAYS = 30
LABOR_REST_BUFFER_MINUTES = 30
EQUIPMENT_DAILY_HOURS_CAP = 16
MAX_RFI_ROUNDS = 2
APPEAL_WINDOW_DAYS = 60

# Risk-score weights and tier floors.
RISK_W_TYPE = 0.30
RISK_W_SECOND = 0.30
RISK_W_THIRD = 0.40
RISK_TIER_HIGH_MIN = 60
RISK_TIER_MEDIUM_MIN = 30
FACILITY_POINTS_PER_FACILITY = 10
DELINQUENCY_POINTS_PER_REPORT = 25

# --- Declaration defaults -----------------------------------------------------
DEFAULT_FEDERAL_COST_SHARE_PCT = 0.75
DEFAULT_SMALL_PROJECT_THRESHOLD_CENTS = 4_000_000

# --- Logical clock ------------------------------------------------------------
CLOCK_DEFAULT_UTC = "2026-08-01T00:00:00Z"

# --- Test scenario defaults ---------------------------------------------------
TEST_DEFAULTS = {
    "CLOCK": "2026-07-01T00:00:00Z",
    "DECLARATION_NUMBER": "DR-4900",
    "STATE_CODE": "TX",
    "INCIDENT_TYPE": "FLOOD",
    "INCIDENT_START_AT": "2026-06-10T00:00:00Z",
    "INCIDENT_END_AT": "2026-06-25T00:00:00Z",
    "POPULATION": 2_000_000,
    "APPLICANT_NAME": "City of Harborview",
    "APPLICANT_TYPE": "LOCAL_GOVERNMENT",
    "POPULATION_SERVED": 120_000,
    "FACILITY_NAME": "Riverside Pump Station",
    "FACILITY_TYPE": "WATER_CONTROL",
    "OWNERSHIP": "PUBLIC",
    "PROJECT_TITLE": "Pump Station Restoration",
    "SCOPE_OF_WORK": "Restore the damaged pump station to pre-disaster design.",
    "PROJECT_CATEGORY": "C",
    "ESTIMATED_REPAIR_COST_CENTS": 5_000_000,
    "WORK_START_AT": "2026-06-12T08:00:00Z",
    "WORK_END_AT": "2026-06-12T16:00:00Z",
}
