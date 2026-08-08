"""Domain constants and defaults from the PRD calculations (§2.8, §3)."""

# Disclosure obligations are due term_start_date + 30 days (PRD §3.6).
DISCLOSURE_DUE_DAYS = 30
# Consecutive-run tie tolerance: predecessor end + 1 day (PRD §3.8).
CONSECUTIVE_GAP_DAYS = 1
# A new meeting must be at least 24h from any other board meeting (PRD §3.5).
MEETING_MIN_GAP_HOURS = 24
# max_holdover_days default when omitted at board creation (PRD §3.1).
DEFAULT_MAX_HOLDOVER_DAYS = 90

# Reusable board default matching the design-index recipes.
DEFAULT_BOARD = {
    "name": "Zoning Board",
    "jurisdiction": "Springfield",
    "board_type": "COMMISSION",
    "authorized_seat_count": 5,
    "quorum_count": 3,
    "term_length_months": 48,
    "max_consecutive_terms": 2,
    "max_cumulative_years": 12,
    "attendance_threshold_pct": 75.0,
    "sunshine_notice_days": 7,
}
