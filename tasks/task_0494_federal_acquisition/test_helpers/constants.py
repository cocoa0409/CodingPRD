"""Domain thresholds and numeric constants from the Federal Acquisition PRD.

These mirror the numbers stated verbatim in the PRD's scoring (§2.8, §3.3),
fee (§3.5), and performance-index (§3.7) workflows.
"""

# Acceptability floor (PRD §2.8): minimum acceptable raw score on any non-price factor.
ACCEPTABILITY_MIN = 70

# Value-score blend weights (PRD §3.3): merit weighted 0.80, price weighted 0.20.
MERIT_WEIGHT = 0.80
PRICE_WEIGHT = 0.20

# CPARS rating -> numeric value mapping (PRD §3.7).
CPARS_RATING_VALUES = {
    "EXCEPTIONAL": 100,
    "VERY_GOOD": 85,
    "SATISFACTORY": 70,
    "MARGINAL": 50,
    "UNSATISFACTORY": 0,
}

# Logical-clock startup default (PRD §2.4).
CLOCK_STARTUP_DEFAULT = "2026-01-01T00:00:00Z"

# A syntactically valid UUID that resolves to no resource.
NON_EXISTENT_UUID = "00000000-0000-4000-8000-000000000000"
