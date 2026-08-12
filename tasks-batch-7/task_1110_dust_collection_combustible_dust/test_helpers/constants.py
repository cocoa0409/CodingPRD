"""Domain thresholds — numeric constants from the PRD's calculation rules."""

THRESHOLDS = {
    # Kst classification bands, default NFPA variant (PRD §3.2)
    "ST1_MAX": 200,
    "ST2_MAX": 300,
    # Kst classification bands, insurer-conservative variant (insurer_id prefix "IC-")
    "IC_ST1_MAX": 150,
    "IC_ST2_MAX": 250,
    "IC_INSURER_PREFIX": "IC-",
    # Explosion-protection design (PRD §3.3)
    "PSTAT_BAR_G": 0.1,
    "MIN_PRED": 0.05,
    "LARGE_VESSEL_VOLUME_M3": 25,
    "LARGE_VESSEL_MULTIPLIER": 1.20,
    # Differential-pressure trend derivation (PRD §3.3)
    "DP_HIGH_ALARM": 6.0,
    "DP_SLOPE_DELTA": 1.5,
    "DP_LOOKBACK": 5,
    "FILTER_MAX_AGE_DAYS": 180,
    # Housekeeping schedule (PRD §3.5)
    "DUE_SOON_WINDOW_HOURS": 24,
    # Hot-work permits (PRD §3.6)
    "FIRE_WATCH_MIN_MINUTES": 30,
    "PERMIT_MAX_WINDOW_HOURS": 24,
    # Site posture derivation (PRD §2.4)
    "COMPLIANT_MIN": 85,
    "CONDITIONAL_MIN": 60,
    "STOP_WORK_CRITICALS": 2,
    # Retrofit contingency tier rates (PRD §3.8)
    "RATE_LOW": 0.05,
    "RATE_MEDIUM": 0.12,
    "RATE_HIGH": 0.22,
    # DHA risk score (PRD §3.4)
    "RISK_SCORE_CAP": 100,
}

# Logical clock reads this instant at server start (PRD §2.11)
CLOCK_START_ISO = "2026-05-01T00:00:00Z"

TEST_DEFAULTS = {
    "SCOPE_BUDGET_CENTS": 100000,
    "LINE_COST_CENTS": 1000,
    "TARGET_ACCUMULATION": 1.0,
    "FREQUENCY_HOURS": 24,
}
