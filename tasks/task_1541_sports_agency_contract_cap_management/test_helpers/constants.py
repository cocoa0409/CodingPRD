"""Domain thresholds — numeric constants from the PRD's calculation rules."""

# Endorsement fee tiers (PRD section 3.8: the base rate tiers on deal size).
TIER1_MAX_CENTS = 100_000_000      # the one-million-dollar line
TIER1_RATE = 0.10
TIER2_MAX_CENTS = 500_000_000      # the five-million-dollar line
TIER2_RATE = 0.15
TIER3_RATE = 0.20

# Transition split (PRD section 3.2): outgoing 25%, incoming 75%.
OLD_AGENT_SPLIT = 0.25
NEW_AGENT_SPLIT = 0.75

# Contract field constraints (PRD section 3.4).
MIN_YEARS = 1
MAX_YEARS = 5
MAX_ESCALATOR_PCT = 0.15

# Logical clock boot instant (PRD section 2.5).
BOOT_CLOCK_ISO = "2026-08-01T00:00:00Z"
BOOT_SEASON_YEAR = 2026
