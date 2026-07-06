"""Domain thresholds — numeric constants from PRD cost/vote/clock rules."""

# Cost estimation constants (PRD §3.4).
MIN_CONTINGENCY_PCT = 0.10
OVERHEAD_PCT = 0.05

# Vote tally constant (PRD §3.6, ranked Borda).
RANK_MAX_POINTS = 10

# Logical clock: startup default (PRD §2.8).
CLOCK_DEFAULT = "2026-03-01T00:00:00Z"

# Default cycle age floor (PRD §3.2).
DEFAULT_MIN_VOTER_AGE = 16

# A clock instant safely inside the sample cycle windows, used by fixtures.
CLOCK_MID = "2026-04-15T00:00:00Z"

# Language set (PRD §2.7).
LANGUAGES = ["en", "es", "zh", "vi", "ar"]
