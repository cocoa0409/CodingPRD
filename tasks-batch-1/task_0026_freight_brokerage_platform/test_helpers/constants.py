"""Domain thresholds derived from PRD §3.

These constants mirror values the PRD spells out by name (the SPOT tier rates
in §3.3, the detention rate floor in §3.6, the factoring-fee band cuts in §3.8,
and the SmartWay compliance thresholds in §3.8). Tests reference these
constants rather than hard-coding magic numbers so threshold-boundary
assertions remain traceable to the contract.
"""

# ─── Pricing: SPOT tiers and equipment uplift (PRD §3.3) ──────────
SPOT_TIER1_PER_MILE_CENTS = 320       # distance_miles <= 250
SPOT_TIER2_PER_MILE_CENTS = 235       # 251..750
SPOT_TIER3_PER_MILE_CENTS = 195       # >= 751
SPOT_FUEL_SURCHARGE_PER_MILE_CENTS = 65

EQUIPMENT_UPLIFT_PCT = {
    "DRY_VAN": 0,
    "REEFER": 18,
    "FLATBED": 10,
}

# ─── Detention math (PRD §3.6) ────────────────────────────────────
SPOT_DETENTION_FREE_MINUTES = 120
SPOT_DETENTION_RATE_PER_HOUR_CENTS = 7500

# ─── Quote-window buffer (PRD §3.3) ───────────────────────────────
QUOTE_WINDOW_PRE_PICKUP_BUFFER_MINUTES = 120

# ─── Carrier qualification (PRD §3.1) ─────────────────────────────
SAFETY_REJECT_THRESHOLD = 75.0

# ─── Factoring (PRD §3.8) ─────────────────────────────────────────
FACTORING_BASE_PCT = 2.0               # safety_score < 25
FACTORING_MID_PCT = 2.5                # 25 <= safety_score < 50
FACTORING_UPPER_PCT = 3.5              # 50 <= safety_score < 75
FACTORING_FEE_PCT_MAX = 10.0           # PRD §3.8 caps the requested fee at 10

# ─── Credit-risk weights (PRD §3.9) ───────────────────────────────
W_UTIL = 0.6
W_LATE = 5
W_DISPUTE = 8
LATE_AGE_DAYS = 30

# ─── SmartWay compliance bands (PRD §3.8) ─────────────────────────
SMARTWAY_PASS_THRESHOLD = 0.60
SMARTWAY_AT_RISK_THRESHOLD = 0.40

# ─── Convenience domain dictionaries (used by fixtures) ───────────
THRESHOLDS = {
    "SPOT_TIER1_PER_MILE_CENTS": SPOT_TIER1_PER_MILE_CENTS,
    "SPOT_TIER2_PER_MILE_CENTS": SPOT_TIER2_PER_MILE_CENTS,
    "SPOT_TIER3_PER_MILE_CENTS": SPOT_TIER3_PER_MILE_CENTS,
    "SPOT_FUEL_SURCHARGE_PER_MILE_CENTS": SPOT_FUEL_SURCHARGE_PER_MILE_CENTS,
    "SPOT_DETENTION_FREE_MINUTES": SPOT_DETENTION_FREE_MINUTES,
    "SPOT_DETENTION_RATE_PER_HOUR_CENTS": SPOT_DETENTION_RATE_PER_HOUR_CENTS,
    "SAFETY_REJECT_THRESHOLD": SAFETY_REJECT_THRESHOLD,
    "SMARTWAY_PASS_THRESHOLD": SMARTWAY_PASS_THRESHOLD,
    "SMARTWAY_AT_RISK_THRESHOLD": SMARTWAY_AT_RISK_THRESHOLD,
}
