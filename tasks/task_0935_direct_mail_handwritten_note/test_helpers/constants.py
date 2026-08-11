"""Domain thresholds and rate-card figures, each quoted from PRD prose.

Every number here is hand-derived from a PRD sentence; the PRD reference is on
the same line so a reader can re-check it.  Nothing in this module is copied
from any structured seed table.
"""

# --- The logical clock (PRD 2.4) ------------------------------------------
# "Before any caller sets it, the logical clock reads exactly 2026-05-01T00:00:00Z."
CLOCK_DEFAULT_UTC = "2026-05-01T00:00:00Z"
CLOCK_DEFAULT_DATE = "2026-05-01"

# --- Template bounds (PRD 3.2) --------------------------------------------
# "at least 1 character and at most 2000, both bounds inclusive"
MIN_TEMPLATE_CHARACTER_COUNT = 1
MAX_TEMPLATE_CHARACTER_COUNT = 2000

# --- Presort tier thresholds (PRD 3.4) ------------------------------------
# MARKETING_MAIL: "PRESORT_5D at 12 or more automation pieces, PRESORT_AADC at
# 9 or more, PRESORT_MIXED_AADC at 6 or more, and NO_PRESORT below that."
PRESORT_5D_MIN_PIECES = 12
PRESORT_AADC_MIN_PIECES = 9
PRESORT_MIXED_AADC_MIN_PIECES = 6
# FIRST_CLASS: "takes PRESORT_AADC when A is at least 6 and NO_PRESORT otherwise"
FIRST_CLASS_AUTOMATION_MIN_PIECES = 6

# --- Rate card, cents per piece to one decimal place (PRD 3.4) ------------
PRESORT_5D_RATE_CENTS = 23.9
PRESORT_AADC_RATE_CENTS = 28.1
PRESORT_MIXED_AADC_RATE_CENTS = 31.8
MARKETING_NO_PRESORT_RATE_CENTS = 51.0
MARKETING_RETAIL_RATE_CENTS = 51.6
FIRST_CLASS_AUTOMATION_RATE_CENTS = 58.0
FIRST_CLASS_RETAIL_RATE_CENTS = 73.0
EDDM_SATURATION_RATE_CENTS = 22.3
EDDM_HIGH_DENSITY_PLUS_RATE_CENTS = 25.6

# --- EDDM bounds (PRD 3.4, 3.7) -------------------------------------------
# "its total selected pieces must fall within 5 and 50 inclusive"
EDDM_MIN_PIECES_PER_JOB = 5
EDDM_MAX_PIECES_PER_JOB = 50
# "HIGH_DENSITY_PLUS variant demands only that each route carry at least 3
#  residential pieces"
EDDM_HIGH_DENSITY_PLUS_MIN_RESIDENTIAL = 3

# --- Commit settlement (PRD 3.7) ------------------------------------------
# "250 cents of base charge plus eight percent of postage, with that percentage
#  component rounded up to the next whole cent"
HANDLING_BASE_CENTS = 250
HANDLING_PCT = 0.08
# "five percent of the subtotal, rounded down ... only when the job carries at
#  least 6 billable pieces"
VOLUME_CREDIT_PCT = 0.05
VOLUME_CREDIT_MIN_PIECES = 6

# --- Robot-pen production (PRD 3.8) ---------------------------------------
# "each setup pass costs 12 slot-minutes, and a SINGLE_PASS run is charged one
#  setup pass while a SPLIT_RUN run is charged two"
RUN_SETUP_MINUTES = 12
SINGLE_PASS_SETUP_PASSES = 1
SPLIT_RUN_SETUP_PASSES = 2
# "an optional daily_capacity_minutes of at least 1 slot-minute defaulting to 480"
DEFAULT_MACHINE_DAILY_CAPACITY_MINUTES = 480
# "the 500-microlitre safety reserve that must always be left in the bottle"
INK_SAFETY_RESERVE_UL = 500

# --- Return handling (PRD 3.9) --------------------------------------------
# "a FIRST_CLASS return costs nothing ... while a MARKETING_MAIL return costs
#  89 cents per piece"
RETURN_FEE_CENTS_FIRST_CLASS = 0
RETURN_FEE_CENTS_MARKETING_MAIL = 89
# "the record's reprint_count must be strictly below the cap of one reprint per
#  record per campaign"
REPRINT_CAP_PER_CAMPAIGN_PER_RECORD = 1

# --- Proof approval window (PRD 3.5) --------------------------------------
# "expires_at is set to exactly thirty days after approved_at"
PROOF_APPROVAL_VALID_DAYS = 30

# --- Drip / drop-date derivation (PRD 3.6) --------------------------------
# "3 days for FIRST_CLASS, 10 days for MARKETING_MAIL, and 12 days for EDDM"
TRANSIT_DAYS_FIRST_CLASS = 3
TRANSIT_DAYS_MARKETING_MAIL = 10
TRANSIT_DAYS_EDDM = 12
# "earlier than the current date plus 3 days of production lead time"
PRODUCTION_LEAD_DAYS = 3
# "If the shift counter would exceed 5 ... The cap is inclusive"
BLACKOUT_SHIFT_MAX_DAYS = 5
# "must differ from the resolved drop date of every existing non-cancelled
#  sibling step ... by at least 2 calendar days"
DRIP_MIN_GAP_DAYS = 2
# "the schedule must be holding fewer than 8 non-cancelled steps"
DRIP_MAX_STEPS = 8

# --- Pagination (PRD 2.3) -------------------------------------------------
DEFAULT_PAGE_LIMIT = 10
MIN_PAGE_LIMIT = 1
MAX_PAGE_LIMIT = 100

TRANSIT_DAYS_BY_MAIL_CLASS = {
    "FIRST_CLASS": TRANSIT_DAYS_FIRST_CLASS,
    "MARKETING_MAIL": TRANSIT_DAYS_MARKETING_MAIL,
    "EDDM": TRANSIT_DAYS_EDDM,
}
