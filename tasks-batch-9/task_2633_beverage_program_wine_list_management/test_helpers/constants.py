"""Global constants declared by the PRD (§ Global Constants) plus the
derived lookup tables the PRD states inline as calculation inputs."""

# --- PRD global constants ----------------------------------------------
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"
WINE_CATEGORIES = ["SPARKLING", "WHITE", "ROSE", "RED", "DESSERT", "FORTIFIED"]
BTG_SPOILAGE_ALLOWANCE_POURS = 1
EVENT_POUR_SIZE_ML = 100
EVENT_TURNOVER_BUFFER_MINUTES = 120
MAX_REVISION_ROUNDS = 3
REPRINT_THRESHOLD_ENTRIES = 2
MAX_PRESERVATION_HOURS = 720
LARGE_PARTY_THRESHOLD = 8
LARGE_PARTY_CORKAGE_DISCOUNT_PCT = 25.0
PAR_URGENT_FRACTION = 0.5
VARIANCE_RESTRICTED_PCT = 3.0
VARIANCE_FROZEN_PCT = 6.0

# --- Preservation base hours by wine category (PRD preservation rule) ---
PRESERVATION_BASE_HOURS = {
    "SPARKLING": 24,
    "WHITE": 72,
    "ROSE": 72,
    "RED": 96,
    "DESSERT": 168,
    "FORTIFIED": 336,
}

# --- Preservation method factors (PRD preservation rule) ----------------
PRESERVATION_METHOD_FACTOR = {
    "ARGON": 2.0,
    "VACUUM": 1.0,
    "COOLER": 1.5,
    "NONE": 0.5,
}

# --- Bottle-price markup bands (PRD bottle pricing rule) ----------------
# Each tuple is (inclusive upper bound in cents or None, multiplier);
# every break belongs to the band below it.
MARKUP_BANDS = [
    (2000, 3.50),
    (6000, 3.00),
    (15000, 2.60),
    (None, 2.20),
]
ALLOCATED_MARKUP_UPLIFT = 1.15
BOTTLE_PRICE_ROUND_UP_TO_CENTS = 100

# --- Price bands (PRD price band rule), inclusive upper bounds ----------
PRICE_BAND_VALUE_MAX = 6000
PRICE_BAND_CORE_MAX = 12000
PRICE_BAND_PREMIUM_MAX = 25000

# --- Glass price lift (PRD glass pricing rule) --------------------------
GLASS_PRICE_ROUND_UP_TO_CENTS = 25

# --- Event pricing lifts (PRD event pricing rule) -----------------------
PROVISIONAL_GROSS_ROUND_UP_TO_CENTS = 500
FINAL_TICKET_ROUND_UP_TO_CENTS = 100

# --- Wine dinner event beverage tiers (PRD event pricing rule) ----------
# (inclusive lower bound on provisional gross cents, service charge pct)
EVENT_TIERS = [
    (0, 0.0),
    (250000, 4.0),
    (500000, 7.0),
]
