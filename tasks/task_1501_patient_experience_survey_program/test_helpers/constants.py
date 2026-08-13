"""Domain thresholds and fixture constants (PRD §2.4, §2.9, §3.3–§3.9)."""

# Logical clock (PRD §2.4): startup default before any explicit set.
CLOCK_DEFAULT_ISO = "2026-08-01T00:00:00Z"

THRESHOLDS = {
    # Top-box mathematics (PRD §3.6)
    "TOPBOX_RAW_MIN": 4,
    "TOPBOX_ADJUSTED_THRESHOLD": 3.75,
    "MODE_COEFF_MAIL": 0.0,
    "MODE_COEFF_PHONE": -0.5,
    # Star rating (PRD §3.6)
    "MIN_COMPLETED_FOR_RATING": 25,
    "RATE_CAP_THRESHOLD": 10.0,
    "RATE_CAP_MAX_STARS": 3,
    # Publication gate (PRD §3.6)
    "PUBLISH_MIN_COMPLETED": 25,
    "PUBLISH_MIN_RESPONSE_RATE": 10.0,
    # VBP projection (PRD §3.7)
    "VBP_FLOOR_PCT": 50.0,
    "VBP_BENCHMARK_PCT": 95.0,
    "POINTS_PER_COMPOSITE": 10,
    "MAX_TOTAL_POINTS": 40,
    "MAX_ADJUSTMENT_PCT": 2.0,
    # Service recovery SLA (PRD §3.9)
    "SLA_HOURS": 48,
}

# Standard eligible-discharge template used by nearly every fixture:
# HOME / MEDICAL / MEDICARE / age 65 / US / no_publicity false / custody NONE
# with an overnight stay (admit 06-01, discharge 06-03).
ELIGIBLE_TEMPLATE_BASE = {
    "admit_date": "2026-06-01",
    "discharge_date": "2026-06-03",
    "discharge_disposition": "HOME",
    "primary_dx_group": "MEDICAL",
    "payer": "MEDICARE",
    "age_years": 65,
    "address_country": "US",
    "no_publicity_flag": False,
    "custody_status": "NONE",
}

TEST_DEFAULTS = {
    "VENDOR_BUDGET_CENTS": 100000,
    "POSTAGE_COST_CENTS": 100,
    "TARGET_SAMPLE_SIZE": 100,
    # Canonical cycle windows: June discharge window, August fielding window.
    "DISCHARGE_WINDOW_START": "2026-06-01",
    "DISCHARGE_WINDOW_END": "2026-06-30",
    "FIELDING_START_DATE": "2026-08-03",
    "FIELDING_END_DATE": "2026-08-31",
    # Clock instants used to drive the fielding gates.
    "CLOCK_AT_FIELDING_END": "2026-08-31T00:00:00Z",
    "CLOCK_AFTER_FIELDING_END": "2026-09-05T00:00:00Z",
}

COMPOSITE_KEYS = ["nurse_comm", "doctor_comm", "cleanliness", "overall_rating"]
