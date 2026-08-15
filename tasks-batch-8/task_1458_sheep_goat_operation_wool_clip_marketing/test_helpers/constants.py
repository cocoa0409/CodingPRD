"""Domain thresholds and price tables — numeric constants from PRD §3 narratives."""

# Logical clock startup default (PRD §2.5).
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"

# Gestation lengths in days (PRD §3.1).
GESTATION_DAYS = {"SHEEP": 147, "GOAT": 150}

# Lambing window length: birth_date within [expected_lambing_start, +45 days] (PRD §3.1).
LAMBING_WINDOW_DAYS = 45
# LAMBING -> WEANING gate: expected_lambing_start + 45 days (PRD §3.1).
WEANING_GATE_DAYS = 45

# Pasture default rest period (PRD §3.2).
DEFAULT_REST_DAYS = 21

# Treatment efficacy resistance threshold (PRD §3.2): strictly below 80.0 flags resistance.
RESISTANCE_THRESHOLD_PCT = 80.0

# Crew booking sanitation buffer (PRD §3.3): 24h gap required between bookings.
CREW_BUFFER_HOURS = 24

# Wool grade bands in microns (PRD §3.4), lower bounds inclusive.
GRADE_BANDS = {
    "SUPERFINE_MAX_EXCL": 19.5,
    "FINE_MAX_EXCL": 21.5,
    "MEDIUM_MAX_EXCL": 24.5,
    "STRONG_MAX_EXCL": 27.5,
}

# Lot pricing tables in cents (PRD §3.4).
GREASY_PRICE_CENTS = {"SUPERFINE": 380, "FINE": 330, "MEDIUM": 260, "STRONG": 190, "COARSE": 120}
CLEAN_PRICE_CENTS = {"SUPERFINE": 720, "FINE": 640, "MEDIUM": 520, "STRONG": 400, "COARSE": 280}

# Consignment advance rate (PRD §3.5): 70 percent of effective value.
ADVANCE_RATE = 0.70

# Pool fee tiers (PRD §3.5), lower bounds inclusive.
TIER1_MAX_LBS_EXCL = 10000
TIER2_MAX_LBS_EXCL = 25000
TIER1_PCT = 6.5
TIER2_PCT = 5.0
TIER3_PCT = 4.0

# Livestock sale pricing (PRD §3.6).
AUCTION_COMMISSION_PCT = 3.5
AUCTION_COMMISSION_CAP_CENTS = 15000

# Grazing contract invoice (PRD §3.8).
BONUS_PCT = 0.10
BONUS_CAP_CENTS = 250000
BREACH_PENALTY_PCT = 0.20
