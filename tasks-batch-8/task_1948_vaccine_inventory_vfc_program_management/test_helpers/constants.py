"""Domain thresholds and shared values from PRD §2.10, §2.11, §3."""

# Logical clock boot value (PRD §2.10): the server boots reading exactly this.
BOOT_CLOCK_UTC = "2026-08-01T00:00:00Z"

# Typical refrigerator range, inclusive bounds (PRD §3.2).
FRIDGE_MIN_C = 2.0
FRIDGE_MAX_C = 8.0

# Wastage-rate tier floors (PRD §3.9): GREEN < 0.05 <= AMBER < 0.10 <= RED.
TIER_AMBER_FLOOR = 0.05
TIER_RED_FLOOR = 0.10

# Shared defaults used across fixtures.
DEFAULT_EXPIRES_ON = "2027-06-30"
SHORT_EXPIRES_ON = "2026-08-10"
VISIT_DATE = "2026-08-05"
AUDIT_VISIT_DATE = "2026-08-10"
PEDIATRIC_DOB = "2020-01-15"          # age 6 on 2026-08-05
ADULT_BOUNDARY_DOB = "2007-08-05"     # turns exactly 19 on 2026-08-05
