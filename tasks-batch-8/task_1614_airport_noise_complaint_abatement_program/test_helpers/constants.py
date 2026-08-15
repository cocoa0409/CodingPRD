"""Domain thresholds — numeric constants stated in PRD 3.x and 2.4."""

# Logical clock startup value (PRD 2.4).
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

THRESHOLDS = {
    # Complainant standing window (PRD 3.1).
    "REPEAT_THRESHOLD": 10,
    "RESTRICTED_THRESHOLD": 25,
    "STANDING_WINDOW_DAYS": 90,
    # Correlation scoring (PRD 3.4).
    "STRICT_WINDOW_SEC": 300,
    "RELAXED_WINDOW_SEC": 1200,
    "SUBSTANTIATION_THRESHOLD": 60.0,
    # Event verification gates (PRD 3.3).
    "VERIFY_CONFIDENCE_MIN": 70.0,
    "UPTIME_FLOOR_PCT": 80.0,
    "UPTIME_WINDOW_MINUTES": 43200,
    # Retry limits (PRD 3.4, 3.3, 3.8).
    "REOPEN_LIMIT": 3,
    "RECLASSIFY_LIMIT": 2,
    "APPEAL_LIMIT": 2,
    "REOPEN_WINDOW_DAYS": 30,
    "APPEAL_WINDOW_DAYS": 30,
    # Notification program (PRD 3.5).
    "RESPONSE_MIN_CHARS": 20,
    "RESPONSE_SLA_DAYS": 10,
    "AUTO_NOTIFY_COMPLAINT_THRESHOLD": 5,
    "AUTO_NOTIFY_EVENT_THRESHOLD": 3,
    # Grant program (PRD 3.8).
    "TIER1_CAP_CENTS": 8_000_000,
    "TIER2_CAP_CENTS": 4_000_000,
    "ADMIN_FEE_CAP_CENTS": 250_000,
    "OFFER_EXPIRY_DAYS": 45,
    # Parcel exposure (PRD 3.7).
    "PRELIMINARY_ADJUST_DB": 1.5,
    "RESIDENTIAL_INCOMPATIBLE_DNL": 65.0,
    "COMPATIBLE_WITH_MEASURES_DNL": 60.0,
    "NONRES_INCOMPATIBLE_DNL": 75.0,
    "TIER1_DNL_FLOOR": 70.0,
}

TEST_DEFAULTS = {
    "ZONE_CODE": "Z1",
    "RUNWAY_CODE": "09L",
    "FUND_TOTAL_CENTS": 5_000_000,
    "INTAKE_OPENS": "2026-07-01T00:00:00Z",
    "INTAKE_CLOSES": "2026-09-30T00:00:00Z",
}
