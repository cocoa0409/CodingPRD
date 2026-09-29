"""
Business constants for the Warewashing Chemical & Dish Machine Service Program API.

Every value here is transcribed from the PRD so that tests never hard-code a
magic number inline. Section references point at the PRD section that fixes the
value.
"""

# ─── §2.4 Logical clock ────────────────────────────────────────────────

# "Before the clock has ever been set, it reads exactly 2026-08-01T00:00:00Z"
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

# ─── §2.3 Pagination ───────────────────────────────────────────────────

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ─── §2.6 Rounding ─────────────────────────────────────────────────────

PCT_DECIMALS = 2          # drift_pct, variance_pct, goal_attainment_pct
DOSE_DECIMALS = 2         # doses and per-rack baselines
PRESSURE_FACTOR_DECIMALS = 4  # sustainability rinse-pressure factor

# ─── §3.1 Catalog defaults ─────────────────────────────────────────────

DEFAULT_CONCENTRATION_TOLERANCE_PCT = 10.00
DEFAULT_MIN_CONTACT_SECONDS = 7
DEFAULT_PRIORITY_TIER = "STANDARD"
DEFAULT_BILLING_STATUS = "CURRENT"
DEFAULT_SITE_STATUS = "ACTIVE"
DEFAULT_TECHNICIAN_STATUS = "AVAILABLE"

# ─── §3.2 Agreement ────────────────────────────────────────────────────

DEFAULT_RENEWAL_NOTICE_DAYS = 60
DEFAULT_AUTO_RENEW = False
# "a shortfall rate of 60 percent"
TERMINATION_SHORTFALL_RATE = 0.60
# "divide by 30 days, and round up to the next whole number"
TERMINATION_MONTH_DAYS = 30

# ─── §3.3 Retrieval due dates ──────────────────────────────────────────

# Manual retrieval order default: "the current clock's date plus 14 days"
MANUAL_RETRIEVAL_DUE_DAYS = 14
# Cascade alpha: "retrieval_due_date set to the current clock's date plus 30 days"
CASCADE_RETRIEVAL_DUE_DAYS = 30

# ─── §3.4 Alert severity margins ───────────────────────────────────────

# LOW_FINAL_RINSE_TEMP is CRITICAL at or below 5 F under the minimum
CRITICAL_FINAL_RINSE_TEMP_MARGIN_F = 5
# LOW_WASH_TEMP is CRITICAL at or below 10 F under the minimum
CRITICAL_WASH_TEMP_MARGIN_F = 10
# LOW_RINSE_PRESSURE is CRITICAL at or below 3 psi under the minimum
CRITICAL_RINSE_PRESSURE_MARGIN_PSI = 3
# HIGH_CYCLE_RATE fires above racks_per_hour * 1.10
HIGH_CYCLE_RATE_FACTOR = 1.10

ALERT_TYPE_ORDER = [
    "LOW_FINAL_RINSE_TEMP",
    "LOW_WASH_TEMP",
    "LOW_RINSE_PRESSURE",
    "HIGH_RINSE_PRESSURE",
    "HIGH_CYCLE_RATE",
    "CALIBRATION_OVERDUE",
]

# ─── §3.5 Priority scoring ─────────────────────────────────────────────

SYMPTOM_BASE_SCORE = {
    "MACHINE_DOWN": 400,
    "LOW_TEMP": 300,
    "NO_CHEMICAL": 250,
    "LEAK": 200,
    "RACK_QUALITY": 100,
}
HEALTH_DOWN_IN_HOURS_SCORE = 300
HEALTH_DOWN_OUT_OF_HOURS_SCORE = 90
HEALTH_DEGRADED_SCORE = 60
PREMIUM_TIER_SCORE = 120
SANITATION_EXPOSURE_SCORE = 200
ELEVATED_POSTURE_SCORE = 80
PRIORITY_SCORE_CAP = 1000

# SLA bands: "a score of 700 or more gets 120 minutes, a score of 400 or more
# but under 700 gets 240 minutes, and anything below 400 gets 480 minutes"
SLA_HIGH_SCORE = 700
SLA_HIGH_MINUTES = 120
SLA_MID_SCORE = 400
SLA_MID_MINUTES = 240
SLA_LOW_MINUTES = 480

