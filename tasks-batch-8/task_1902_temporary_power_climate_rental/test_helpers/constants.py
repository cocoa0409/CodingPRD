"""Domain thresholds and numeric constants from the PRD's calculation rules."""

# PRD §3.3 load sizing
SAFETY_FACTOR = 1.25
DEMAND_FACTORS = {"CONTINUOUS": 1.0, "INTERMITTENT": 0.7, "STANDBY": 0.35}

# PRD §3.3 accessory ampacity requirement
VOLTAGE = 480
SQRT3 = 1.732

# PRD §3.4 tiered rental accrual
DAYS_PER_WEEK = 7
DAYS_PER_MONTH = 28
SECONDS_PER_DAY = 86400

# PRD §3.9 invoice composition
FUEL_BUYBACK_CENTS_PER_LITER = 180
SLA_BREACH_CREDIT_CENTS = 25000

# PRD §3.6 fuel projection
LOAD_FACTOR = 0.75
SPECIFIC_CONSUMPTION_L_PER_KWH = 0.28
METERED_WINDOW_DAYS = 7

# PRD §3.5 emissions screening caps (g/kWh)
JURISDICTION_CAPS = {"CA-SCAQMD": 5.0, "TX-TCEQ": 8.0, "FL-DEP": 12.0}
DEFAULT_CAP = 10.0
TIER2_BAN_CAP_AT_OR_BELOW = 5.0

# PRD §2.5 quote validity window on the logical clock
QUOTE_VALIDITY_DAYS = 7

# PRD §2.5 startup value of the logical clock
LOGICAL_CLOCK_START = "2026-08-01T00:00:00Z"

# PRD §3.7 technician travel buffer (minutes on each side of a visit window)
TECHNICIAN_BUFFER_MINUTES = 60

# PRD §3.5 permit resubmission budget
PERMIT_MAX_REVIEW_ROUNDS = 3

# Shared test data defaults for the canonical fleet unit / kit / site.
TEST_DEFAULTS = {
    "UNIT_CAPACITY_KW": 200,
    "UNIT_NOX": 3.0,
    "UNIT_DAY_RATE": 12000,
    "UNIT_WEEK_RATE": 60000,
    "UNIT_MONTH_RATE": 200000,
    "UNIT_DEMOB_FEE": 35000,
    "UNIT_HOME_DEPOT": "DAL-01",
    "KIT_CODE": "CABLE-400A",
    "KIT_AMPACITY": 400,
    "KIT_DAY_RATE": 3000,
    "KIT_WEEK_RATE": 15000,
    "KIT_MONTH_RATE": 50000,
    "SITE_JURISDICTION": "TX-TCEQ",
    "SITE_TANK_CAPACITY": 5000,
    "LOAD_NAMEPLATE_KW": 160,
    "CONTRACT_START": "2026-09-01T00:00:00Z",
    "CONTRACT_END": "2026-09-08T00:00:00Z",
}
