"""Domain thresholds and numeric constants taken from the PRD's calculations.

Every value here is stated verbatim in PRD.md; nothing is inferred.
"""

# --- §3.3 Quantifying historical consumptive use -----------------------------
HCU = {
    "DITCH_EFFICIENCY": 0.65,          # DIVERSION_BASED per-year multiplier
    "CIR_AF_PER_ACRE": 2.10,           # CIR_BASED acre-feet per irrigated acre
    "FACE_VALUE_CAP_FACTOR": 0.65,     # authorized_diversion_af * 0.65
    "MIN_QUALIFYING_YEARS": 3,         # strictly fewer than 3 => haircut
    "SHORT_HISTORY_HAIRCUT": 0.85,
}

# --- §3.5 Injury analysis ----------------------------------------------------
INJURY = {
    "DEPLETION_FACTOR_INSTANT": 0.92,
    "DEPLETION_FACTOR_SEASONAL": 0.78,
    "DISTANCE_DECAY_PER_MILE": 0.015,
    "DISTANCE_FACTOR_FLOOR": 0.55,
    "MATERIALITY_AF": 0.01,            # unconditional approval gate
}

# --- §3.8 Mitigation fee pricing --------------------------------------------
MITIGATION_FEE = {
    "BASE_RATE_USD_PER_AF": 125.00,
    "TIER1_CEILING_USD": 5000.00,      # base_fee < 5000.00 => 0.040
    "TIER2_CEILING_USD": 20000.00,     # 5000.00 <= base_fee < 20000.00 => 0.070
    "SURCHARGE_TIER1": 0.040,
    "SURCHARGE_TIER2": 0.070,
    "SURCHARGE_TIER3": 0.095,
}

# --- §3.2 Forfeiture assessment ---------------------------------------------
FORFEITURE = {
    "LOOKBACK_YEARS": 10,
    "DE_MINIMIS_AF": 0.50,             # a used year needs >= 0.50 AF
    "NONUSE_WEIGHT": 9,
    "UNVERIFIED_WEIGHT": 25,
    "UNDERUSE_WEIGHT": 30,
    "SUSPENDED_PENALTY": 12,
    "METER_CREDIT": 10,
    "STATUTORY_FORFEITURE_YEARS": 5,   # inclusive: exactly 5 is eligible
    "BAND_HIGH_MIN": 70.00,
    "BAND_ELEVATED_MIN": 40.00,
}

# --- §3.9 Water banking and lease settlement --------------------------------
LEASE = {
    "SEASON_BLOCK_DAYS": 30,
    "FALLOW_BUFFER_DAYS": 7,           # closed exclusion window on both ends
}
BANK = {
    "LOW_CREDIT_FLOOR_AF": 5.00,       # strict: below 5.00 => RESTRICTED
}

# --- §3.10 Decreed volume waterfall -----------------------------------------
DECREE = {
    "OBJECTION_HAIRCUT": 0.90,
    "PRIORITY_MISMATCH_HAIRCUT": 0.90,
    "PRIORITY_TOLERANCE_DAYS": 366,    # strict: 366 within tolerance, 367 not
}

# --- §2.3 Pagination ---------------------------------------------------------
PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "DEFAULT_OFFSET": 0,
}

# --- §2.4 Logical clock ------------------------------------------------------
CLOCK_STARTUP_UTC = "2026-08-01T00:00:00Z"

# --- §3.4 Revision cycle -----------------------------------------------------
REVISION_ROUND_CAP = 2

# --- Values reused across the generated test scenarios ----------------------
TEST_DEFAULTS = {
    "CLOCK_BASE": "2026-03-01T00:00:00Z",
    "AUTHORIZED_DIVERSION_AF": 400.00,
    "AUTHORIZED_RATE_CFS": 5.000,
    "PLACE_OF_USE_ACRES": 120.00,
    "PRIORITY_DATE": "1901-05-01T00:00:00Z",
    "SOURCE_STREAM_CODE": "SNK-14",
    "REPORTED_DIVERSION_AF": 300.000,
    "IRRIGATED_ACRES": 100.00,
    # BASE RIGHT + DIVERSION_BASED 2023-2025 study certifies this volume.
    "CERTIFIED_HCU_AF": 195.00,
}
