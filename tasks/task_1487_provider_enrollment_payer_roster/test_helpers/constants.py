"""Domain thresholds and well-known instants from the PRD.

PRD §2.5: the logical clock starts at exactly 2026-08-01T00:00:00Z.
PRD §3.2: attestation cycle is 120 days; the warning window opens 30 days
before due_at.
PRD §3.3 / §3.4: retroactive windows reach 90 days back from the current
logical date.
PRD §3.7: the revalidation window starts 60 days before the due date.
PRD §3.8: the per-claim recoupment fee is 2% of amount_cents, rounded half up.
"""

THRESHOLDS = {
    "ATTESTATION_CYCLE_DAYS": 120,
    "DUE_WARNING_DAYS": 30,
    "RETRO_DAYS": 90,
    "REVALIDATION_WINDOW_DAYS": 60,
}

# Per-claim recovery fee percentage (PRD §3.8).
RECOUPMENT_FEE_PCT = 0.02

# Logical-clock startup default (PRD §2.5).
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

TEST_DEFAULTS = {
    "REVALIDATION_INTERVAL_DAYS": 200,
    "CLAIM_AMOUNT_CENTS": 1000,
}


def recoupment_fee(amount_cents: int) -> int:
    """Per-claim fee: 2% of amount_cents, rounded half up to whole cents."""
    doubled = amount_cents * 2  # hundredths of a cent
    return (doubled + 50) // 100
