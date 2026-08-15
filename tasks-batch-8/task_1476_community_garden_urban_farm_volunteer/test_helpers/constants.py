"""Domain thresholds and shared scenario values (PRD §2.5, §2.9, §3)."""

# Fixed logical-clock startup value (PRD §2.5).
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

# Standard season used across scenarios (PRD §3.3). The operating window
# [2026-08-01, 2026-11-30] contains every shift/harvest/irrigation instant used.
SEASON_NAME = "2026 Summer"
SIGNUP_OPENS_AT = "2026-07-01T00:00:00Z"
SIGNUP_CLOSES_AT = "2026-08-10T00:00:00Z"
SEASON_STARTS_AT = "2026-08-01T00:00:00Z"
SEASON_ENDS_AT = "2026-11-30T00:00:00Z"
DEFAULT_WATER_BUDGET = 1000

# Standard 3-hour weekday shift inside the season window (PRD §3.5).
SLOT_DATE = "2026-08-15"
SLOT_STARTS_AT = "2026-08-15T09:00:00Z"
SLOT_ENDS_AT = "2026-08-15T12:00:00Z"
SLOT_SCHEDULED_MINUTES = 180  # 09:00..12:00 whole minutes

# An instant comfortably inside the check-in window
# [starts_at - 30 minutes, ends_at] of the standard slot (PRD §3.5).
CHECKIN_CLOCK = "2026-08-15T09:10:00Z"

# Harvest scenario: an in-window past harvest instant and the "current" clock
# used once the season reaches HARVESTING (PRD §3.8).
HARVEST_CLOCK = "2026-09-15T12:00:00Z"
HARVESTED_AT = "2026-09-15T10:00:00Z"

# Domain constants fixed by PRD §2.9 / §3.
THRESHOLDS = {
    "SUPERVISION_RATIO": 8,          # ceil(minor_count / 8) required chaperones
    "GRACE_MINUTES": 30,             # checkout credit cap: scheduled + 30
    "NO_SHOW_THRESHOLD": 3,          # 3rd no-show drops GOOD -> PROBATION
    "VOLUNTEER_SHARE_PCT": 0.20,     # floor(weight * 0.20) volunteer share
    "BED_BUFFER_DAYS": 14,           # cover-crop buffer between occupancy windows
    "KEY_REGISTRY_MAX": 4,           # max non-RETIRED shed keys
    "KEYS_PER_VOLUNTEER": 1,         # one held key per volunteer
    "VARIANCE_NUMERATOR": 1.10,      # floor(planned * 1.10) variance threshold
    "WAIVER_VALIDITY_DAYS": 365,     # SIGNED -> EXPIRED after > 365 days
}

TEST_DEFAULTS = {
    "ADULT_DOB": "1990-05-20",   # adult at the default clock
    "MINOR_DOB": "2012-03-01",   # 14 at the default clock
    "BED_CODE": "B-01",
    "BED_SIZE": 100,
    "BED_ZONE": "Z1",
    "CROP_TYPE": "Tomato",
    "PLANT_FAMILY": "Solanaceae",
    "PLAN_SQ_FT": 60,
    "PLAN_START": "2026-08-01",
    "PLAN_END": "2026-09-01",
    "CERT_EXPIRES_AT": "2027-08-01T00:00:00Z",
    "TASK_TYPE": "WEEDING",
    "RECIPIENT_CAPACITY": 100000,
}
