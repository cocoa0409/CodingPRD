"""Domain thresholds and shared constants from the PRD."""

# Logical clock (PRD §2.6): startup default; the server never reads wall clock.
CLOCK = {
    "STARTUP_DEFAULT": "2026-08-01T00:00:00Z",
}

# Standard application window used across fixtures (opens exactly at the
# startup-default instant, so publish succeeds immediately at the default clock).
WINDOW = {
    "OPEN_AT": "2026-08-01T00:00:00Z",
    "CLOSE_AT": "2026-09-15T00:00:00Z",
}

# Reminder cadence (PRD §3.3): offsets before the program close.
REMINDER_OFFSET_DAYS = {"D14": 14, "D7": 7, "D1": 1}

# Committee ranking (PRD §3.5): deep-need bonus and score cap.
DEEP_NEED_BONUS = 5
SCORE_CAP = 100

# Award offers (PRD §3.6): offers expire 14 days after creation.
OFFER_EXPIRY_DAYS = 14

# Disbursement split (PRD §3.7): each term spans 180 days, closed intervals.
TERM_DAYS = 180

# Thank-you letters (PRD §3.9): due 30 days after full disbursement.
THANK_YOU_DUE_DAYS = 30

# Pagination envelope (PRD §2.3).
PAGINATION = {"DEFAULT_LIMIT": 10, "MIN_LIMIT": 1, "MAX_LIMIT": 100, "DEFAULT_OFFSET": 0}

# Money/GPA conventions (PRD §2.5): GPA range in integer hundredths.
GPA_MIN_HUNDREDTHS = 0
GPA_MAX_HUNDREDTHS = 500

# Default committee-flow cycle window (kept clear of program window dates).
CYCLE_WINDOW = {"STARTS_ON": "2026-09-16", "ENDS_ON": "2026-10-15"}

# Standard operator identities used by segregation-of-duties scenarios.
COORDINATOR_USER_ID = "coord_1"
COORDINATOR_ALT_USER_ID = "coord_9"
FAO_USER_ID = "fao_1"
FAO_ALT_USER_ID = "fao_2"
FAO_APPROVER_USER_ID = "fao_7"
REVIEWER_USER_IDS = ["rev_1", "rev_2", "rev_3"]
ADMIN_USER_ID = "admin_1"

# Canonical non-existent UUID for 404 probes.
MISSING_UUID = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"
