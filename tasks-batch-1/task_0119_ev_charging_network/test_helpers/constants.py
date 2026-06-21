"""Domain thresholds and shared test defaults.

Numeric constants come from the PRD's pricing and allocation rules (§3.4, §3.8).
Generic NON_EXISTENT_UUID comes from the framework.
"""

# Power allocations are expressed to one decimal place of a kilowatt (PRD §2.8, §3.4).
ALLOCATION_GRANULARITY_KW = 0.1

# Pagination bounds (PRD §2.3).
PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "DEFAULT_OFFSET": 0,
}

# The canonical ENERGY_BASED tariff used across difficulty/corner setups.
# tier1 <= 20 kWh @ 30c, tier2 20..50 kWh @ 25c, tier3 >50 kWh @ 20c;
# time rate 40c/min; grace 10 min, idle 50c/min; session fee 100c.
ENERGY_TARIFF = {
    "pricing_mode": "ENERGY_BASED",
    "session_fee_cents": 100,
    "energy_tier_1_max_kwh": 20,
    "energy_tier_2_max_kwh": 50,
    "energy_rate_t1_cents": 30,
    "energy_rate_t2_cents": 25,
    "energy_rate_t3_cents": 20,
    "time_rate_cents_per_min": 40,
    "idle_grace_minutes": 10,
    "idle_fee_cents_per_min": 50,
    "effective_from": "2026-01-01T00:00:00Z",
    "effective_to": "2027-01-01T00:00:00Z",
}

# A funded wallet large enough for any single test session.
FUNDED_WALLET_CENTS = 100_000

# The clock instant most setups start at.
BASE_CLOCK = "2026-06-01T00:00:00Z"
