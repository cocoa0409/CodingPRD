"""Domain thresholds — numeric constants from the PRD's refund and scan rules."""

# Refund: maximum granted scans for which a pass remains refund-eligible, and the
# denominator of the proration's unused-share fraction (PRD §3.5).
MAX_SCANS_FOR_REFUND = 10

# Refund: processing fee deducted on RELOCATION / DISSATISFIED proration (PRD §3.5).
PROCESSING_FEE_RATE = 0.10

# Scan: anti-passback cooldown in whole minutes, half-open window (PRD §3.3).
ANTI_PASSBACK_MINUTES = 5

# A UUID that resolves to no resource — for not-found tests.
NON_EXISTENT_UUID = "00000000-0000-0000-0000-000000000000"
