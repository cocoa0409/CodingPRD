"""Domain thresholds — numeric constants from PRD calculations (§2.6, §3.4, §3.6, §3.3)."""

# Citation base fines by violation type, in cents (PRD §3.6).
BASE_FINE_CENTS = {
    "OVERSTAY": 7500,
    "NO_PERMIT": 15000,
    "UNAUTHORIZED_ZONE": 10000,
    "WRONG_DESIGNATION": 5000,
}

# 25% late penalty applied to a late-upheld citation (PRD §3.6).
LATE_PENALTY_BPS = 2500

# due_at = issued_at + 14 days (PRD §3.6).
GRACE_DAYS = 14

# Turnover buffer between exclusive schedule windows, minutes (PRD §3.3).
TURNOVER_BUFFER_MINUTES = 15

# Basis-point unit: 10000 bps == a multiplier of 1.0 (PRD §2.6).
BPS_ONE = 10000

# Logical-clock startup default (PRD §3.8).
CLOCK_DEFAULT_UTC = "2026-05-01T00:00:00Z"

# Pagination bounds (PRD §2.3).
PAGINATION = {
    "default_limit": 10,
    "min_limit": 1,
    "max_limit": 100,
    "default_offset": 0,
}

# Canonical pricing-policy shape used across most fixtures.
DEFAULT_POLICY = {
    "name": "P1",
    "base_rate_cents_per_15min": 200,
    "peak_multiplier_bps": 15000,
    "peak_start_hour": 7,
    "peak_end_hour": 10,
    "surge_tier1_ratio_bps": 5000,
    "surge_tier1_mult_bps": 12500,
    "surge_tier2_ratio_bps": 8000,
    "surge_tier2_mult_bps": 15000,
}
