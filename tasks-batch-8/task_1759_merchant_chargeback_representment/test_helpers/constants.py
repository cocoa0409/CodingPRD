"""Domain thresholds — numeric constants from PRD rules (§2.5, §3.3, §3.4, §3.9)."""

# PRD §2.5: startup default of the test-driving logical clock.
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

# PRD §3.4: prevention-alert response window in hours.
ALERT_RESPONSE_HOURS = 72

# PRD §3.3: settlement-hold maturity is exactly 90 days after occurred_at.
RESERVE_MATURITY_DAYS = 90

# PRD §3.9: ratio sentinel when the denominator is zero but the numerator is not.
ZERO_DENOMINATOR_SENTINEL_BPS = 100000

# PRD §3.9: program threshold table (inclusive boundaries).
PROGRAM_THRESHOLDS = {
    "VDMP_STANDARD": {"min_bps": 90, "min_count": 5},
    "VDMP_EXCESSIVE": {"min_bps": 180, "min_count": 10},
    "ECM": {"min_bps": 150, "min_count": 10},
    "HECM": {"min_bps": 300, "min_count": 10},
}

# PRD §3.9: program fine base amounts (cents).
PROGRAM_FINE_BASE_CENTS = {
    "VDMP_STANDARD": 250000,
    "VDMP_EXCESSIVE": 500000,
    "ECM": 250000,
    "HECM": 500000,
}

# PRD §3.3: EXPOSURE_BASED target multiplier over open exposure.
EXPOSURE_MULTIPLIER = 2

# PRD §3.6/§3.7: the network allows at most one cure per packet lineage.
MAX_CURES = 1
