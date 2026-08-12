"""Domain thresholds — numeric constants from PRD calculations (§3.6, §3.7, §3.8)."""

THRESHOLDS = {
    # Freight tiers (PRD §3.6)
    "FREIGHT_FLAT_MAX_GALLONS": 2000,
    "FREIGHT_FLAT_CENTS": 15000,
    "FREIGHT_MID_MAX_GALLONS": 6000,
    "FREIGHT_MID_TC_PER_GAL": 40,
    "FREIGHT_HIGH_TC_PER_GAL": 32,
    # Reconciliation default variance flag threshold (PRD §3.7)
    "DEFAULT_RECON_THRESHOLD_GALLONS": 130,
    # Brand audit pass boundary (PRD §3.4)
    "AUDIT_PASS_SCORE": 70,
    # Tax remittance late-filing (PRD §3.8)
    "LATE_PENALTY_RATE": 0.05,
    "DUE_DATE_LAG_DAYS": 20,
    # Renewal volume incentive (PRD §3.3)
    "RENEWAL_INCENTIVE_PCT": 0.01,
    "FULFILLMENT_THRESHOLD_PCT": 95.00,
    # Credit band (PRD §2.10)
    "WATCH_BAND_NUMERATOR": 4,    # exposure * 5 >= limit * 4
    "WATCH_BAND_DENOMINATOR": 5,
    # Tank settle buffer (PRD §3.6) — hours
    "TANK_SETTLE_HOURS": 4,
    # Cure window (PRD §3.4) — days
    "CURE_WINDOW_DAYS": 30,
    # Renewal window lead (PRD §3.3) — days
    "RENEWAL_WINDOW_LEAD_DAYS": 90,
}


TEST_DEFAULTS = {
    "CLOCK_START": "2026-05-01T00:00:00Z",
    "FED_EXCISE_GAS_TC": 184,
    "FED_EXCISE_DIESEL_TC": 244,
    "TEMP_COEFF_GAS": 0.00065,
    "TEMP_COEFF_DIESEL": 0.00040,
}
