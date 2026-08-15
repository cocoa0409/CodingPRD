"""Domain thresholds and canonical monetary constants from the PRD.

PRD §2.6: monetary values are integer cents; shares/rates are basis points
(10000 bps == 100%). PRD §2.5: the logical clock starts at
2026-08-01T00:00:00Z. PRD §3.7: withholding rates and safe-harbor multiplier;
§3.7 penalty constants; §3.9 ticket SLA windows.
"""

# Logical clock startup default (PRD §2.5)
CLOCK_START_ISO = "2026-08-01T00:00:00Z"

# Foreign partner withholding (PRD §3.7)
SAFE_HARBOR_MULTIPLIER_BPS = 11000
WITHHOLDING_RATE_INDIVIDUAL_BPS = 3700
WITHHOLDING_RATE_ENTITY_BPS = 2100
PENALTY_MONTHLY_BPS = 500
PENALTY_CAP_MONTHS = 5
QUARTER_DUE_DATES = {1: "04-15", 2: "06-15", 3: "09-15", 4: "12-15"}

# Ticket SLA windows in hours (PRD §3.9)
TICKET_SLA_HOURS_AMENDED_K1 = 24
TICKET_SLA_HOURS_DEFAULT = 72

# Canonical fund configuration used across scenarios. Fee variant "zero"
# (management_fee_rate_bps 0) keeps net ordinary income equal to gross.
CANONICAL_FUND = {
    "waterfall_hurdle_rate_bps": 800,
    "waterfall_catchup_bps": 2000,
    "waterfall_carry_bps": 2000,
    "foreign_ownership_cap_pct_bps": 10000,
    "management_fee_rate_bps": 0,
    "fee_discount_threshold_cents": 1,
    "fee_discount_bps": 0,
}

# Canonical waterfall fund with a nonzero fee and a huge discount threshold,
# so the discount (fee halved) always applies to plausible test incomes.
CANONICAL_FEE_FUND = {
    "waterfall_hurdle_rate_bps": 800,
    "waterfall_catchup_bps": 2000,
    "waterfall_carry_bps": 2000,
    "foreign_ownership_cap_pct_bps": 10000,
    "management_fee_rate_bps": 100,
    "fee_discount_threshold_cents": 5000000000,
    "fee_discount_bps": 5000,
}

# Canonical three-partner roster: GP 1000bps / LP 6000bps / foreign LP 3000bps.
CANONICAL_PARTNERS = [
    {
        "key": "gp1",
        "legal_name": "GP1",
        "partner_type": "US_ENTITY",
        "partner_class": "GENERAL",
        "residency_state": "DE",
        "ownership_pct_bps": 1000,
        "capital_commitment_cents": 10000000,
        "admission_date": "2025-01-01",
    },
    {
        "key": "lp1",
        "legal_name": "LP1",
        "partner_type": "US_INDIVIDUAL",
        "partner_class": "LIMITED",
        "residency_state": "CA",
        "ownership_pct_bps": 6000,
        "capital_commitment_cents": 60000000,
        "admission_date": "2025-01-01",
    },
    {
        "key": "lp2",
        "legal_name": "LP2",
        "partner_type": "FOREIGN_INDIVIDUAL",
        "partner_class": "LIMITED",
        "residency_state": "XX",
        "ownership_pct_bps": 3000,
        "capital_commitment_cents": 30000000,
        "admission_date": "2025-01-01",
    },
]

# Canonical 2025 fund-level income totals (gross ordinary, gain, interest).
CANONICAL_TOTALS = {
    "gross_ordinary_income_cents": 10000000,
    "capital_gain_cents": 20000000,
    "interest_income_cents": 5000000,
}

# Default segregation-of-duties user ids (PRD §2.1: opaque operator ids).
PREPARER_USER_ID = "prep_1"
REVIEWER_USER_ID = "rev_1"
