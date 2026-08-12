"""Domain thresholds and shared default values from PRD calculations."""

# Standard rule-config values used by fixtures (PRD §3.1 mentions thirty
# months as the conventional ESRD setting and thirty days as a typical
# savings period length).
CONFIG_DEFAULTS = {
    "dependent_primacy_rule": "BIRTHDAY_RULE",
    "msp_employer_size_threshold": 20,
    "esrd_coordination_months": 30,
    "retroactive_lookback_months": 12,
    "recovery_window_days": 30,
    "savings_period_length_days": 30,
}

# Default logical clock at server startup (PRD §2.6).
DEFAULT_CLOCK_ISO = "2026-05-01T00:00:00Z"
DEFAULT_CLOCK_DATE_PREFIX = "2026-05-01T00:00:00"

# Survey due window: due_at = sent_at + 30 days (PRD §3.3).
SURVEY_DUE_DAYS = 30
