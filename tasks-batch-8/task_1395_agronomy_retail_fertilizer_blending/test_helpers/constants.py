"""Domain thresholds — numeric constants from PRD calculation rules."""

THRESHOLDS = {
    # Nutrient recommendation rates (PRD 3.2)
    "P_CRITICAL_PPM": 20,
    "P_DRAWDOWN_PPM": 40,
    "P_BUILD_LBS_PER_PPM": 9,
    "P2O5_REMOVAL_LB_PER_BU": 0.37,
    "K_CRITICAL_PPM": 130,
    "K_DRAWDOWN_PPM": 170,
    "K_BUILD_LBS_PER_PPM": 4,
    "K2O_REMOVAL_LB_PER_BU": 0.27,
    "N_LB_PER_BU": 1.0,
    "PREV_SOYBEAN_N_CREDIT": 30,
    # Batch variance (PRD 3.6)
    "BATCH_VARIANCE_TOLERANCE_PCT": 0.05,
    # Blender occupancy buffer (PRD 3.5)
    "CLEANUP_BUFFER_MINUTES": 30,
    # Seasonal volume rebate tiers (PRD 3.6)
    "REBATE_TIER1_MIN_TONS": 50,
    "REBATE_TIER1_PCT": 0.02,
    "REBATE_TIER2_MIN_TONS": 150,
    "REBATE_TIER2_PCT": 0.035,
}

TEST_DEFAULTS = {
    # Logical clock startup default (PRD 2.6)
    "CLOCK_START": "2026-08-01T00:00:00Z",
    # Standard published price-sheet window covering the default clock
    "SHEET_FROM": "2026-08-01T00:00:00Z",
    "SHEET_TO": "2026-12-01T00:00:00Z",
    "UREA_PRICE_CENTS": 52000,
    "DAP_PRICE_CENTS": 61000,
    "MOP_PRICE_CENTS": 44500,
    "UREA_ANALYSIS": {"analysis_n_pct": 46, "analysis_p2o5_pct": 0, "analysis_k2o_pct": 0, "form": "DRY"},
    "DAP_ANALYSIS": {"analysis_n_pct": 18, "analysis_p2o5_pct": 46, "analysis_k2o_pct": 0, "form": "DRY"},
    "MOP_ANALYSIS": {"analysis_n_pct": 0, "analysis_p2o5_pct": 0, "analysis_k2o_pct": 60, "form": "DRY"},
    "SOIL_P_PPM": 12,
    "SOIL_K_PPM": 90,
    "SOIL_PH": 6.1,
    "REC_VALID_UNTIL": "2027-06-01T00:00:00Z",
    "NMP_VALID_FROM": "2026-01-01T00:00:00Z",
    "NMP_VALID_TO": "2026-12-31T00:00:00Z",
    "PERMIT_EXPIRES": "2027-12-31T00:00:00Z",
    "SITE_CODE": "SITE-1",
    # Prepay program window used across prepay scenarios (PRD 3.9)
    "PREPAY_ENROLL_OPEN": "2026-07-01T00:00:00Z",
    "PREPAY_ENROLL_CLOSE": "2026-10-31T00:00:00Z",
    "PREPAY_FUNDING_DEADLINE": "2026-11-15T23:59:59Z",
    "PREPAY_DEPOSIT_PCT": 0.30,
    "PREPAY_DISCOUNT_PCT": 0.05,
    "PREPAY_PENALTY_PCT": 0.10,
}
