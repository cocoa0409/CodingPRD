"""Domain thresholds — numeric constants from the PRD pricing engines (§3.5, §3.7).

Generic NON_EXISTENT_UUID comes from the framework.
"""

# ── Reservation quote (forward-looking estimate, §3.5) ───────────────────
ESTIMATED_ROUND_TRIP_MILES = 60
MILEAGE_DISCOUNT_BY_TIER = {
    "STANDARD": 0.00,
    "SILVER": 0.10,
    "GOLD": 0.20,
}
ADDON_RATES = {
    "UTILITY_DOLLY": 700,
    "APPLIANCE_DOLLY": 1000,
    "FURNITURE_PAD_DOZEN": 500,
}

# ── Contract settlement (chronological/actual, §3.7) ─────────────────────
FUEL_PRICE_PER_GALLON_CENTS = 600
REFUEL_SERVICE_FEE_CENTS = 3000
LATE_GRACE_MINUTES = 119
LATE_FEE_PER_DAY_CENTS = 4000
SUPPLY_REFUND_PCT = 0.50

# ── Window overlap (§3.8) ────────────────────────────────────────────────
TURNAROUND_HOURS = 3

# ── Pagination bounds (§2.3) ─────────────────────────────────────────────
PAGINATION = {
    "default_limit": 10,
    "min_limit": 1,
    "max_limit": 100,
    "min_offset": 0,
}

# A syntactically valid UUID that names no resource (for NOT_FOUND probes).
MISSING_UUID = "00000000-0000-4000-8000-000000000000"
