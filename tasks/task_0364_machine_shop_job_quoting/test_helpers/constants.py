"""Domain thresholds — numeric constants from the PRD calculations and rates.

Generic NON_EXISTENT_UUID comes from the framework. A literal non-existent UUID
constant is also provided here for tests that follow the design indices' use of
the fixed all-zeros UUID in their `trigger` calls.
"""

# Per-minute machine rates, cents per minute (PRD §2.10).
MACHINE_RATES = {
    "MILL_3AX": 180,
    "MILL_5AX": 320,
    "LATHE": 150,
}

# Margin tier boundaries on extended_cost_cents (PRD §3.2).
MARGIN_TIER_LOW_MAX = 50000      # exclusive upper bound for the 35% tier
MARGIN_TIER_MID_MAX = 200000     # exclusive upper bound for the 25% tier
MARGIN_PCT_LOW = 35
MARGIN_PCT_MID = 25
MARGIN_PCT_HIGH = 18

# Shipment penalty constants (PRD §3.6).
UNIT_PENALTY_PER_DAY_CENTS = 50
PENALTY_CAP_CENTS = 20000

# Invoice tax (PRD §3.7).
TAX_PCT = 8.25

# Inspection station default buffer (PRD §3.5).
DEFAULT_STATION_BUFFER_MIN = 15

# A fixed UUID that never resolves to a real resource — matches the design
# indices' not-found probes.
ZERO_UUID = "00000000-0000-4000-8000-000000000000"
