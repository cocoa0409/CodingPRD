"""Domain constants — canonical local configurations and shared values.

The logical clock's startup default is exactly 2026-08-01T00:00:00Z (PRD
section on the logical clock); tests that need a different time set it
explicitly through the clock endpoint.
"""

# Canonical PERCENTAGE_OF_GROSS local configuration used across tests.
PCT_LOCAL = {
    "dues_method": "PERCENTAGE_OF_GROSS",
    "default_dues_percent_bp": 200,      # 2.00% of gross wages
    "default_flat_dues_cents": 5000,
    "per_capita_rate_cents": 1500,
    "delinquency_threshold_cents": 10000,
    "grace_periods": 2,
    "notice_cure_days": 30,
    "reinstatement_base_fee_cents": 2500,
    "max_suspensions": 3,
    "expel_after_months": 12,
}

# Canonical FLAT_RATE local configuration used across tests.
FLAT_LOCAL = {
    "dues_method": "FLAT_RATE",
    "default_dues_percent_bp": 200,
    "default_flat_dues_cents": 5000,
    "per_capita_rate_cents": 1500,
    "delinquency_threshold_cents": 10000,
    "grace_periods": 2,
    "notice_cure_days": 10,
    "reinstatement_base_fee_cents": 2500,
    "max_suspensions": 3,
    "expel_after_months": 12,
}

# Logical-clock startup instant named by the PRD.
CLOCK_START_ISO = "2026-08-01T00:00:00Z"

# Basis-point denominator for the percentage-dues multiplication.
BASIS_POINTS_DENOMINATOR = 10000

# A UUID that never resolves to a persisted entity.
MISSING_UUID = "00000000-0000-0000-0000-000000000000"
