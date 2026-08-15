"""Domain thresholds and pinned constants (PRD §2.4, §3.2, §3.5, §3.6)."""

# PRD §2.4: the logical clock's fixed startup default (never wall-clock).
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"
# Prefix form that tolerates the three-fractional-digit rendering of §2.5.
DEFAULT_CLOCK_PREFIX = "2026-08-01T00:00:00"

# PRD §3.2: per-level loading used by the REGRESSION_OLS level deflation.
LEVEL_LOADING = 0.04

# PRD §3.6: four-fifths rule threshold; a ratio exactly 0.8000 is not flagged.
FOUR_FIFTHS_THRESHOLD = 0.80

# PRD §3.1: optional study tuning knobs and their server-side defaults.
STUDY_DEFAULTS = {
    "significance_threshold": 0.05,
    "actionable_gap_pct": 2.0,
    "min_group_size": 30,
    "monitor_cadence_days": 180,
}

# PRD §3.5: EEO band edges in cents, lower-inclusive / upper-exclusive.
EEO_BAND_EDGES = [
    ("BAND_A", 0, 5000000),
    ("BAND_B", 5000000, 7500000),
    ("BAND_C", 7500000, 10000000),
    ("BAND_D", 10000000, 15000000),
    ("BAND_E", 15000000, None),
]

TEST_DEFAULTS = {
    "STUDY_NAME": "Study",
    "GROUP_NAME": "G1",
    "EFFECTIVE_DATE": "2026-09-01",
    "HIRE_DATE": "2020-01-01",
}
