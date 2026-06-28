"""Domain thresholds — numeric constants from the PRD calculations and rules.

Generic NON_EXISTENT_UUID comes from the framework.
"""

# Risk-tier derivation thresholds (PRD §3.7).
BP_ELEVATED_THRESHOLD = 140
BP_TRANSFER_THRESHOLD = 160
WATCH_ESCALATION_COUNT = 2

# Self-pay estimate fraction on the global fee (PRD §3.6).
SELF_PAY_ESTIMATE_PCT = 0.20

# Fixed transfer fee created by the transfer cascade (PRD §3.8).
TRANSFER_FEE_CENTS = 75000

# Pagination defaults (PRD §2.3).
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MAX_LIMIT = 100

# Logical-clock startup default (PRD §2.9).
CLOCK_STARTUP_DEFAULT = "2026-01-01T00:00:00Z"

# A syntactically valid UUID that resolves to no resource.
MISSING_UUID = "00000000-0000-4000-8000-000000000000"
