"""Domain thresholds and numeric constants from the PRD's calculation rules."""

# Fee components (integer cents) — PRD §3.2
OVER_ALLOWANCE_FEE_CENTS = 2500
REFRIGERANT_FEE_CENTS = 4500
OVERSIZE_FEE_CENTS = 1500
MATTRESS_FEE_CENTS = 1200
SURCHARGE_RATE = 0.085

# Contamination penalty at completion (flat, no surcharge) — PRD §3.4
CONTAMINATION_PENALTY_CENTS = 3000

# Illegal-dumping fine schedule — PRD §3.6
BASE_FINE_CENTS = 25000
ESCALATION_CAP = 3

# Per-category base load units — PRD §3.2
LOAD_BY_CATEGORY = {
    "STANDARD_FURNITURE": 2,
    "MATTRESS": 3,
    "APPLIANCE_NO_REFRIGERANT": 4,
    "APPLIANCE_WITH_REFRIGERANT": 5,
    "ELECTRONICS": 2,
    "TIRES": 1,
}
OVERSIZE_LOAD_MULTIPLIER = 2

# Default annual free-item allowance — PRD §3.1
DEFAULT_ANNUAL_ALLOWANCE_ITEMS = 4

# Logical clock startup default — PRD §2.4
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"

TEST_DEFAULTS = {
    "MAX_LOAD_UNITS": 40,
    "MAX_STOPS": 25,
    "STREET_ADDRESS": "1 Test Way",
    "SERVICE_ZONE": "ZONE_NORTH",
}
