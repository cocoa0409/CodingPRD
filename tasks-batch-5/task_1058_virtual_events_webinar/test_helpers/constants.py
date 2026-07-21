"""Numeric thresholds and rates the PRD's calculations depend on."""

# --- The logical clock ----------------------------------------------------
# Before any client sets it, the logical clock reads exactly this instant.
DEFAULT_CLOCK_UTC = "2026-07-01T00:00:00Z"

# --- Seat pricing (PRD 3.4) ----------------------------------------------
PRICING = {
    "VIP_SURCHARGE_CENTS": 5000,
    "EARLY_BIRD_DISCOUNT_PCT": 0.20,
    "GROUP_DISCOUNT_PCT": 0.10,
    "GROUP_MIN_SIZE": 5,
    "MAX_TOTAL_DISCOUNT_PCT": 0.25,
    "PROCESSING_FEE_PCT": 0.03,
    "PROCESSING_FEE_MIN_CENTS": 100,
    "PROCESSING_FEE_MAX_CENTS": 2500,
}

# --- Attendance resolution (PRD 3.3 / 3.10) ------------------------------
ATTENDANCE_MIN_MINUTES = 15

# --- Lead scoring (PRD 3.8) ----------------------------------------------
LEAD_SCORING = {
    "BOOTH_VISIT_WEIGHT": 3,
    "DOC_DOWNLOAD_WEIGHT": 5,
    "SESSION_MINUTE_WEIGHT": 0.5,
    "MEETING_ACCEPTED_WEIGHT": 12,
    "LEAD_SCORE_CAP": 100,
    "HOT_LEAD_THRESHOLD": 60,
}

# --- Sponsorship invoice (PRD 3.11) --------------------------------------
SPONSOR_BILLING = {
    "PACKAGE_PRICE_CENTS_BRONZE": 250000,
    "PACKAGE_PRICE_CENTS_SILVER": 500000,
    "PACKAGE_PRICE_CENTS_GOLD": 900000,
    "LEAD_OVERAGE_UNIT_CENTS": 137.5,
    "BOOTH_STREAM_UNIT_CENTS": 4.25,
    "SPONSOR_TAX_PCT": 0.0825,
}

# --- Organizer invoice (PRD 3.11) ----------------------------------------
EVENT_BILLING = {
    "STREAMING_RATE_CENTS_PER_MINUTE": 4,
    "PLATFORM_FEE_PCT": 0.08,
    "VOLUME_TIER_1_CENTS": 100000,
    "VOLUME_TIER_1_DISCOUNT_PCT": 0.10,
    "VOLUME_TIER_2_CENTS": 250000,
    "VOLUME_TIER_2_DISCOUNT_PCT": 0.15,
    "PLATFORM_FEE_MIN_CENTS": 500,
}

# --- Interval geometry (PRD 2.10) ----------------------------------------
SPEAKER_TRANSITION_BUFFER_MINUTES = 10
MATCH_EXPIRY_LEAD_MINUTES = 60
MAX_CONCURRENT_MEETINGS_PER_REGISTRATION = 1

# --- Pagination (PRD 2.3) -------------------------------------------------
PAGINATION = {"DEFAULT_LIMIT": 10, "MIN_LIMIT": 1, "MAX_LIMIT": 100, "DEFAULT_OFFSET": 0}

# --- Common test values ---------------------------------------------------
TEST_DEFAULTS = {
    "GENERAL_PRICE_CENTS": 20000,
    # 20000 -> no discount -> fee round(600) = 600 -> 20600
    "GENERAL_AMOUNT_DUE_CENTS": 20600,
    "EVENT_CAPACITY": 25,
    "TICKET_QUOTA": 10,
    "PAST_EARLY_BIRD": "2026-06-01T00:00:00Z",
    "FUTURE_EARLY_BIRD": "2026-08-01T00:00:00Z",
}

# --- Operator identities --------------------------------------------------
ORGANIZER_USER_ID = "org-1"
OTHER_ORGANIZER_USER_ID = "org-2"
PLATFORM_ADMIN_USER_ID = "adm-1"
FINANCE_ADMIN_USER_ID = "fin-1"
SECOND_FINANCE_ADMIN_USER_ID = "fin-2"
