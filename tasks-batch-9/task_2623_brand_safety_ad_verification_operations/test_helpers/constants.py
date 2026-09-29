"""Domain thresholds and numeric constants stated by the PRD."""

# ---------------------------------------------------------------------------
# Suitability ladder (PRD 2.5)
# ---------------------------------------------------------------------------
TIER_RANK = {
    "FLOOR": 0,
    "HIGH_RISK": 1,
    "MEDIUM_RISK": 2,
    "LOW_RISK": 3,
    "SAFE": 4,
}

CATEGORY_RISK_WEIGHTS = {
    "ADULT": 100,
    "TERRORISM": 100,
    "ILLEGAL_DRUGS": 100,
    "ARMS": 40,
    "CRIME_VIOLENCE": 40,
    "HATE_SPEECH": 40,
    "PIRACY": 40,
    "DEATH_INJURY": 15,
    "TOBACCO_ALCOHOL": 15,
    "GAMBLING": 15,
    "DEBATED_SOCIAL": 15,
    "NEWS_HARD": 5,
    "SPORTS_NEWS": 5,
    "GENERAL": 0,
}

SPECIFICITY_RANK = {"PAGE_URL": 4, "DOMAIN": 3, "PUBLISHER": 2, "CATEGORY": 1}

# ---------------------------------------------------------------------------
# Made-for-advertising scoring and risk arithmetic (PRD 3.3)
# ---------------------------------------------------------------------------
THRESHOLDS = {
    "MFA_DENSITY_WEIGHT": 0.4,
    "MFA_DENSITY_CAP": 40.00,
    "MFA_REFRESH_FAST_POINTS": 25.00,
    "MFA_REFRESH_MEDIUM_POINTS": 12.00,
    "MFA_REFRESH_FAST_MAX_SECONDS": 15,
    "MFA_REFRESH_MEDIUM_MAX_SECONDS": 30,
    "MFA_SOURCED_MAX": 20.00,
    "MFA_ORIGINALITY_WEIGHT": 0.15,
    "MFA_FLAG_THRESHOLD": 70.00,
    "MFA_RISK_MULTIPLIER": 1.5,
    "CONFIDENCE_INFLATION": 1.25,
    "MODEL_CONFIDENCE_FLOOR": 0.80,
    # Tier ladder boundaries on adjusted_risk_points
    "TIER_FLOOR_MIN_POINTS": 100.00,
    "TIER_HIGH_RISK_MIN_POINTS": 40.00,
    "TIER_MEDIUM_RISK_MIN_POINTS": 15.00,
    "TIER_LOW_RISK_MIN_POINTS": 5.00,
    # Measurement / invalid traffic
    "IVT_CONFIRM_CONFIDENCE_FLOOR": 0.75,
    "BATCH_WINDOW_BUFFER_SECONDS": 60,
    # Publisher standing
    "PUBLISHER_QUARANTINE_LIMIT": 3,
    "PUBLISHER_MFA_LIMIT": 3,
    # Appeals and claims
    "APPEAL_MAX_ROUNDS": 3,
    "APPEAL_FILING_WINDOW_DAYS": 14,
    "CLAIM_FILING_WINDOW_DAYS": 30,
    "ROLLUP_WINDOW_DAYS": 30,
    "AUDIT_PASS_MAX_FINDING_RATE": 0.05,
    # Money
    "ADMIN_FEE_TIER_BREAK_CENTS": 500000,
    "ADMIN_FEE_RATE_STANDARD": 0.15,
    "ADMIN_FEE_RATE_HIGH_VOLUME": 0.10,
    # Publisher quality index
    "QUALITY_IVT_WEIGHT": 2.0,
    "QUALITY_VIEWABILITY_TARGET": 0.70,
    "QUALITY_VIEW_WEIGHT": 1.5,
    "QUALITY_MFA_PENALTY": 5,
    "QUALITY_QUARANTINE_PENALTY": 3,
    "QUALITY_OVERTURN_CREDIT": 10,
    "TIER_BAND_PREFERRED_MIN": 85.00,
    "TIER_BAND_STANDARD_MIN": 60.00,
    "TIER_BAND_WATCHLIST_MIN": 40.00,
}

# ---------------------------------------------------------------------------
# Declared defaults (PRD 3.1, 3.2, 3.3)
# ---------------------------------------------------------------------------
DEFAULTS = {
    "ADVERTISER_CREDIT_CAP_CENTS": 1000000,
    "PUBLISHER_SOURCED_TRAFFIC_PCT": 0.0,
    "CAMPAIGN_TARGET_COVERAGE_RATE": 0.75,
    "DISPLAY_IN_VIEW_SECONDS": 1.0,
    "VIDEO_IN_VIEW_SECONDS": 2.0,
    "DISPLAY_PIXEL_PCT": 0.5,
    "LARGE_DISPLAY_PIXEL_PCT": 0.3,
    "VIDEO_PIXEL_PCT": 0.5,
    "COVERAGE_RATE_FLOOR": 0.7,
    "IVT_RATE_CEILING": 0.02,
    "MODEL_CONFIDENCE": 1.0,
}

# ---------------------------------------------------------------------------
# Logical clock (PRD 2.4): starts at this instant on every server start.
# ---------------------------------------------------------------------------
CLOCK_START = "2026-08-01T00:00:00Z"
CLOCK_DEFAULT_NOW = "2026-08-10T00:00:00Z"

TEST_DEFAULTS = {
    "CPM_CENTS": 875,
    "CREDIT_CAP_CENTS": 1000000,
    "MEASURED_IMPRESSIONS": 10000,
    "MEASURABLE_IMPRESSIONS": 8000,
    "IN_VIEW_IMPRESSIONS": 6000,
    "AVG_IN_VIEW_SECONDS": 1.2,
    "AVG_IN_VIEW_PIXEL_PCT": 0.6,
}
