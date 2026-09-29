"""Domain thresholds and numeric constants drawn from the PRD's stated rules."""

POSTAGE = {
    "TIER_1_MAX_GRAMS": 28,
    "TIER_1_CENTS": 73,
    "TIER_2_MAX_GRAMS": 57,
    "TIER_2_CENTS": 129,
    "TIER_3_MAX_GRAMS": 85,
    "TIER_3_CENTS": 185,
    "OVERWEIGHT_STEP_GRAMS": 28,
    "OVERWEIGHT_STEP_CENTS": 56,
    "UOCAVA_SURCHARGE_RATE": 0.15,
    "FORWARDING_ENDORSEMENT_CENTS": 8,
    "RETURN_POSTAGE_PREPAID_CENTS": 68,
}

SIGNATURE = {
    "ON_FILE_STEP": 0.025,
    "ON_FILE_CAP": 0.10,
    "STALENESS_DAYS": 1460,
    "STALENESS_PENALTY": 0.05,
    "LEAD_BONUS": 0.03,
    "AUTO_ACCEPT_THRESHOLD": 0.72,
    "REJECT_FLOOR": 0.55,
    "MAX_ROUNDS": 3,
}

CANVASS = {
    "DAYS_STANDARD": 17,
    "DAYS_EXTENDED": 21,
    "EXTENDED_OPEN_CURE_THRESHOLD": 3,
}

REVIEWER = {
    "MAX_OPEN_REVIEWS": 12,
    "TRAINING_VALID_DAYS": 365,
}

ELECTION_DEFAULTS = {
    "POSTMARK_GRACE_DAYS": 7,
    "CURE_WINDOW_DAYS": 21,
}

ENROLLMENT = {
    "SUSPENSION_THRESHOLD": 2,
}

SECRECY = {
    "MIN_POOL": 3,
}

OBSERVER = {
    "MAX_CONCURRENT_PER_PARTY": 1,
    "MAX_CONCURRENT_TOTAL": 3,
}

REMAKE = {
    "CHANGEOVER_BUFFER_MINUTES": 15,
}

# The logical clock's default instant before any test sets it.
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

# The shared election world used by most setups.
TEST_ELECTION = {
    "name": "General 2026",
    "election_date": "2026-11-03",
    "uocava_send_deadline_date": "2026-09-19",
    "domestic_send_deadline_date": "2026-10-05",
    "return_deadline_at": "2026-11-03T20:00:00Z",
    "postage_budget_cents": 1_000_000,
    "postmark_grace_days": 7,
    "cure_window_days": 21,
}
