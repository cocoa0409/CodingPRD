"""Domain thresholds — numeric constants from the PRD's scoring and scheduling rules."""

# Fall-risk scoring (PRD §3.2)
POLYPHARMACY_THRESHOLD = 4      # medication_count >= 4 earns medication points
HIGH_TIER_THRESHOLD = 50        # clinical_score >= 50 -> HIGH
MODERATE_TIER_THRESHOLD = 25    # clinical_score >= 25 -> MODERATE

# Visit targets by tier (PRD §3.3)
HIGH_TARGET_VISITS = 12
MODERATE_TARGET_VISITS = 8
LOW_TARGET_VISITS = 4

# Home-hazard scoring (PRD §3.7)
HAZARD_HIGH_THRESHOLD = 20      # home_hazard_score >= 20 -> HIGH
HAZARD_MODERATE_THRESHOLD = 10  # home_hazard_score >= 10 -> MODERATE

# Room scheduling (PRD §3.5)
ROOM_TURNOVER_BUFFER_MINUTES = 15

# Logical-clock default at startup (PRD §2.9)
CLOCK_STARTUP_DEFAULT = "2026-05-01T00:00:00Z"

# A stable clock value used by fixtures so scheduling windows are deterministic.
TEST_CLOCK = "2026-06-01T00:00:00Z"
