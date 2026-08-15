"""Domain thresholds and canonical scenario values from the PRD.

All monetary values are integer cents. The canonical rate card below is the
price book used by most scenarios; every number in the test-suite money
assertions is derived from these constants through the PRD's pricing rules.
"""

# --- Logical clock -----------------------------------------------------------
CLOCK_BOOT_ISO = "2026-08-01T00:00:00Z"

# --- After-hours boundary (UTC hour of received_at) ---------------------------
# after_hours is true when hour >= 18 or hour < 6 (18:00:00Z is after-hours,
# 17:59:59Z is not; 06:00:00Z is not, 05:59:59Z is).
AFTER_HOURS_START_HOUR = 18
AFTER_HOURS_END_HOUR = 6

# --- Fleet discount tiers ------------------------------------------------------
# Derived from month_to_date_spend_cents: >= 500000 PLATINUM (10%),
# >= 200000 GOLD (5%), else STANDARD (0%).
GOLD_THRESHOLD_CENTS = 200_000
PLATINUM_THRESHOLD_CENTS = 500_000

# --- Documented defaults --------------------------------------------------------
DEFAULT_PAYMENT_TERMS_DAYS = 30
DEFAULT_REORDER_POINT = 2
DEFAULT_VEHICLE_ODOMETER = 0

# --- Time-driven rules -----------------------------------------------------------
ESTIMATE_EXPIRY_DAYS = 7          # SUBMITTED estimates expire after 7 calendar days
DEFECT_CORRECTION_DAYS = 15       # correction_deadline_at = discovered_at + 15 days
TOW_WINDOW_BUFFER_MINUTES = 30    # tow pickup windows expanded +/-30 minutes
APPEAL_CAP = 2                    # warranty appeal hard cap

# --- Repeat-failure comeback windows ---------------------------------------------
NO_CHARGE_MAX_DAYS = 30
NO_CHARGE_MAX_MILES = 1000
REDUCED_MAX_DAYS = 45
REDUCED_MAX_MILES = 2000

# --- Canonical rate card ("STD-2026") ----------------------------------------------
STD_CARD = {
    "name": "STD-2026",
    "labor_rate_standard_cents": 14500,
    "labor_rate_master_cents": 17500,
    "after_hours_multiplier_bp": 15000,   # 1.5x labor on after-hours calls
    "travel_free_miles": 25,
    "travel_per_mile_cents": 425,
    "travel_time_per_minute_cents": 200,
    "emergency_callout_fee_cents": 25000,
    "parts_tax_rate_bp": 725,             # 7.25% on the parts subtotal only
    "effective_from": "2026-01-01T00:00:00Z",
    "effective_to": "2026-12-31T23:59:59Z",
}

# --- Canonical "S1" job (business-hours DRIVABLE alternator job) --------------------
# 2.5h STANDARD labor = 36250; travel (40-25) x 425 = 6375; 95 travel minutes
# x 200 = 19000; parts 2 x 34999 = 69998; tax = round_half_up(69998*0.0725) = 5075;
# total = 136698.
S1_LABOR_AMOUNT_CENTS = 36_250
S1_TRAVEL_AMOUNT_CENTS = 6_375
S1_TRAVEL_TIME_AMOUNT_CENTS = 19_000
S1_PARTS_SUBTOTAL_CENTS = 69_998
S1_TAX_CENTS = 5_075
S1_TOTAL_CENTS = 136_698

# Alternator van stock pricing used across scenarios
ALT_104_UNIT_COST_CENTS = 21_000
ALT_104_UNIT_RETAIL_CENTS = 34_999
