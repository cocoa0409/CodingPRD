"""Domain thresholds and numeric constants stated in the PRD (§2.4, §3)."""

# Logical clock (PRD §2.4): startup default before any operator sets it.
CLOCK_DEFAULT_ISO = "2026-08-01T00:00:00Z"

THRESHOLDS = {
    # Atmospheric within-limits band (PRD §3.6, all bounds inclusive)
    "O2_MIN_PCT": 19.5,
    "O2_MAX_PCT": 23.5,
    "LEL_MAX_PCT": 10,
    "H2S_MAX_PPM": 10,
    "CO_MAX_PPM": 35,
    # Plausibility ranges (PRD §3.6)
    "O2_PLAUSIBLE_MAX": 30.0,
    "LEL_PLAUSIBLE_MAX": 100,
    "H2S_PLAUSIBLE_MAX": 500,
    "CO_PLAUSIBLE_MAX": 2000,
    # Alarm severity escalation floors (PRD §3.6)
    "ALARM_O2_LOW": 16,
    "ALARM_O2_HIGH": 25,
    "ALARM_LEL": 25,
    "ALARM_H2S": 20,
    "ALARM_CO": 100,
    # Temporal rules (PRD §3.3-§3.5)
    "PRE_ENTRY_MAX_AGE_MINUTES": 30,
    "VERIFICATION_TTL_HOURS": 12,
    "MONITORING_MAX_GAP_MINUTES": 15,
    "ROSTER_CHECKIN_EARLY_MINUTES": 15,
    "ROSTER_NO_SHOW_GRACE_MINUTES": 15,
    "REST_GAP_HOURS": 8,
    "STANDBY_CHECKIN_EARLY_MINUTES": 30,
    "STANDBY_NO_SHOW_GRACE_MINUTES": 15,
    # Pricing (PRD §3.8)
    "QUARTER_HOUR_MINUTES": 15,
    "AFTER_HOURS_START_UTC_HOUR": 19,
    "AFTER_HOURS_END_UTC_HOUR": 7,
    "CANCELLATION_FEE_RATIO": 0.5,
    # Exposure (PRD §3.7)
    "TWA_NORMALIZATION_MINUTES": 480,
    "TWA8_ACTION_PPM": 5,
    "TWA8_EXCEEDANCE_PPM": 10,
    "PEAK_ACTION_PPM": 10,
    "PEAK_EXCEEDANCE_PPM": 15,
}

# Default account rate knobs (PRD §3.1)
ACCOUNT_DEFAULTS = {
    "deployment_surcharge_cents": 50000,
    "minimum_billable_hours": 4,
    "tier1_hours_threshold": 8,
    "tier2_multiplier": 1.5,
    "after_hours_multiplier": 1.5,
    "weekend_multiplier": 2.0,
}

TEST_DEFAULTS = {
    "HOURLY_RATE_CENTS": 20000,
    "EVENT_BASE_FEE_CENTS": 150000,
    "EVENT_PER_RESCUER_CENTS": 25000,
    "CREDIT_LIMIT_CENTS": 100000000,
    "MAX_DUTY_HOURS": 12,
}
