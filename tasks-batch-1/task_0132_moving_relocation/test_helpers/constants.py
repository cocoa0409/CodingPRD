"""Domain thresholds — numeric constants from the PRD pricing engine.

All money is integer cents. These mirror the constants stated in the PRD's
pricing, valuation, storage, and settlement descriptions.
"""

# ─── cubic_feet_rollup (PRD §3.2) ─────────────────────────────────────────────
DENSITY_LBS_PER_CF = 7

# ─── packing_total (PRD §3.3) ─────────────────────────────────────────────────
CRATE_FEE_CENTS = 9500

# ─── valuation_premium (PRD §3.4) ─────────────────────────────────────────────
RATE_PER_100_CENTS = 110           # $1.10 per $100 of declared value
MIN_PREMIUM_CENTS = 7500           # $75 floor
DEDUCTIBLE_CREDIT = {0: 0.00, 25000: 0.10, 50000: 0.18, 100000: 0.30}
ALLOWED_DEDUCTIBLES = [0, 25000, 50000, 100000]
MIN_VALUATION_PER_LB_CENTS = 600   # $6.00/lb minimum declared value floor

# ─── estimate_total: long-haul cwt bands + fuel (PRD §3.4) ────────────────────
CWT_RATE_CENTS = {"0_250": 9000, "251_750": 14000, "751_1500": 21000, "1501_plus": 29000}
FUEL_PCT = 0.085
STAIR_FEE_CENTS = 7500
LONG_CARRY_FEE_CENTS = 9000

# ─── estimate_total: local hourly (PRD §3.4) ──────────────────────────────────
CF_PER_CREW_HOUR = 45
MIN_HOURS = 3.0
TRAVEL_HOURS = 0.5
HOURLY_RATE_CENTS = {2: 14000, 3: 19000, 4: 24000, 5: 28500}
# Crew size by total cubic feet: cf<=300 -> 2; 301-600 -> 3; 601-1000 -> 4; cf>1000 -> 5

# ─── final_charge_reconciliation (PRD §3.7) ───────────────────────────────────
BINDING_TOLERANCE_PCT = 0.10

# ─── sit_accrual (PRD §3.8) ───────────────────────────────────────────────────
DAILY_RATE_CENTS = 4200
FREE_SIT_DAYS = 3
WAREHOUSE_HANDLING_CENTS = 11000

# ─── claim_settlement (PRD §3.10) ─────────────────────────────────────────────
RELEASED_RATE_CENTS_PER_LB = 60    # $0.60 per pound per article

# ─── dispatch overlap (PRD §3.6) ──────────────────────────────────────────────
CREW_TURNAROUND_MINUTES = 90

# ─── pagination (PRD §2.3) ────────────────────────────────────────────────────
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
