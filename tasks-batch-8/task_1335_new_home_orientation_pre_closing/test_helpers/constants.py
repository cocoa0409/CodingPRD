"""Domain thresholds — numeric constants from the PRD's policy defaults and
calculation rules."""

# Logical clock startup default (PRD §2.4): before any client sets it, the
# clock starts at exactly this instant.
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"

# Community policy defaults (PRD §3.1).
COMMUNITY_DEFAULTS = {
    "holdback_cost_multiplier": 1.5,
    "holdback_min_cents": 50_000,
    "holdback_max_cents": 1_000_000,
    "orientation_min_days_before_closing": 5,
    "orientation_max_days_before_closing": 30,
    "appointment_duration_minutes": 120,
    "appointment_buffer_minutes": 30,
    "survey_window_days": 14,
    "cosmetic_photo_required": True,
}

# Rep policy defaults (PRD §3.1).
REP_DEFAULTS = {
    "active": True,
    "daily_visit_capacity_minutes": 240,
}

# Visit duration default (PRD §3.5).
DEFAULT_VISIT_DURATION_MINUTES = 60

# Hard cap on successful reschedules (PRD §3.2).
RESCHEDULE_LIMIT = 3

# Appointment start window: opens 30 minutes before scheduled_start and closes
# duration_minutes after it (PRD §3.3).
APPOINTMENT_START_EARLY_MINUTES = 30

# Survey composite weights and branches (PRD §3.8).
SURVEY_WEIGHTS = {"W_OVERALL": 0.5, "W_SYSTEMS": 0.3, "W_TIMELINESS": 0.2}
NO_RECOMMEND_PENALTY = 0.5
DETRACTOR_CAP = 2.0
COMPOSITE_MIN = 1.00
COMPOSITE_MAX = 5.00

MINUTES_PER_DAY = 1440
