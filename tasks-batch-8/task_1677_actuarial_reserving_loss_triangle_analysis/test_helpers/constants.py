"""Domain thresholds and shared constants from the PRD's calculation rules."""

# PRD §3.5: reserve range bounds are pinned fractions of IBNR.
RANGE_LOW_FACTOR = 0.75
RANGE_HIGH_FACTOR = 1.50

# PRD §2.6: factors, CDFs and percentages are carried at four decimal places.
RATIO_DECIMALS = 4

# PRD §3.4: the tail factor is exactly 1.0000 with fewer than three factors.
DEFAULT_TAIL_FACTOR = 1.0

# PRD §3.8: the filing deadline is sixty calendar days after the statement date.
FILING_DEADLINE_DAYS = 60

# PRD §2.5: logical clock default at server startup.
LOGICAL_CLOCK_DEFAULT = "2026-08-01T00:00:00Z"

# Canonical quarter labels used across the standard fixtures.
Q1_2025 = "2025-Q1"
Q2_2025 = "2025-Q2"
Q3_2025 = "2025-Q3"
Q4_2025 = "2025-Q4"
