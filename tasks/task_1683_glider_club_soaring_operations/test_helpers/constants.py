"""Domain thresholds and money constants (PRD §2.6-§2.11, §3)."""

# Logical clock (PRD §2.5): before any call the clock reads exactly this instant.
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

# Convenience default for airframe registration: an annual deadline far in the
# future so the airframe is currency-legal unless a test drives it overdue.
DEFAULT_ANNUAL_DUE = "2027-06-01T00:00:00Z"

# Tow fee ladder (PRD §3.5): base price by release altitude in feet MSL.
TOW_TIER1_CEILING_FT = 2000
TOW_TIER2_CEILING_FT = 3000
TOW_TIER3_CEILING_FT = 5000
TOW_TIER1_CENTS = 3000
TOW_TIER2_CENTS = 3800
TOW_TIER3_CENTS = 4600
TOW_TIER4_CENTS = 5500

# Soaring surcharge (PRD §3.6): 400 cents per commenced 30-minute block
# beyond the first 60 flight minutes; never discounted.
SOAR_SURCHARGE_CENTS = 400
SOAR_SURCHARGE_BLOCK_MIN = 30
SOAR_FREE_MINUTES = 60

# Member account (PRD §2.6, §3.2).
ARREARS_THRESHOLD_CENTS = 20000
CREDIT_CAP_CENTS = -50000

# Penalty fees (PRD §2.6): always apply, never waived.
LATE_CANCEL_WINDOW_HOURS = 24
LATE_CANCEL_FEE_CENTS = 1500
NO_SHOW_FEE_CENTS = 2500
DUTY_NO_SHOW_FEE_CENTS = 5000

# Tow plane accrual (PRD §3.6): fixed twelve-minute sortie per launched flight.
TOW_SORTIE_MINUTES = 12

# Temporal rules (PRD §2.9).
INSTRUCTOR_BUFFER_MIN = 30
CHECKOUT_EARLY_GRACE_MIN = 15

# Airframe currency (PRD §2.8): strict less-than against 100.0 hours.
INSPECTION_INTERVAL_HOURS = 100.0

# Retrieve cost split (PRD §3.6).
RETRIEVE_BASE_CENTS = 5000
RETRIEVE_PER_KM_CENTS = 120
RETRIEVE_BAND1_KM = 50
RETRIEVE_BAND2_KM = 100

# Solo eligibility (PRD §3.7).
MIN_DUAL_HOURS = 10.0
SOLO_RECENCY_DAYS = 90
