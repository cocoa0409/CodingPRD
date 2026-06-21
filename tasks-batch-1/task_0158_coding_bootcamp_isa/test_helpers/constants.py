"""Domain thresholds — numeric constants from the PRD's calculations.

Sourced from the refund calculation (§3.6), the CIRR placement window (§3.12),
and the standard ISA terms used throughout the repayment narratives.
"""

# Refund computation constants (PRD §3.6).
WITHDRAWAL_RETENTION = 0.10        # deposit retains 10% on non-cooling-off refunds
TUITION_PRORATION_WEIGHT = 0.50    # unused-tuition proration weight
ADMIN_FEE_PCT = 0.05               # administrative fee on gross refund

# CIRR placement window (PRD §3.12).
CIRR_WINDOW_DAYS = 180

# Cooling-off grace window (PRD §3.5).
COOLING_OFF_DAYS = 14

# Standard ISA terms used by fixtures to reach a known ledger state.
TEST_DEFAULTS = {
    "INCOME_SHARE_PCT": 0.17,
    "CAP_CENTS": 3_000_000,
    "TERM_MONTHS": 24,
    "INCOME_THRESHOLD_CENTS": 400_000,
    "DEPOSIT_CENTS": 200_000,
    "TUITION_STICKER_CENTS": 1_500_000,
}

# A well-formed but non-existent UUID for not-found probes.
NONEXISTENT_UUID = "00000000-0000-4000-8000-000000000000"
