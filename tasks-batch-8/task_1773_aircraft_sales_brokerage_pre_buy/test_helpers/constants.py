"""Domain thresholds and canonical worked-example values from the PRD.

Calculation constants come from the PRD business-logic sections: the
valuation's minimum comparables count and per-hour adjustment rate, the
deposit minimum percentage, and the commission tier rates. The canonical
Gulfstream G550 comparable set and the deal economics below are the worked
examples the PRD's pinned formulas are exercised against; every expected
value is derived from the PRD's own step-by-step formulas.
"""

# --- PRD calculation constants ------------------------------------------------
MIN_COMPARABLES = 3
TIME_ADJ_PCT_PER_HOUR = 0.00004
MIN_DEPOSIT_PCT = 0.05
TIER1_LIMIT_USD = 5_000_000.00
TIER1_RATE = 0.06
TIER2_RATE = 0.04
DUAL_BUYER_SIDE_RATE = 0.02
DEFAULT_TURNAROUND_BUFFER_MINUTES = 120

# --- Canonical comparable set (Gulfstream G550, all VERIFIED) -----------------
CANONICAL_COMPS = [
    {"make": "Gulfstream", "model": "G550", "year": 2014,
     "sale_price_usd": 4123456.05, "sale_date": "2026-01-20",
     "total_time_hours": 3001, "comp_status": "VERIFIED"},
    {"make": "Gulfstream", "model": "G550", "year": 2016,
     "sale_price_usd": 4350000.00, "sale_date": "2026-02-11",
     "total_time_hours": 2850, "comp_status": "VERIFIED"},
    {"make": "Gulfstream", "model": "G550", "year": 2013,
     "sale_price_usd": 3980000.55, "sale_date": "2026-03-02",
     "total_time_hours": 3100, "comp_status": "VERIFIED"},
]
CANONICAL_LISTING_TT = 2900

# Expected valuation outputs for the canonical comps against a tt-2900 listing:
# PROVISIONAL = round_half_up((4123456.05 + 4350000.00 + 3980000.55) / 3, 2)
EXPECTED_PROVISIONAL_VALUE = 4151152.20
# FINAL per-comp adjusted (rounded to cents first): 4106797.29, 4358700.00,
# 3948160.55 -> mean rounded half up.
EXPECTED_FINAL_VALUE = 4137885.95
# The unpinned alternative (average the unrounded adjustments, round once).
EXPECTED_FINAL_VALUE_MEAN_THEN_ROUND = 4137885.94
# FINAL once a third VERIFIED comp 3900000.00 @ 2900h reaches the minimum
# count (the 3980000.55 UNVERIFIED comp never enters the input set):
# (4106797.29 + 4358700.00 + 3900000.00) / 3 rounded half up.
EXPECTED_FINAL_VALUE_FOUR_COMPS = 4121832.43

# --- Canonical deal economics -------------------------------------------------
# offer 6200000.50, deposit 500000.00, credit 100000.25
DEAL_OFFER_USD = 6200000.50
DEAL_DEPOSIT_USD = 500000.00
DEAL_CREDIT_USD = 100000.25
DEAL_BUDGET_USD = 7000000.00
# base = 6200000.50 - 100000.25 = 6100000.25
EXPECTED_COMMISSION_SOLE = 344000.01        # 300000.00 + 44000.01
EXPECTED_COMMISSION_DUAL = 466000.02        # sole + round(6100000.25 * 0.02)
EXPECTED_COMMISSION_FLAT6 = 366000.02       # wrong: flat 6% of base
EXPECTED_COMMISSION_FLAT4 = 244000.01       # wrong: flat 4% of base
EXPECTED_BUYER_DUE = 5600000.25             # agreed - credits - deposit
EXPECTED_SELLER_NET_SOLE = 5856000.49       # agreed - sole commission
EXPECTED_SELLER_NET_DUAL = 5734000.48       # agreed - dual commission

# --- Small-deal economics (routine pipeline walks) -----------------------------
SMALL_OFFER_USD = 2000000.00
SMALL_DEPOSIT_USD = 100000.00
SMALL_BUDGET_USD = 3000000.00

# --- Default facility / booking window -----------------------------------------
DEFAULT_FACILITY = {"name": "SkyMRO", "airport_code": "KTEB",
                    "turnaround_buffer_minutes": 120}
DEFAULT_SLOT_START = "2026-09-01T10:00:00Z"
DEFAULT_SLOT_END = "2026-09-01T14:00:00Z"
