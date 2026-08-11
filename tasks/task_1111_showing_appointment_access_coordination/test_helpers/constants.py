"""Domain thresholds — numeric constants from PRD calculation rules."""

# Default logical-clock reading at startup (before any operator set call).
CLOCK_START_ISO = "2026-05-01T00:00:00Z"

THRESHOLDS = {
    # Standing ladder (calc_agent_standing)
    "NO_SHOW_WEIGHT": 25,
    "LATE_CANCEL_WEIGHT": 10,
    "RESTRICT_POINTS": 15,
    "SUSPEND_POINTS": 30,
    "STRIKE_TTL_DAYS": 90,
    # Approval deadline (calc_approval_deadline)
    "MIN_REVIEW_WINDOW_MINUTES": 30,
    # Access windows (calc_access_window)
    "VACANT_EARLY_ENTRY_MINUTES": 60,
    "VACANT_EXIT_GRACE_MINUTES": 60,
    "OCCUPIED_EARLY_ENTRY_MINUTES": 15,
    # Confirm-by deadline: start_at - 60 minutes
    "CONFIRM_BY_LEAD_MINUTES": 60,
    # Late-cancel strike window: cancel < 24h before start
    "LATE_CANCEL_HOURS": 24,
    # Feedback due: sent_at + 72 hours
    "FEEDBACK_DUE_HOURS": 72,
    # Feedback score weights (calc_feedback_score_rollup)
    "W_Q1": 0.30,
    "W_Q2": 0.25,
    "W_Q3": 0.20,
    "W_Q4": 0.15,
    "W_Q5": 0.10,
}

TEST_DEFAULTS = {
    "SELLER_APPROVAL_TIMEOUT_MINUTES": 240,
    "SELLER_AUTO_APPROVE": False,
    "LISTING_BUFFER_MINUTES": 30,
    "LISTING_MAX_SHOWINGS_PER_DAY": 5,
    "LISTING_MIN_NOTICE_MINUTES": 120,
    "MAX_WINDOW_DURATION_MINUTES": 120,
}

# Instruction texts pinned by the PRD for each occupancy variant.
INSTRUCTIONS_VACANT = "Vacant property: self-access with lockbox/code anytime inside the access window."
INSTRUCTIONS_OCCUPIED = "Occupied property: occupant-approved access; arrive no earlier than 15 minutes before start."
