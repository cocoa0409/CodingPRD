"""Domain thresholds — numeric constants named by the PRD.

Wage progression (PRD §3.6): step k requires STEP_HOURS[k] accumulated OJT
hours AND STEP_RTI[k] related-instruction credits; the step rate is the
journeyman base rate multiplied by STEP_PCT[k], rounded half-up.
"""

# PRD §3.6 wage step gates and percentages
STEP_PCT = {1: 0.50, 2: 0.60, 3: 0.70, 4: 0.80, 5: 0.90}
STEP_HOURS = {2: 2000, 3: 4000, 4: 6000, 5: 8000}
STEP_RTI = {2: 144, 3: 288, 4: 432, 5: 576}

# PRD §3.8 journeyman certification prerequisites
CERT_MIN_OJT_HOURS = 8000
CERT_MIN_RTI_CREDITS = 576

# PRD §3.4 instructor turnover buffer (minutes)
TURNOVER_MINUTES = 30

# PRD §3.5 overtime cap multiplier on the scheduled class window
OVERTIME_CAP_MULTIPLIER = 1.25

# PRD §2.11 logical clock reading before any adjustment
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

# Common test inputs
TEST_DEFAULTS = {
    "FUND_NAME": "JATC Training Fund",
    "EMPLOYER_LEGAL_NAME": "Ampere Electric LLC",
    "EMPLOYER_RATE_CENTS_PER_HOUR": 500,
    "APPRENTICE_FULL_NAME": "Rae Torres",
    "APPRENTICE_TRADE": "INSIDE_WIREMAN",
    "JOURNEYMAN_BASE_RATE_CENTS": 4000,
    "INSTRUCTOR_USER_ID": "inst-1",
    "INSTRUCTOR_NAME": "I. Mason",
    "INSTRUCTOR_RATE_CENTS_PER_HOUR": 6000,
    "FACILITY": "SHOP-A",
    "RTI_CREDIT_VALUE": 8,
    "CLASS_CAPACITY": 10,
    "CLASS_START_MINUTE": 600,
    "CLASS_END_MINUTE": 720,
    "FISCAL_YEAR": 2026,
}
