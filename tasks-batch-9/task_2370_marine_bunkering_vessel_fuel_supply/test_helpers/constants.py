"""Domain thresholds and pinned numeric constants from the PRD's calculations."""

# ─── Logical clock (PRD §2.4) ─────────────────────────

CLOCK_EPOCH = "2026-08-01T00:00:00Z"

# ─── Reference-data defaults (PRD §3.1, §3.2) ─────────

DEFAULTS = {
    "PORT_ECA_ZONE": False,
    "PORT_ECA_SULFUR_LIMIT_PCT": 0.100,
    "PORT_NOTICE_LEAD_HOURS": 24,
    "PORT_CONCURRENT_OPS_CAPACITY": 2,
    "PORT_SPILL_RESPONSE_TIER": "TIER_2",
    "GRADE_ECA_PERMITTED": False,
    "GRADE_TEST_TOLERANCE_PCT": 0.010,
    "QUOTE_SOURCE": "PLATTS",
    "ASSET_BOOM_CERTIFIED": False,
    "ASSET_SEGREGATED_TANKS": False,
    "ASSET_TURNAROUND_BUFFER_MINUTES": 90,
    "ASSET_COMPLIANCE_SCORE": 100.00,
    "ASSET_COMMITTED_QUANTITY_MT": 0.000,
    "CUSTOMER_PAYMENT_TERMS_DAYS": 30,
    "CUSTOMER_SETTLEMENT_BASIS": "SUPPLIER_FIGURES",
    "CUSTOMER_CREDIT_STATUS": "OK",
    "CUSTOMER_OUTSTANDING_BALANCE_USD": 0.00,
    "NOMINATION_SCRUBBER_FITTED": False,
}

# ─── Pagination (PRD §2.3) ────────────────────────────

PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "DEFAULT_OFFSET": 0,
}

# ─── Credit exposure (PRD §3.2) ───────────────────────

CREDIT_THRESHOLDS = {
    "HOLD_UTILISATION": 1.0000,
    "WATCH_UTILISATION": 0.8000,
}

# ─── Nomination intake and scheduling (PRD §3.3, §3.4) ─

SCHEDULING = {
    "MIN_WINDOW_HOURS": 6,
    "VESSEL_IMO_DIGITS": 7,
    "PUMPING_RATE_MT_PER_HOUR": 250,
    "HOSE_ALLOWANCE_MINUTES": 60,
}

# ─── Measurement (PRD §3.5) ───────────────────────────

MEASUREMENT = {
    "BARGE_METER_TOLERANCE_MT": 1.000,
}

# ─── Spill severity, penalties and the compliance score (PRD §3.6) ─

SPILL = {
    "MAJOR_VOLUME_LITERS": 100.00,
    "MAJOR_PENALTY_POINTS": 45.00,
    "MINOR_PENALTY_POINTS": 15.00,
}

COMPLIANCE_SCORE = {
    "BASE": 100.00,
    "DECAY_FULL_MAX_DAYS": 30,
    "DECAY_HALF_MAX_DAYS": 90,
    "DECAY_QUARTER_MAX_DAYS": 180,
    "WEIGHT_FULL": 1.00,
    "WEIGHT_HALF": 0.50,
    "WEIGHT_QUARTER": 0.25,
    "CLEAN_DELIVERY_BONUS": 1.00,
    "CLEAN_DELIVERY_BONUS_CAP": 10.00,
    "MIN": 0.00,
    "MAX": 100.00,
}

# ─── Delivery notes, samples and claims (PRD §3.7) ────

SAMPLE_RETENTION_DAYS = 90
CLAIM_WINDOW_DAYS = 30

# ─── Laboratory analysis and remediation (PRD §3.8) ───

REMEDIATION = {
    "MAX_ANALYSIS_ROUNDS": 2,
    "OFFSPEC_ALLOWANCE_PCT": 0.15,
    "DEBUNKER_HANDLING_USD_PER_MT": 12.00,
    "SEVERE_EXCEEDANCE_PCT": 0.050,
    "SEVERE_MULTIPLIER": 1.25,
    "CREDIT_CAP_PCT": 0.60,
}

# ─── Invoicing and the bunker adjustment factor (PRD §3.9) ─

INVOICE = {
    "ECA_SURCHARGE_USD_PER_MT": 4.25,
}

BAF = {
    "BASE": 0.020,
    "VOLATILITY_LOW_THRESHOLD": 0.05,
    "VOLATILITY_HIGH_THRESHOLD": 0.10,
    "VOLATILITY_STEP_NONE": 0.000,
    "VOLATILITY_STEP_MID": 0.010,
    "VOLATILITY_STEP_HIGH": 0.020,
    "MODE_PREMIUM_TRUCK": 0.015,
    "MODE_PREMIUM_BARGE": 0.005,
    "ECA_PREMIUM": 0.010,
    "TIER_DISCOUNT": 0.010,
    "TIER_DISCOUNT_MIN_MT": 1000.000,
    "FLOOR": 0.010,
    "CEILING": 0.045,
}

# ─── Rounding scales (PRD §2.10) ──────────────────────

SCALES = {
    "TONNAGE": 3,
    "MONEY": 2,
    "SULFUR": 3,
    "BAF_PCT": 4,
    "UTILISATION": 4,
}

__all__ = [
    "CLOCK_EPOCH",
    "DEFAULTS",
    "PAGINATION",
    "CREDIT_THRESHOLDS",
    "SCHEDULING",
    "MEASUREMENT",
    "SPILL",
    "COMPLIANCE_SCORE",
    "SAMPLE_RETENTION_DAYS",
    "CLAIM_WINDOW_DAYS",
    "REMEDIATION",
    "INVOICE",
    "BAF",
    "SCALES",
]
