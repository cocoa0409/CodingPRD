"""
Domain constants transcribed from the PRD.

Only values the PRD states literally live here.
"""

# ─── Logical clock ────────────────────────────────────

# PRD §2.4: "The clock's startup default is exactly `2026-08-01T00:00:00Z`".
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"

# ─── Filing deadline ──────────────────────────────────

# PRD §3.1: a five-business-day window.
FILING_DEADLINE_BUSINESS_DAYS = 5

# PRD §3.1: "The federal holiday calendar the system honours consists of
# exactly these dates".
FEDERAL_HOLIDAYS = [
    "2026-01-01",
    "2026-07-03",
    "2026-09-07",
    "2026-11-26",
    "2026-12-25",
    "2027-01-01",
]

# PRD §3.3: days_late is computed by dividing the elapsed time by 86400 seconds.
SECONDS_PER_DAY = 86400

# ─── Pagination ───────────────────────────────────────

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ─── Population rules ─────────────────────────────────

MODEL_YEAR_MIN = 1980
MODEL_YEAR_MAX = 2100
PLANT_MODEL_CODE_MAX_LEN = 8
DEFECT_DESCRIPTION_MAX_LEN = 2000
DEALER_CODE_MAX_LEN = 16
VIN_LENGTH = 17

# ─── Wave coverage gate (PRD §3.6) ────────────────────

COVERAGE_MINIMUM_BY_SEVERITY = {
    "HIGH": 1.0000,
    "MODERATE": 0.6000,
    "LOW": 0.3000,
}

# PRD §2.11: "`coverage_tier_factor` is one of exactly four values".
COVERAGE_TIER_FACTORS = [1.00, 0.75, 0.40, 0.00]

# PRD §3.6: the fourteen-day mailing separation rule.
WAVE_MAILING_SEPARATION_DAYS = 14

# ─── Parts and claims (PRD §3.5, §3.7) ────────────────

# One kit per repair.
KITS_PER_REPAIR = 1

# PRD §3.5: lead_time_days "defaults to 30 days when omitted".
DEFAULT_LEAD_TIME_DAYS = 30

# PRD §3.7: claimed hours are capped at one and a half times flat_hours.
LABOR_HOURS_CAP_MULTIPLIER = 1.5

# PRD §3.7: a fifteen percent parts-handling markup.
PARTS_HANDLING_MARKUP = 0.15

# PRD §3.7: a flat administrative allowance of 12.00 dollars.
ADMIN_ALLOWANCE = 12.00

# PRD §3.7: the regional rate ceiling for the dealer's region_code.
REGIONAL_RATE_CEILING = {
    "NE": 152.00,
    "SE": 128.50,
    "MW": 121.75,
    "WE": 165.25,
}

# ─── Effectiveness and completion (PRD §3.9) ──────────

EFFECTIVENESS_STARTING_POINTS = 100.00
EFFECTIVENESS_FLOOR = 70.00
REPEAT_REPAIR_WEIGHT = 60.00
UNREACHABLE_WEIGHT = 20.00
LATE_FILING_PENALTY = 5.00

# ─── Outreach and follow-up waves (PRD §3.8) ──────────

UNREACHABLE_ATTEMPT_THRESHOLD = 3
FOLLOW_UP_TRIGGER_COMPLETION_PCT = 85.00
FOLLOW_UP_LEAD_DAYS = 21

# ─── Owner reimbursement (PRD §3.9) ───────────────────

PREVAILING_LABOR_RATE = 115.00
CUSTOMER_PRICE_FACTOR = 1.40
TOWING_CAP = 100.00
REIMBURSEMENT_INVOICE_MAX = 5000.00
REIMBURSEMENT_LOOKBACK_DAYS = 365
REIMBURSEMENT_TAIL_DAYS = 30
MAX_DOCUMENT_ROUNDS = 2

# ─── Closure gates (PRD §3.9) ─────────────────────────

CLOSURE_MIN_COMPLETION_RATE_PCT = 95.00
CLOSURE_MIN_EFFECTIVENESS_SCORE = 70.00
CLOSURE_MIN_QUARTERLY_FILINGS = 2
