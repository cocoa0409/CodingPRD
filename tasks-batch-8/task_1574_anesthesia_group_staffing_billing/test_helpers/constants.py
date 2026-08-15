"""Domain thresholds and conversion factors from the PRD calculation rules.

PRD §2.9 conversion factors; §3.3 rest buffer; §3.3 supervision ratio cap;
§3.6 standby notice tiers; §3.7 time-unit divisor; §3.8 daily/monthly caps.
"""

# PRD §3.7 charge_units
TIME_UNIT_MINUTES = 15
EMERGENCY_QUALIFYING_UNITS = 2
PS_UNITS = {"P1": 0, "P2": 0, "P3": 1, "P4": 2, "P5": 3, "P6": 0}

# PRD §2.9 conversion factors (cents per unit)
PERSONAL_CF_CENTS = 8000
DIRECTION_CF_CENTS = 8001
SUPERVISION_CF_CENTS = 4000
CRNA_SOLO_CF_CENTS = 7500
AD_FLAT_UNITS = 3.0

# PRD §3.3 safety gates
RATIO_MAX = 4
REST_MINUTES = 480

# PRD §3.6 standby notice tiers (minutes)
STANDBY_FULL_NOTICE_MINUTES = 120
STANDBY_NOTICE_FREE_MINUTES = 1440

# PRD §3.8 caps (cents)
DAILY_STIPEND_CAP_CENTS = 50000
MONTHLY_STIPEND_CAP_CENTS = 400000

# PRD §3.9 severity weights
SEVERITY_WEIGHTS = {"MINOR": 10, "MAJOR": 30, "CRITICAL": 60}

# Minute-of-day bounds per PRD §2.4
MINUTE_OF_DAY_MAX_START = 1438
MINUTE_OF_DAY_MAX_END = 1439

# Logical clock startup default per PRD §2.4
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"

# Common test dates / times
DATE_SERVICE = "2026-08-10"
VALID_EXPIRY = "2027-01-31"

TEST_DEFAULTS = {
    "SITE_NAME": "General Hospital",
    "SITE_NAME_2": "Surgery Center",
    "FEE_BASE_UNITS": 5,
    "FEE_CONTRACTED_MAX_CENTS": 1000000,
    "PROCEDURE_CODE": "P100",
    "REQUIRED_PRIMARY_SLOTS": 1,
    "SCHEDULED_DAY_END_MINUTE": 1200,
    "SERVICE_DATE": "2026-08-10",
    "CREDENTIAL_EXPIRES_ON": "2027-01-31",
    "DEA_EXPIRES_ON": "2027-01-31",
    "CALL_STIPEND_CENTS": 12000,
    "LATE_STAY_RATE_CENTS_PER_MINUTE": 50,
    "STANDBY_FULL_CENTS": 30000,
    "STANDBY_PARTIAL_CENTS": 15000,
}
