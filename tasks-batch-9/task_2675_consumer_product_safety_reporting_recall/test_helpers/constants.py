"""Domain constants for the consumer product safety reporting and recall API."""

# Every business endpoint is mounted under this prefix; the clock endpoint is not.
API_PREFIX = "/product-safety"
CLOCK_PATH = "/_clock/set_current_utc"

# The logical UTC clock reads exactly this before any client sets it.
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

# Injury base weights used by the severity weight computation.
INJURY_BASE_WEIGHTS = {
    "NO_INJURY": 1,
    "FIRST_AID": 3,
    "MEDICAL_TREATMENT": 8,
    "HOSPITALIZATION": 20,
    "FATALITY": 50,
}

# Channel credibility multipliers used by the severity weight computation.
CHANNEL_CREDIBILITY = {
    "CONSUMER_HOTLINE": 1.00,
    "WEB_FORM": 1.00,
    "RETAILER": 1.20,
    "MEDICAL_EXAMINER": 1.50,
}

# Hazard pattern snapshot constants.
EXPOSURE_DIVISOR = 10000
EXPOSURE_FLOOR = 1.0
CONCENTRATION_BASE = 0.5
RISK_INDEX_CEILING = 100
CONFIRM_MIN_INCIDENT_COUNT = 3
CONFIRM_MIN_CONCENTRATION_RATIO = 0.6000
CONFIRM_MIN_RISK_INDEX = 10.00

# Reportability evaluation clocks, in hours.
HIGH_RISK_THRESHOLD = 25.00
ESCALATION_WINDOW_HIGH_HOURS = 48
ESCALATION_WINDOW_NORMAL_HOURS = 120
REPORT_DUE_HOURS = 240
INCIDENT_ESCALATION_DEADLINE_HOURS = 120

# Score support thresholds keyed on the evaluation's standard basis.
DEFECT_SCORE_THRESHOLD = 5
RISK_SCORE_THRESHOLD = 5
COMBINED_SCORE_THRESHOLD = 8

# Statutory report lateness scoring.
SECONDS_PER_DAY = 86400
SURCHARGE_CENTS_PER_LATE_DAY = 250000
SURCHARGE_CAP_CENTS = 5000000

# Retailer stop-sale acknowledgement deadline, in hours after issuance.
ACK_DUE_HOURS = 72

# Audit windows are deconflicted per retailer with this travel buffer, in hours.
AUDIT_TRAVEL_BUFFER_HOURS = 24

# Progress report periods must be contiguous with exactly this gap, in hours.
REPORT_PERIOD_CONTIGUITY_HOURS = 24

# Remedy claim reimbursement constants.
REPAIR_KIT_COST_CENTS = 2500
RETROFIT_KIT_COST_CENTS = 4200
HANDLING_FEE_RATE = 0.075

# Civil penalty assessment constants.
PENALTY_BASE_CENTS_PER_VIOLATION = 1000000
SEVERITY_MULTIPLIER_FATALITY = 1.50
SEVERITY_MULTIPLIER_HOSPITALIZATION = 1.25
SEVERITY_MULTIPLIER_DEFAULT = 1.00
LATENESS_MULTIPLIER_PER_DAY = 0.05
LATENESS_MULTIPLIER_CAP = 0.50
PENALTY_CEILING_CENTS = 17150000
NEGOTIATION_ROUND_CAP = 6

# Consent agreement tiers, keyed on the pre-credit settlement base.
TIER_1_UPPER_EXCLUSIVE_CENTS = 5000000
TIER_2_UPPER_INCLUSIVE_CENTS = 12000000
TIER_1_RATE = 0.10
TIER_2_RATE = 0.15
TIER_3_RATE = 0.20
COOPERATION_BONUS_POINTS = 0.05
CREDIT_RATE_CEILING = 0.30
COMPLIANCE_PROGRAM_THRESHOLD_CENTS = 5000000
REPORTING_MONTHS_WITH_PROGRAM = 24
REPORTING_MONTHS_WITHOUT_PROGRAM = 12

# Pagination defaults declared by the contract.
DEFAULT_LIMIT = 10
MAX_LIMIT = 100
