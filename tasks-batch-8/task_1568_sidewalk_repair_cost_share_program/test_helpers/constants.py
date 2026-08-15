"""Domain thresholds — numeric constants from the PRD's calculation rules."""

# Logical clock startup default (PRD §2.4).
CLOCK_START = "2026-08-01T00:00:00Z"

# Severity weights and classification thresholds (PRD §3.2).
SEVERITY_WEIGHTS = {"MINOR": 25, "MAJOR": 60, "TRIP_HAZARD": 100}
TRIP_THRESHOLD_INCHES = 0.5
MAJOR_OFFSET_INCHES = 0.25
SETTLEMENT_MAJOR_SQFT = 9
SPALLING_MAJOR_SQFT = 16

# Cost-share percentage tiers (PRD §3.5).
BASE_CITY_SHARE = 50
ARTERIAL_BONUS = 20
COLLECTOR_BONUS = 10
SENIOR_BONUS = 20
LOW_INCOME_BONUS = 30
SHARE_CAP = 90

# Award arithmetic (PRD §3.5 / §3.6).
ENGINEER_UNIT_RATE_CENTS = 1200
RAMP_FLAT_CENTS = 250000
PER_APPLICATION_CAP_CENTS = 400000
PER_PARCEL_LIFETIME_CAP_CENTS = 800000

# Deadline constants (PRD §3.3 / §3.5).
DEFAULT_BASE_DEADLINE_DAYS = 45
HARDSHIP_EXTENSION_DAYS = 30
APPEAL_RESET_DAYS = 15
APPROVAL_EXPIRY_DAYS = 60

# Derived datetimes at the startup clock.
DEFAULT_NOTICE_DEADLINE = "2026-09-15T00:00:00Z"   # issue at 2026-08-01 + 45d
DEFAULT_APPROVAL_EXPIRY = "2026-09-30T00:00:00Z"   # approve at 2026-08-01 + 60d

# Batch / forestry constants (PRD §3.7 / §3.8).
CURE_BUFFER_DAYS = 7

# Lien constants (PRD §3.9).
ADMIN_FEE_MIN_CENTS = 15000
ADMIN_FEE_PCT = 10
DEFAULT_INTEREST_RATE_BP = 800
FORECLOSURE_MIN_DAYS = 90
PAYOFF_GOOD_THROUGH_DAYS = 15
DAYS_PER_YEAR_X10000 = 3650000

# Well-known operator ids for the five opaque roles.
COORD_1 = "coord-1"
INSP_1 = "insp-1"
INSP_2 = "insp-2"
FIN_1 = "fin-1"
FOR_1 = "for-1"
HEAR_1 = "hear-1"
