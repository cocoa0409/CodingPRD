"""Domain thresholds and shared values — numeric constants from the PRD."""

# Logical clock (PRD §2.5): startup default.
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

# A session start comfortably inside business hours (PRD §3.6: business hours
# run 08:00 up to but not including 18:00 UTC) and safely ahead of the startup
# clock, used where a test's expected price assumes no after-hours multiplier.
BUSINESS_START_ISO = "2026-08-01T10:00:00Z"

# Threshold classification (PRD §3.2).
SAFE_HARBOR_SHARE = 0.05
SAFE_HARBOR_COUNT = 1000
PRIORITY_ENCOUNTER_SHARE = 0.05

# Interpretation pricing (PRD §3.6).
BILLING_INCREMENT_MIN = 6
MIN_MINUTES = {"PHONE": 15, "VIDEO": 15, "IN_PERSON": 60}
TIER_MULTIPLIER = {"PROVISIONAL": 0.85, "REGISTERED": 1.0, "CERTIFIED": 1.15}
AFTER_HOURS_MULTIPLIER = 1.5
IN_PERSON_BUFFER_MIN = 30
IN_PERSON_LEAD_HOURS = 2

# Translation pricing (PRD §3.4).
REVISION_PCT_PER_CYCLE = 0.10
REVISION_PCT_CAP = 0.30
RUSH_MULTIPLIER = 1.25

# Scoring (PRD §3.1, §3.5).
SUBSTANTIATED_PENALTY = 150
UNFULFILLED_PENALTY = 50
ON_TIME_RESOLUTION_BONUS = 100
COMPLETION_BONUS = 5
SUBSTANTIATED_LINKED_PENALTY = 200
SUSPENSION_THRESHOLD = 600
REINSTATEMENT_FLOOR = 600
WATCH_FLOOR = 600
GOOD_STANDING_FLOOR = 800
SCORE_CAP = 1000

# Confidentiality currency (PRD §3.5).
CONFIDENTIALITY_TTL_DAYS = 365

# Contract exhaustion (PRD §3.3).
EXHAUSTION_PCT = 0.9

# Standard rate card used by most fixtures (PRD §3.3).
RATE_CARD = {
    "phone_per_minute_cents": 50,
    "video_per_minute_cents": 75,
    "in_person_per_minute_cents": 100,
    "translation_per_word_cents": 20,
    "in_person_travel_flat_cents": 2500,
}
