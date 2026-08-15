"""Domain thresholds and rate sets — numeric constants named in PRD 3.x.

Only constants whose values appear verbatim in the PRD live here.  Statutory
window lengths the PRD names but never numbers (the appeal window, the
referendum window) are deliberately absent: tests read those deadlines from
server-computed fields instead of hard-coding values.
"""

# --- Logical clock (PRD 2.8) ---
CLOCK_DEFAULT_ISO = "2026-08-01T00:00:00Z"

# --- Opposition scoring (PRD 3.5) ---
WEIGHT_SUPPORT = -2
WEIGHT_NEUTRAL = 0
WEIGHT_OPPOSE = 5
WEIGHT_ORGANIZED_OPPOSITION = 12
ELEVATED_THRESHOLD = 10  # "at least 10 but below 30" -> ELEVATED
HIGH_THRESHOLD = 30  # "reaches 30" -> HIGH

# --- Hearings (PRD 3.5) ---
NOTICE_LEAD_DAYS = 20  # "exactly 20 days satisfies the rule and 19 days is rejected"

# --- Decision deadline (PRD 3.3) ---
PERMIT_STREAMLINING_DAYS = 90  # "stamps decision_due_date as 90 days after the submission instant"

# --- Late fees (PRD 3.7) ---
LATE_FEE_RATE_PER_MONTH = 0.015  # "1.5 percent for each full month"
DAYS_PER_MONTH = 30  # "the whole 30-day months contained in that span"

# --- Referendum threshold (PRD 3.8) ---
REFERENDUM_SIGNATURE_PCT = 0.10  # "ten percent of registered_voters"

# --- Impact fee basis (PRD 3.3) ---
SQFT_BASIS_DIVISOR = 1000  # "floor_area_sqft divided by 1,000"
AFFORDABLE_EXEMPT_CATEGORIES = ("TRANSPORTATION", "PARKS")
FEE_CATEGORIES = ("TRANSPORTATION", "PARKS", "FIRE", "WATER", "SEWER")

# --- Canonical fee schedule rate sets used across tests ---
V1_RATES = {
    "rate_transportation_res": 3200.00,
    "rate_parks_res": 2100.00,
    "rate_fire_res": 800.00,
    "rate_water_res": 2600.00,
    "rate_sewer_res": 2900.00,
    "rate_transportation_com": 5400.00,
    "rate_parks_com": 0.00,
    "rate_fire_com": 950.00,
    "rate_water_com": 3100.00,
    "rate_sewer_com": 3400.00,
}

# V2: every rate +10% over V1 (used for schedule-supersession tests).
V2_RATES = {
    "rate_transportation_res": 3520.00,
    "rate_parks_res": 2310.00,
    "rate_fire_res": 880.00,
    "rate_water_res": 2860.00,
    "rate_sewer_res": 3190.00,
    "rate_transportation_com": 5940.00,
    "rate_parks_com": 0.00,
    "rate_fire_com": 1045.00,
    "rate_water_com": 3410.00,
    "rate_sewer_com": 3740.00,
}

# Odd-cent commercial rates that force fractional-cent raw category grosses.
COMMERCIAL_ODD_CENT_RATES = dict(V1_RATES, rate_fire_com=951.05, rate_water_com=3125.55)

TEST_DEFAULTS = {
    "DWELLING_UNITS": 5,
    "AFFORDABLE_UNITS": 0,
    "FLOOR_AREA_SQFT": 0,
    "ATTENDEE_COUNT": 10,
    "VESTING_TERM_YEARS": 5,
    "REGISTERED_VOTERS": 12500,
}
