"""Domain thresholds — numeric constants named in the PRD's calculation rules."""

THRESHOLDS = {
    # Production forecasting (PRD §3.3)
    "HISTORY_WINDOW_OCCURRENCES": 4,
    "PREP_BUFFER_PCT": 0.05,
    "DEFAULT_OCCUPANCY_PCT": 0.60,
    # Catering quote (PRD §3.8)
    "DIETARY_PREMIUM_CENTS": 300,
    "SERVICE_FEE_BASE_CENTS": 7500,
    "PER_COVER_STAFFING_CENTS": 25,
    "MINIMUM_ORDER_CENTS": 50000,
    "MARKUP_SMALL": 1.40,     # covers < 50
    "MARKUP_MEDIUM": 1.25,    # 50 <= covers < 200
    "MARKUP_LARGE": 1.15,     # covers >= 200
    "TIER_MEDIUM_MIN_COVERS": 50,
    "TIER_LARGE_MIN_COVERS": 200,
    # Weekly overtime (PRD §3.5)
    "WEEKLY_OT_THRESHOLD_MINUTES": 2400,
    "OT_MULTIPLIER": 1.5,
    "WORKED_MINUTES_GRACE": 60,
    # Inspection scoring (PRD §3.7)
    "DEMERIT_CRITICAL": 25,
    "DEMERIT_MAJOR": 10,
    "DEMERIT_MINOR": 3,
    "PASS_THRESHOLD": 70,
    "CONDITIONAL_THRESHOLD": 40,
    # Corrective-action due-date offsets in days (PRD §3.7)
    "DUE_DAYS_CRITICAL": 7,
    "DUE_DAYS_MAJOR": 14,
    "DUE_DAYS_MINOR": 30,
    # Sustainability (PRD §3.4)
    "ALERT_THRESHOLD_KG_PER_COVER": 0.15,
    # Labor rest buffer (PRD §3.5)
    "REST_BUFFER_MINUTES": 480,
    # Catering lead time / cancellation fee (PRD §3.8)
    "LEAD_TIME_HOURS": 48,
    "CANCEL_FEE_FAR_BPS": 1000,
    "CANCEL_FEE_NEAR_BPS": 2500,
    "CANCEL_FEE_FAR_HOURS": 72,
    "INVOICE_MIN_RATIO": 0.80,
    "INVOICE_MAX_RATIO": 1.20,
}

# Fixed start-of-day hour for each catering time slot (PRD §3.8).
SLOT_START_HOURS = {"BREAKFAST": 7, "LUNCH": 11, "DINNER": 17}

TEST_DEFAULTS = {
    # The logical clock reads exactly this instant before any client call (PRD §2.4).
    "DEFAULT_CLOCK_ISO": "2026-08-01T00:00:00Z",
    "DEFAULT_CLOCK_DATE": "2026-08-01",
}
