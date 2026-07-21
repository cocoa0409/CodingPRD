"""Domain thresholds and shared literals from the PRD calculations (§2.5, §2.6, §3)."""

# The single non-integer factor in the system: invoice management fee (PRD §2.5, §3.8).
MGMT_FEE_RATE = 0.035

# Server logical-clock startup default (PRD §2.6).
CLOCK_DEFAULT = "2026-07-01T00:00:00Z"

# Standard policy used across setups. Thresholds chosen so that:
#   market/estimate < 100000  -> approval NONE (auto-APPROVED)
#   100000 <= estimate < 500000 -> MANAGER
#   estimate >= 500000 -> EXEC
POLICY_DEFAULTS = {
    "name": "Global",
    "region": "NA",
    "max_air_class": "BUSINESS",
    "max_hotel_nightly_cents": 40000,
    "advance_purchase_days": 14,
    "requires_manager_approval_over_cents": 100000,
    "requires_exec_approval_over_cents": 500000,
    "exchange_penalty_cents": 15000,
    "credit_validity_days": 365,
}
