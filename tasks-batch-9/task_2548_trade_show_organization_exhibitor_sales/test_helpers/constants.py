"""
Domain constants for the Trade Show Exhibitor Sales API.

Every value here is transcribed from a numeric literal that PRD.md states in
prose.  Nothing is derived, inferred or rounded on the way in: if the PRD spells
a number out in words ("two points per whole hundred-square-foot block") the
integer form appears here and the quote lives beside it.
"""

# ─── §2.4 Logical clock ───────────────────────────────────────────────────────
# "Before any client sets it, the clock reads exactly `2026-08-01T00:00:00Z`"
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

# ─── §2.3 Pagination ─────────────────────────────────────────────────────────
# "`limit` controls page size: it defaults to 10 when omitted, may not be
#  smaller than 1, and may not be larger than 100."
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ─── §3.1 Venue contract defaults ────────────────────────────────────────────
# "it defaults to three buckets — 25 percent at 180 days out, 50 percent at
#  90 days out, and 100 percent at zero days out."
DEFAULT_CANCELLATION_FEE_SCHEDULE = [
    {"min_days_out": 180, "pct": 25},
    {"min_days_out": 90, "pct": 50},
    {"min_days_out": 0, "pct": 100},
]

# ─── §3.1 Hall occupancy ─────────────────────────────────────────────────────
# "a symmetric dark-day buffer of two days on each side"
DARK_DAY_BUFFER_DAYS = 2

# ─── §3.2 Publication ────────────────────────────────────────────────────────
# "`advance_order_deadline` as the date of `move_in_start` less twenty-one days"
ADVANCE_ORDER_LEAD_DAYS = 21

# ─── §3.5 Booth pricing multipliers ──────────────────────────────────────────
# "a location multiplier — 1.00 for `INLINE`, 1.10 for `CORNER`,
#  1.20 for `PENINSULA`, 1.30 for `ISLAND`"
LOCATION_MULT = {
    "INLINE": 1.00,
    "CORNER": 1.10,
    "PENINSULA": 1.20,
    "ISLAND": 1.30,
}

# "a zone multiplier: 1.00 for `NONE`, 1.08 for `MAIN_AISLE`,
#  1.15 for `ENTRANCE`, and 1.05 for `FOOD_COURT`."
ZONE_MULT = {
    "NONE": 1.00,
    "MAIN_AISLE": 1.08,
    "ENTRANCE": 1.15,
    "FOOD_COURT": 1.05,
}

# ─── §3.5 Volume tiers (inclusive at the bottom) ─────────────────────────────
# "12 percent at 4000 square feet or more, 8 percent at 2000 or more,
#  5 percent at 1000 or more, and 0 percent below 1000."
VOLUME_TIER_PCT = [(4000, 12), (2000, 8), (1000, 5), (0, 0)]

# "The contract's `min_deposit_cents` is then 25 percent of `space_fee_cents`"
MIN_DEPOSIT_PCT = 25

# ─── §3.5 Negotiation and discount fences ────────────────────────────────────
# "requires the contract's `negotiation_round` to be strictly below three"
MAX_NEGOTIATION_ROUNDS = 3
# "A discount above 10 percent may only be approved by a `ShowDirector`"
DISCOUNT_APPROVAL_THRESHOLD_PCT = 10
# "No role, the `ShowDirector` included, may approve more than 40 percent"
MAX_APPROVED_DISCOUNT_PCT = 40

# ─── §3.5 Bundle tiers, read from the PRE-discount subtotal ──────────────────
# "4 percent when the subtotal is at least five million cents, two and a half
#  percent when it is at least two million cents, and 0 percent below that."
BUNDLE_TIER_PCT = [(5_000_000, 4), (2_000_000, 2.5), (0, 0)]

# ─── §3.9 Service order rate card arithmetic ─────────────────────────────────
# "for `MATERIAL_HANDLING` it is the larger of the ordered `quantity` and a
#  two-hundredweight minimum"
MIN_BILLABLE_CWT = 2
# "the product of `billable_quantity`, `unit_rate_cents` and one point three five"
FLOOR_RATE_MULTIPLIER = 1.35
# "a flat seventy-five dollars — 7500 cents — is added"
EXPEDITE_FEE_CENTS = 7500

