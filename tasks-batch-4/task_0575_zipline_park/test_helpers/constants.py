"""Domain thresholds and time anchors — numeric constants from PRD §2, §3."""

# Logical clock: startup default (PRD §2.5).
DEFAULT_CLOCK = "2026-05-01T00:00:00Z"

# Canonical slots used by the design chains.
WEEKDAY_SLOT_START = "2026-06-03T10:00:00Z"   # Wednesday UTC
WEEKEND_SLOT_START = "2026-06-06T10:00:00Z"   # Saturday UTC

# Constants named by the PRD calculations and rules.
THRESHOLDS = {
    "WAIVER_VALID_DAYS": 365,             # PRD §3.3
    "CLEANING_BUFFER_MINUTES": 30,        # PRD §3.8
    "VOLUNTARY_FULL_REFUND_HOURS": 24,    # PRD §3.6
    "VOLUNTARY_LATE_REFUND_PCT": 0.5,     # PRD §3.6
    "INSURANCE_RATE": 0.0745,             # PRD §3.7
}

# Group-discount tiers keyed by expected_size band (PRD §3.4).
GROUP_TIERS = {
    "TIER_1_MAX": 3,     # size 1..3 -> 0.00
    "TIER_1_PCT": 0.00,
    "TIER_2_MAX": 7,     # size 4..7 -> 0.10
    "TIER_2_PCT": 0.10,
    "TIER_3_PCT": 0.20,  # size 8+  -> 0.20
}

# Default course shape used across the design chains.
COURSE_DEFAULTS = {
    "name": "Zip A",
    "difficulty_level": 2,
    "min_weight_kg": 30,
    "max_weight_kg": 120,
    "min_age_years": 8,
    "base_price_cents": 5000,
    "duration_minutes": 90,
    "default_capacity": 4,
    "max_participants_per_guide": 4,
    "weekend_surcharge_pct": 0.15,
}
