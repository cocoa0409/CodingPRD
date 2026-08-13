"""Domain thresholds and shared literals from the PRD's calculation rules
(PRD §2.4, §3.3-§3.9) and the standard event window used across tests.
"""

# --- Logical clock (PRD §2.4) ---
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"

# --- Standard event window used by the shared fixtures ---
EVENT_START = "2026-10-04T06:00:00Z"
EVENT_END = "2026-10-04T22:00:00Z"
EARLY_ACCESS_OPENS = "2026-08-10T00:00:00Z"
SIGNUP_OPENS = "2026-08-17T00:00:00Z"
SIGNUP_CLOSES = "2026-09-27T00:00:00Z"
# A convenient instant inside the general signup window (open to all)
IN_GENERAL_WINDOW = "2026-08-20T00:00:00Z"
# A convenient instant inside the early-access window (returning volunteers only)
IN_EARLY_ACCESS_WINDOW = "2026-08-12T00:00:00Z"
# After the signup window closed but before race day
AFTER_SIGNUP_CLOSES = "2026-09-28T00:00:00Z"

# --- Age (PRD §3.3) ---
GLOBAL_MIN_AGE = 14

# --- Temporal windows (PRD §3.5-§3.7) ---
CONFIRM_DEADLINE_HOURS = 48
CONFIRM_SHIFT_START_BUFFER_MINUTES = 60
CHECKIN_EARLY_MINUTES = 60
NO_SHOW_GRACE_MINUTES = 30
BACKFILL_WINDOW_MINUTES = 90
TRANSITION_BUFFER_MINUTES = 30

# --- Training validity in days (PRD §3.4) ---
VALIDITY_DAYS = {
    "SAFETY_BRIEFING": 30,
    "CAPTAIN_COURSE": 365,
    "MEDICAL_RESPONSE": 730,
}

# --- No-show strikes (PRD §3.7) ---
STRIKE_LIMIT = 2

# --- Hour rounding (PRD §3.8) ---
QUARTER_MINUTES = 15
CLAIMED_DECIMAL_PLACES = 2

# --- Fundraising credit tiers (PRD §3.8) ---
TIER1_LIMIT_HOURS = 100
TIER1_RATE_CENTS = 500
TIER2_LIMIT_HOURS = 500
TIER2_RATE_CENTS = 800
TIER3_RATE_CENTS = 1200

# --- Sponsor match (PRD §3.8) ---
MATCH_TIER_HIGH_CENTS = 250000
MATCH_TIER_HIGH_PCT = 0.25
MATCH_TIER_MID_CENTS = 50000
MATCH_TIER_MID_PCT = 0.15
MATCH_BASE_PCT = 0.05

# --- Recognition points (PRD §3.9) ---
POINTS_PER_HOUR = 10
CAPTAIN_BONUS = 25
RETURNING_BONUS = 50
NOSHOW_PENALTY = -15
TIER_BRONZE = 50
TIER_SILVER = 150
TIER_GOLD = 300
TIER_PLATINUM = 600

# --- Pagination defaults (PRD §2.3) ---
PAGE_DEFAULT_LIMIT = 10
PAGE_MIN_LIMIT = 1
PAGE_MAX_LIMIT = 100
PAGE_DEFAULT_OFFSET = 0

# --- A fixed non-existent identifier used by not-found tests ---
MISSING_UUID = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"