# ─── §3.3 Priority points ────────────────────────────────────────────────────
# "its effective net square footage divided by one hundred with the remainder
#  discarded, multiplied by two points per whole hundred-square-foot block"
SQFT_PER_POINT_BLOCK = 100
POINTS_PER_BLOCK = 2
# "plus a flat five-point rebooking bonus"
REBOOK_BONUS_POINTS = 5
# "its `negotiated_price_cents` divided by five hundred thousand cents"
CENTS_PER_SPEND_POINT = 500_000
# "when the edition age is strictly greater than three, the contract's
#  contribution is halved with the remainder discarded"
CERTIFIED_DECAY_EDITION_AGE = 3
# "`PLATINUM` at 1000 points or more, `GOLD` at 600 or more,
#  `SILVER` at 300 or more, and `BRONZE` below that."
TIER_FLOORS = [("PLATINUM", 1000), ("GOLD", 600), ("SILVER", 300), ("BRONZE", 0)]
# "When an exhibitor's `penalty_points` reaches thirty, the exhibitor
#  transitions `ACTIVE → SUSPENDED`"
SUSPENSION_PENALTY_THRESHOLD = 30

# ─── §3.5 Booth selector ordering keys ───────────────────────────────────────
# "then by `location_class` in the sequence `INLINE`, `CORNER`, `PENINSULA`, `ISLAND`"
LOCATION_RANK = {"INLINE": 1, "CORNER": 2, "PENINSULA": 3, "ISLAND": 4}
# "ordered `ENTRANCE`, then `MAIN_AISLE`, then `FOOD_COURT`, then `NONE`"
ZONE_RANK = {"ENTRANCE": 1, "MAIN_AISLE": 2, "FOOD_COURT": 3, "NONE": 4}

# ─── §2.8 Floor posture thresholds ───────────────────────────────────────────
# "`FROZEN` when `committed_ratio_pct` is at least 100 ... otherwise it is
#  `SPACE_LOCKED` when `committed_ratio_pct` is at least 85"
FROZEN_RATIO_PCT = 100
SPACE_LOCKED_RATIO_PCT = 85
# "also when the show is `ON_SITE` and its `upheld_violation_count` has reached three"
ONSITE_FREEZE_VIOLATIONS = 3

# ─── §3.9 Attrition settlement ───────────────────────────────────────────────
# "that shortfall multiplied by eighteen dollars — 1800 cents — per square foot"
ATTRITION_RATE_CENTS_PER_SQFT = 1800

# ─── §3.8 Registration scoring ───────────────────────────────────────────────
# "Authority contributes 0 points for `NONE`, 15 for `INFLUENCER`,
#  25 for `RECOMMENDER` and 40 for `DECISION_MAKER`."
AUTHORITY_PTS = {"NONE": 0, "INFLUENCER": 15, "RECOMMENDER": 25, "DECISION_MAKER": 40}
# "5 points for `UNDER_50K`, 15 for `K50_250K`, 25 for `K250K_1M` and 35 for `OVER_1M`."
SPEND_PTS = {"UNDER_50K": 5, "K50_250K": 15, "K250K_1M": 25, "OVER_1M": 35}
# "The title contributes a flat 10 points"
TITLE_MATCH_PTS = 10
# "eight keywords — `CHIEF`, `VP`, `VICE PRESIDENT`, `DIRECTOR`, `HEAD OF`,
#  `BUYER`, `OWNER`, `PARTNER`"
BUYER_TITLE_KEYWORDS = [
    "CHIEF", "VP", "VICE PRESIDENT", "DIRECTOR", "HEAD OF", "BUYER", "OWNER", "PARTNER",
]
# "1.00 for `BUYER`, 1.15 for `VIP_BUYER`, and 0.50 for `STUDENT`"
CATEGORY_WEIGHT = {"BUYER": 1.00, "VIP_BUYER": 1.15, "STUDENT": 0.50}
# "A score of 60 or more ... at least 40 but below 60 ... below 40"
QUALIFY_SCORE_MIN = 60
WAITLIST_SCORE_MIN = 40

# ─── §3.7 Sponsorship ────────────────────────────────────────────────────────
# "it must also be at least 80 percent of `list_price_cents` ... so that no
#  package can be discounted by more than a fifth."
MAX_SPONSOR_DISCOUNT_PCT = 20
# "a `due_date` set to the show's `event_start` less fourteen days"
OBLIGATION_LEAD_DAYS = 14

# ─── §3.9 Citation penalty schedule ──────────────────────────────────────────
# "ten for `BOOTH_HEIGHT`, five for `NOISE`, eight for `AISLE_ENCROACHMENT`
#  and fifteen for `SALES_CONDUCT`."
PENALTY_POINTS = {
    "BOOTH_HEIGHT": 10,
    "NOISE": 5,
    "AISLE_ENCROACHMENT": 8,
    "SALES_CONDUCT": 15,
}
# "which adds three penalty points to that exhibitor's `penalty_points`"
FORFEIT_PENALTY_POINTS = 3
# "Breach costs the sponsor twenty penalty points"
BREACH_PENALTY_POINTS = 20
