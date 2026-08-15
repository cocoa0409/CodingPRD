"""Domain thresholds and fixed instants — numeric constants from PRD §2-§3."""

# Logical clock fixed default instant (PRD §2.4).
T0 = "2026-08-01T00:00:00Z"

# A wide availability window covering every timestamp used by happy-path setups.
WIDE_WINDOW_START = "2026-07-01T00:00:00Z"
WIDE_WINDOW_END = "2026-09-01T00:00:00Z"

THRESHOLDS = {
    # QA scoring (PRD §3.5)
    "QA_CRITICAL_WEIGHT": 25,
    "QA_MAJOR_WEIGHT": 5,
    "QA_MINOR_WEIGHT": 1,
    "QA_PASS_THRESHOLD": 80.0,
    # Transcript measurement (PRD §3.5)
    "CHARS_PER_LINE": 65,
    # ASR draft estimate (PRD §3.3)
    "ASR_CHARS_PER_SECOND": 2,
    # Editor standing (PRD §3.6)
    "STANDING_MIN_REVIEWS": 5,
    "ROLLING_WINDOW": 20,
    "PROBATION_BELOW": 85,
    "SUSPEND_FROM_ACTIVE_BELOW": 70,
    "SUSPEND_FROM_PROBATION_BELOW": 75,
    "RECOVERY_AT_LEAST": 90,
    "TIER_3_AT_LEAST": 95,
    # Clinic config defaults (PRD §3.1)
    "DEFAULT_UNSIGNED_REPORT_THRESHOLD": 3,
    "DEFAULT_AGING_TIER1_HOURS": 24,
    "DEFAULT_AGING_TIER2_HOURS": 72,
    "DEFAULT_PAYMENT_GRACE_DAYS": 14,
}

# max_concurrent_claims by skill tier / standing (PRD §3.6).
CAPACITY_BY_TIER = {"TIER_1": 1, "TIER_2": 3, "TIER_3": 5, "SUSPENDED": 0}

TEST_DEFAULTS = {
    "ROUTINE_TAT_MINUTES": 1440,
    "URGENT_TAT_MINUTES": 480,
    "STAT_TAT_MINUTES": 120,
    "AUDIO_DURATION_SECONDS": 60,
    "QA_REVIEWER_USER_ID": "qa-01",
}

# Exact-length text literals for line-count boundary work (65 chars per line).
TEXT_65_CHARS = "x" * 65
TEXT_66_CHARS = "x" * 66
TEXT_131_CHARS = "x" * 131


def iso_seconds_prefix(ts: str) -> str:
    """First 19 chars ('YYYY-MM-DDTHH:MM:SS') — deadline comparisons are made
    at second precision (PRD §2.8), regardless of fractional-digit rendering."""
    return ts[:19]