# §3.1 posture: CRITICAL when an open ticket carries a priority_score >= 700
CRITICAL_POSTURE_SCORE = 700

# §3.5 dispatch eligibility: open_ticket_count strictly fewer than three
MAX_OPEN_TICKETS_PER_TECHNICIAN = 3
CERTIFICATION_RANK = {"SANITATION_CERTIFIED": 3, "L2": 2, "L1": 1}

# ─── §3.6 Visit scheduling and verdicts ────────────────────────────────

TRAVEL_BUFFER_MINUTES = 30
# "when the absolute value of drift_pct is greater than 25.00, the verdict is FAIL"
DRIFT_HARD_FAIL_PCT = 25.00

# ─── §3.7 Delivery pricing and variance classification ────────────────

DISCOUNT_TIER_HIGH_UNITS = 25
DISCOUNT_RATE_HIGH = 0.12
DISCOUNT_TIER_MID_UNITS = 10
DISCOUNT_RATE_MID = 0.05
DISCOUNT_RATE_NONE = 0.0

THEFT_SUSPECT_PCT = 25.00
DILUTION_SUSPECT_PCT = -15.00
DILUTION_EVIDENCE_DRIFT_PCT = -10.00
OVERUSE_PCT = 8.00
UNDERUSE_PCT = -8.00

# ─── §3.8 Investigation case ───────────────────────────────────────────

MIN_EVIDENCE_ITEMS_TO_SUBSTANTIATE = 2

# ─── §3.9 Sustainability report ────────────────────────────────────────

BASE_SERVICE_FEE_CENTS = 25000
SERVICE_FEE_RATE_LOW_THRESHOLD = 200000
SERVICE_FEE_RATE_LOW = 0.08
SERVICE_FEE_RATE_MID_THRESHOLD = 500000
SERVICE_FEE_RATE_MID = 0.06
SERVICE_FEE_RATE_HIGH = 0.04
SUSTAINABILITY_CREDIT_RATE = 0.05
SUSTAINABILITY_CREDIT_CAP_CENTS = 15000

# ─── Canonical catalog fixture values ─────────────────────────────────

# DET-100 detergent
DET_CONCENTRATION_TARGET_PPM = 1200
DET_SPEC_DOSE_ML_PER_RACK = 8.00
DET_UNIT_SIZE_ML = 20000
DET_UNIT_PRICE_CENTS = 9600

# SAN-200 sanitizer
SAN_CONCENTRATION_TARGET_PPM = 200
SAN_SPEC_DOSE_ML_PER_RACK = 2.50
SAN_UNIT_SIZE_ML = 10000
SAN_UNIT_PRICE_CENTS = 7200
SAN_MIN_PPM = 150
SAN_MAX_PPM = 400
SAN_MIN_CONTACT_SECONDS = 7

# DT-88 door-type machine model
DT88_RACKS_PER_HOUR = 60
DT88_RATED_WATER_L_PER_RACK = 0.74
DT88_RATED_KWH_PER_RACK = 0.41
DT88_MIN_FINAL_RINSE_TEMP_F = 180
DT88_MIN_WASH_TEMP_F = 150
DT88_MIN_RINSE_PRESSURE_PSI = 15
DT88_MAX_RINSE_PRESSURE_PSI = 25
DT88_EQUIPMENT_VALUE_CENTS = 480000
DT88_MAX_CYCLES_BETWEEN_CALIBRATIONS = 20000

# Canonical site economics
SITE_REGION_CODE = "NW"
SITE_OPERATING_WINDOW_START_MINUTE = 600   # 10:00 UTC inclusive
SITE_OPERATING_WINDOW_END_MINUTE = 1320    # 22:00 UTC exclusive
SITE_BASELINE_WATER_L_PER_RACK = 1.20
SITE_BASELINE_KWH_PER_RACK = 0.62
SITE_WATER_COST_CENTS_PER_1000L = 480
SITE_ENERGY_COST_CENTS_PER_KWH = 14

# Canonical agreement economics
AGREEMENT_MIN_TERM_MONTHS = 36
AGREEMENT_MONTHLY_MINIMUM_SPEND_CENTS = 20000
CUSTOMER_SUSTAINABILITY_GOAL_WATER_L = 500000
