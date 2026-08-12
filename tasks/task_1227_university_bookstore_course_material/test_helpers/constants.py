"""Domain thresholds and shared constants.

Numeric constants come from the PRD's calculation prose (shelf pricing,
refund variants, buyback offers, tiered landed cost) and the logical-clock
default. Shared calendar payloads live here so fixtures and tests never
hand-duplicate the term calendar.
"""

# Logical clock default before any clock call (PRD: the logical time
# defaults to 2026-05-01T00:00:00Z).
CLOCK_DEFAULT = "2026-05-01T00:00:00Z"

# Shelf pricing constants (PRD §3.6): USED is 75% of list; RENTAL tiers
# are 40% (<= 8 weeks), 50% (9-16 weeks), 60% (>= 17 weeks).
USED_RATIO = 0.75
RENTAL_TIER_1_MAX_WEEKS = 8
RENTAL_TIER_1_PCT = 0.40
RENTAL_TIER_2_MAX_WEEKS = 16
RENTAL_TIER_2_PCT = 0.50
RENTAL_TIER_3_PCT = 0.60

# Returns (PRD §3.7): manager override keeps a 20% restocking share;
# digital lines are returnable within 48 hours of placement.
RESTOCKING_KEEP_PCT = 0.20
DIGITAL_RETURN_HOURS = 48

# Buyback (PRD §3.9): needs-based offer is 50% of list; quotes live 24 hours.
NEEDS_RATIO = 0.50
QUOTE_TTL_HOURS = 24

# Buy-plan tiering (PRD §3.5): a 0.02 tier bonus when projected units
# reach 100.
TIER_QTY = 100
TIER_BONUS_PCT = 0.02

# Canonical fall 2026 term calendar used by most fixtures.
TERM_FALL_2026 = {
    "code": "2026-FALL",
    "length_weeks": 16,
    "registration_open_at": "2026-06-01T00:00:00Z",
    "price_posting_deadline_at": "2026-06-01T00:00:00Z",
    "adoption_deadline_at": "2026-06-15T23:59:59Z",
    "aid_charge_window_start_at": "2026-08-01T00:00:00Z",
    "aid_charge_window_end_at": "2026-09-15T23:59:59Z",
    "add_drop_return_deadline_at": "2026-09-08T23:59:59Z",
    "census_at": "2026-09-10T00:00:00Z",
    "ia_opt_out_deadline_at": "2026-09-09T23:59:59Z",
    "buyback_window_start_at": "2026-12-10T00:00:00Z",
    "buyback_window_end_at": "2026-12-20T23:59:59Z",
    "buy_budget_cents": 100000000,
}

# Spring 2027 term used as the "upcoming term" whose adoptions define
# buyback demand (PRD §3.9).
TERM_SPRING_2027 = {
    "code": "2027-SPRING",
    "length_weeks": 16,
    "registration_open_at": "2026-10-15T00:00:00Z",
    "price_posting_deadline_at": "2026-11-01T00:00:00Z",
    "adoption_deadline_at": "2026-11-15T23:59:59Z",
    "aid_charge_window_start_at": "2027-01-05T00:00:00Z",
    "aid_charge_window_end_at": "2027-02-15T23:59:59Z",
    "add_drop_return_deadline_at": "2027-02-01T23:59:59Z",
    "census_at": "2027-02-03T00:00:00Z",
    "ia_opt_out_deadline_at": "2027-02-02T23:59:59Z",
    "buyback_window_start_at": "2027-05-01T00:00:00Z",
    "buyback_window_end_at": "2027-05-10T23:59:59Z",
    "buy_budget_cents": 100000000,
}

# Frequently used clock positions (all within the canonical calendar above).
CLOCK_IN_AID_WINDOW = "2026-08-20T00:00:00Z"
CLOCK_AT_CENSUS = "2026-09-10T00:00:00Z"
CLOCK_BEFORE_CENSUS = "2026-09-05T00:00:00Z"
CLOCK_PAST_ADD_DROP = "2026-09-20T00:00:00Z"
CLOCK_IN_BUYBACK_WINDOW = "2026-12-15T12:00:00Z"

# Standard publisher agreement window covering all fixture clock positions.
AGREEMENT_STANDARD = {
    "start_date": "2026-01-01",
    "end_date": "2027-06-30",
    "discount_pct": 0.10,
    "digital_discount_pct": 0.25,
    "commission_pct": 0.08,
}

TEST_DEFAULTS = {
    "LIST_PRICE_CENTS": 10000,
    "PUBLISHER_NAME": "Penguin",
    "FACULTY_NAME": "Prof Ada",
    "FACULTY_EMAIL": "ada@uni.edu",
    "COURSE_CODE": "CS101",
    "SECTION_CODE": "01",
    "ENROLLMENT_CAPACITY": 30,
    "STUDENT_AID": 100000,
    "IA_FEE_CENTS": 4900,
}
