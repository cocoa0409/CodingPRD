"""Domain thresholds — numeric constants from the PRD calculations."""

THRESHOLDS = {
    # PRD §3.1: risk trend factors for the TREND expected-bushels variant
    "RISK_TREND_FACTOR": {"CONSERVATIVE": 0.98, "BALANCED": 1.00, "AGGRESSIVE": 1.02},
    # PRD §2.7: risk-profile coverage ceilings
    "RISK_COVERAGE_CAP": {"CONSERVATIVE": 0.60, "BALANCED": 0.80, "AGGRESSIVE": 1.00},
    # PRD §2.10 / §3.5: per-bushel margin rates by instrument
    "IM_RATE_FUTURES_SHORT": 0.30,
    "MM_RATE_FUTURES_SHORT": 0.22,
    "LONG_PUT_MARGIN_PREMIUM_ADDON": 0.05,
    # PRD §3.4: PROPOSED recommendation time-to-live in days
    "RECOMMENDATION_TTL_DAYS": 5,
    # PRD §3.8: moisture shrink base and per-point shrink
    "MOISTURE_BASE_PCT": 15.0,
    "SHRINK_PER_POINT": 0.012,
    # PRD §3.8: over-delivery tolerance multiplier
    "OVER_DELIVERY_TOLERANCE": 1.02,
    # PRD §2.8: storage bin buffer in days
    "STORAGE_BIN_BUFFER_DAYS": 7,
}

TEST_DEFAULTS = {
    "CROP_YEAR": 2026,
    "CONTRACT_MONTH": "2026-12",
    "PLANTED_ACRES": 100,
    "APH_YIELD": 200.0,
    "TREND_YIELD": 205.0,
    "FLAT_ANNUAL_FEE": 1000.0,
    "FIXED_PRICE": 4.50,
    "WINDOW_START": "2026-10-01",
    "WINDOW_END": "2026-11-01",
    "DELIVERY_DATE": "2026-10-10",
}

# A well-formed UUID that never resolves to a persisted resource.
MISSING_UUID = "11111111-2222-4333-8444-555555555555"
