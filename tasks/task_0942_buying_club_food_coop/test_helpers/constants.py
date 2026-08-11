"""Domain thresholds and tunables, taken from the PRD narrative."""

# --- logical clock (PRD §2.5) ---------------------------------------------
CLOCK_DEFAULT_UTC = "2026-05-01T00:00:00Z"

# --- minimums (PRD §3.2, §2.7) --------------------------------------------
DROP_MINIMUM_DEFAULT_CENTS = 50000
ROUTE_MINIMUM_DEFAULT_CENTS = 250000
ROUTE_REEFER_SLOTS_DEFAULT = 2
ROUTE_MAX_PALLETS_DEFAULT = 12

# --- split-case pricing (PRD §3.4) ----------------------------------------
SPLIT_CASE_FEE_PCT = 0.12
SPLIT_CASE_FEE_MIN_CENTS = 25

# --- cycle windows (PRD §3.6, §2.7) ---------------------------------------
EXCEPTION_WINDOW_HOURS = 48
ROUTE_TURNAROUND_HOURS = 48

# --- substitution (PRD §3.6) ----------------------------------------------
SUBSTITUTION_TOLERANCE_PCT = 0.10
SUBSTITUTION_RESPONSE_HOURS = 24

# --- two-phase payment (PRD §3.8) -----------------------------------------
PAYMENT_AUTH_BUFFER_PCT = 0.10
PAYMENT_VARIANCE_TOLERANCE_PCT = 0.15
PAYMENT_VARIANCE_TOLERANCE_FLOOR_CENTS = 500

# --- reconciliation (PRD §2.7, §3.9) --------------------------------------
RECON_VARIANCE_TOLERANCE_CENTS = 200

# --- cold chain / pallets (PRD §3.7, §2.7) --------------------------------
REEFER_SURCHARGE_CENTS_PER_SLOT = 4500
PALLET_MAX_WEIGHT_GRAMS = 900000
PALLET_MAX_CUBE_CM3 = 1600000
REEFER_REQUIRED_TEMP_CLASSES = ["FROZEN", "CHILLED"]

# --- coordinator commission (PRD §3.9) ------------------------------------
COMMISSION_BAND_1_MAX_CENTS = 100000
COMMISSION_BAND_1_RATE = 0.03
COMMISSION_BAND_2_MAX_CENTS = 300000
COMMISSION_BAND_2_RATE = 0.05
COMMISSION_BAND_3_RATE = 0.07
COMMISSION_VOLUNTEER_MIN_HOURS = 4.0
COMMISSION_VOLUNTEER_UNMET_MULTIPLIER = 0.50
COMMISSION_STORE_CREDIT_BONUS_PCT = 0.10
COMMISSION_CASH_FEE_PCT = 0.02
COMMISSION_CASH_FEE_MIN_CENTS = 100

# --- membership (PRD §3.1) ------------------------------------------------
COORDINATOR_MIN_TIER_RANK = 2
MEMBERSHIP_TERM_DAYS = 365
DUES_GRACE_DAYS = 14
TIER_BASIC_RANK = 1
TIER_BASIC_ANNUAL_DUES_CENTS = 3000
TIER_BASIC_DISCOUNT_PCT = 0.00
TIER_PLUS_RANK = 2
TIER_PLUS_ANNUAL_DUES_CENTS = 9000
TIER_PLUS_DISCOUNT_PCT = 0.05
TIER_PRO_RANK = 3
TIER_PRO_ANNUAL_DUES_CENTS = 18000
TIER_PRO_DISCOUNT_PCT = 0.09

ANNUAL_DUES_CENTS = {
    "BASIC": TIER_BASIC_ANNUAL_DUES_CENTS,
    "PLUS": TIER_PLUS_ANNUAL_DUES_CENTS,
    "PRO": TIER_PRO_ANNUAL_DUES_CENTS,
}
TIER_RANK = {"BASIC": 1, "PLUS": 2, "PRO": 3}
TIER_DISCOUNT_PCT = {"BASIC": 0.00, "PLUS": 0.05, "PRO": 0.09}

# --- volunteer credit (PRD §3.9, §3.1) ------------------------------------
VOLUNTEER_CREDIT_CENTS_PER_HOUR = 1200
VOLUNTEER_CREDIT_EXPIRY_DAYS = 180
CREDIT_MAX_OFFSET_PCT = 0.50

# --- ordering / rollover (PRD §3.3, §3.5) ---------------------------------
MAX_ORDER_LINE_UNITS = 500
MIN_ORDER_LINE_UNITS = 1
ROLLFORWARD_MAX_PER_DROP_RUN = 1

# --- pagination (PRD §2.3) ------------------------------------------------
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100

# --------------------------------------------------------------------------
# Canonical scenario values used by the composite fixtures.  These are the
# figures the fixture chain drives the system to; every expected value in the
# test suite is derived from the PRD's stated arithmetic over them.
# --------------------------------------------------------------------------
CLOCK_OPEN = "2026-05-05T00:00:00Z"
CLOCK_CUTOFF = "2026-05-25T00:00:00Z"
CLOCK_AFTER_EXCEPTION_WINDOW = "2026-05-27T00:00:00Z"

CYCLE_OPENS_AT = "2026-05-05T00:00:00Z"
CYCLE_CUTOFF_AT = "2026-05-25T00:00:00Z"

PRICE_EPOCH = "2026-04-01T00:00:00Z"
PRICE_LATE_OAT = "2026-05-20T00:00:00Z"

DEFAULT_SUPPLIER_INVOICE_CENTS = 64400
DEFAULT_FREIGHT_CENTS = 5000
