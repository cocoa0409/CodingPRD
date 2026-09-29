"""Domain thresholds and canonical test data drawn from the PRD's formulas."""

# ─── The logical clock ────────────────────────────────────────────────────
# The clock starts at exactly this instant and never falls back to wall time.
CLOCK_START = "2026-08-01T00:00:00Z"
CLOCK_START_MS = "2026-08-01T00:00:00.000Z"

# ─── Money and pricing ────────────────────────────────────────────────────
FACILITY_FEE_CENTS_PER_SEAT = 150
MAX_SEATS_PER_ORDER = 10
MIN_SEATS_PER_ORDER = 1

# ─── Membership standing ──────────────────────────────────────────────────
ROLLING_WINDOW_DAYS = 365
FISCAL_YEAR_START = "2026-07-01T00:00:00.000Z"
MEMBERSHIP_TERM_DAYS = 365

TIER_THRESHOLD_CENTS = {
    "DONOR_CIRCLE": 50000,
    "SUPPORTER": 15000,
    "BASIC": 6000,
}
TIER_RANK = {"PROSPECT": 0, "BASIC": 1, "SUPPORTER": 2, "DONOR_CIRCLE": 3}
DISCOUNT_PCT_BY_TIER = {
    "PROSPECT": 0.00,
    "BASIC": 0.10,
    "SUPPORTER": 0.15,
    "DONOR_CIRCLE": 0.25,
}
ADVANCE_ACCESS_HOURS_BY_TIER = {
    "PROSPECT": 0,
    "BASIC": 24,
    "SUPPORTER": 48,
    "DONOR_CIRCLE": 168,
}
COMP_TICKETS_GRANTED_BY_TIER = {
    "PROSPECT": 0,
    "BASIC": 0,
    "SUPPORTER": 2,
    "DONOR_CIRCLE": 6,
}

# ─── Negotiation ──────────────────────────────────────────────────────────
OFFER_VALIDITY_HOURS = 72
MAX_NEGOTIATION_ROUNDS = 4

# ─── Minimum run and settlement ───────────────────────────────────────────
MIN_PRORATION_FLOOR = 0.60
MAX_PRORATION = 1
MIN_RUN_PENALTY_RATE = 0.50
SLIDING_SCALE_DISTRIBUTOR_RATE = 0.90

# ─── Slot scoring ─────────────────────────────────────────────────────────
SLOT_GRID_MINUTES = 15
PRIME_SCORE_EVENING = 60
PRIME_SCORE_AFTERNOON = 35
PRIME_SCORE_OTHER = 10
SPACING_GAP_CAP_MINUTES = 120
SPACING_COMPONENT_CAP = 12
FRAGMENTATION_PENALTY = 15
REPERTORY_STRAND_BONUS = 10

# ─── Auditorium defaults (used when the field is omitted at registration) ─
VENUE_DEFAULTS = {
    "house_hold_seats": 0,
    "min_useful_gap_minutes": 45,
    "utc_offset_minutes": 0,
    "max_first_run_share": 0.60,
    "weekly_repertory_target": 6,
    "base_house_nut_weekly_cents": 480000,
}

# ─── Canonical test data ──────────────────────────────────────────────────
# One 12-seat house holding back 4 seats, so 8 seats are ever sellable.
TEST_DEFAULTS = {
    "VENUE_NAME": "Reel Repertory",
    "SEAT_CAPACITY": 12,
    "HOUSE_HOLD_SEATS": 4,
    "SELLABLE_SEATS": 8,
    "TRAILER_REEL_MINUTES": 12,
    "TURNAROUND_MINUTES": 25,
    "MIN_USEFUL_GAP_MINUTES": 45,
    "DCP_INGEST_LANE_COUNT": 2,
    "OPEN_LOCAL_TIME": "11:00",
    "LAST_START_LOCAL_TIME": "22:00",
    "UTC_OFFSET_MINUTES": 0,
    "MAX_FIRST_RUN_SHARE": 0.60,
    "WEEKLY_REPERTORY_TARGET": 3,
    "SUPPORTED_FORMATS": ["DCP_2K", "DCP_4K"],
    "BASE_HOUSE_NUT_WEEKLY_CENTS": 200000,
    "DISTRIBUTOR_NAME": "Coyote Films",
    "DISTRIBUTOR_EMAIL": "book@coyote.example",
    "DEFAULT_MIN_RUN_DAYS": 4,
    "DEFAULT_DISTRIBUTOR_SHARE_PCT": 0.35,
    "TITLE_NAME": "La Jetee Redux",
    "RELEASE_YEAR": 1962,
    "RUNTIME_MINUTES": 104,
    "HOUSE_NUT_CENTS": 12500,
    "GUARANTEE_CENTS": 3000,
    "MIN_RUN_DAYS": 4,
    "ENGAGEMENT_START_DATE": "2026-08-10",
    "ENGAGEMENT_END_DATE": "2026-08-20",
    "LICENSOR_NAME": "Cinematheque Nord",
    "LICENSE_FEE_CENTS": 45000,
    "TERRITORY": "US-NY-METRO",
    "WINDOW_START_DATE": "2026-08-10",
    "WINDOW_END_DATE": "2026-08-20",
    "MAX_SCREENINGS": 6,
    "CARRIER_REF": "WB-77120",
    "INGEST_WINDOW_START_AT": "2026-07-30T08:00:00Z",
    "INGEST_WINDOW_END_AT": "2026-07-31T08:00:00Z",
    "SERVER_REF": "SRV-CERT-9",
    "BASE_PRICE_CENTS": 1450,
    "PUBLIC_SALE_OPENS_AT": "2026-08-01T00:00:00Z",
    "MEMBER_NAME": "Ada Wells",
    "MEMBER_EMAIL": "ada@example.com",
    "JOIN_DATE": "2026-07-01",
    "SUPPORTER_DONATION_CENTS": 20000,
    "SUPPORTER_DONATION_AT": "2026-03-01T10:00:00Z",
}

# The canonical 104-minute title in the canonical 12-minute-reel, 25-minute
# turnaround house: 116 minutes on screen, 141 minutes of screen occupancy.
CANONICAL_ON_SCREEN_MINUTES = 116
CANONICAL_BLOCK_MINUTES = 141
