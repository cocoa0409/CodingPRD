"""Domain thresholds — numeric constants named by the PRD's calculation rules
(§2.10 age limit, §3.3 termination fee, §3.6 proration, §3.7 mileage credit,
§3.9 repair split, §3.10 damage billing, §3.11 penalties)."""

# Logical clock default reading (PRD §2.5).
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

THRESHOLDS = {
    # §2.10 fleet safety gates
    "INTERCHANGE_AGE_LIMIT_YEARS": 50,
    # §3.3 early termination fee: min(remaining_days, 90) * rate * 50%
    "TERMINATION_FEE_CAP_DAYS": 90,
    "TERMINATION_FEE_PCT": 50,
    # §3.4 commodity-change turnaround buffer
    "COMMODITY_TURNAROUND_BUFFER_DAYS": 3,
    # §3.7 mileage credit tiering and cap
    "HIGH_MILEAGE_THRESHOLD_MILES": 120000,
    "EXCESS_RATE_PCT": 80,
    "CREDIT_CAP_PCT": 80,
    # §3.9 repair responsibility split
    "WEAR_ALLOWANCE_CENTS": 25000,
    "WEAR_EXCESS_LESSEE_PCT": 40,
    # §3.10 damage billing schedule
    "LABOR_RATE_CENTS_PER_HOUR": 14500,
    "BETTERMENT_AGE_YEARS": 30,
    "BETTERMENT_PCT": 25,
    # §3.11 directive default grace
    "DEFAULT_GRACE_DAYS": 30,
}

TEST_DEFAULTS = {
    "CAR_HIRE_DAILY_CENTS": 9000,
    "MILEAGE_CREDIT_CENTS": 55,
    "BASE_DAILY_RATE_CENTS": 5000,
    "LESSOR_SHARE_PCT": 100,
    "REPAIR_CAP_CENTS": 20000,
    "CREDIT_LIMIT_CENTS": 100000000,
    "TARIFF_WINDOW_FROM": "2026-01-01",
    "TARIFF_WINDOW_TO": "2027-01-01",
    "LEASE_START": "2026-08-01",
    "LEASE_END": "2027-07-31",
}
