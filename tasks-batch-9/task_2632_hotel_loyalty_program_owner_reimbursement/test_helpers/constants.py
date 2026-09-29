"""Domain thresholds and derived-value tables stated by the PRD."""

# The logical clock's value at server start.
CLOCK_DEFAULT_UTC = "2026-08-01T00:00:00Z"
CLOCK_DEFAULT_DATE = "2026-08-01"

THRESHOLDS = {
    # A property becomes delinquent when its fee ledger is strictly above this.
    "FEE_DELINQUENCY_CENTS": 250_000,
    # Elite night bands.
    "TIER_NIGHTS_PLATINUM": 50,
    "TIER_NIGHTS_GOLD": 30,
    "TIER_NIGHTS_SILVER": 10,
    # Award pricing.
    "TIER_DISCOUNT_CAP_POINTS": 3_000,
    "AWARD_FLOOR_POINTS_PER_NIGHT": 6_000,
    "FREE_NIGHT_MIN_NIGHTS": 5,
    # Reimbursement occupancy bands.
    "OCCUPANCY_COMPRESSION": 0.95,
    "OCCUPANCY_STRONG": 0.80,
    "SOFT_DEMAND_FLOOR_CENTS_PER_NIGHT": 3_000,
    # Delinquency surcharge banding on the step-three working figure.
    "SURCHARGE_BAND_HIGH_CENTS": 500_000,
    # Benefit recovery.
    "UPGRADE_RECOVERY_CAP_CENTS": 9_000,
    "BREAKFAST_RECOVERY_CENTS_PER_NIGHT": 1_800,
    "LATE_CHECKOUT_RECOVERY_CENTS": 1_200,
    "BENEFIT_DENIAL_LIMIT": 3,
    # Complaints.
    "INFO_REQUEST_LIMIT": 2,
    # Blackout calendar.
    "BLACKOUT_CLEAR_DAYS_REQUIRED": 7,
    "BLACKOUT_ANNUAL_DAY_CAP": 60,
    # Point sales.
    "MEMBER_ANNUAL_PURCHASE_CAP_POINTS": 200_000,
    "VOLUME_TIER_HIGH_POINTS": 100_000,
    "VOLUME_TIER_LOW_POINTS": 25_000,
    "DIRECT_LIST_PRICE_CENTS_PER_1000": 1_250,
    # Liability valuation.
    "LIABILITY_UNIT_COST_CENTS_PER_1000": 600,
    "SOLVENCY_HEALTHY": 1.0000,
    "SOLVENCY_WATCH": 0.7500,
    "SOLVENCY_RATIO_WHEN_LIABILITY_ZERO": 999.0000,
    "DEFAULT_BREAKAGE_RATE_PCT": 0.20,
    "MAX_BREAKAGE_RATE_PCT": 0.35,
    # Pagination.
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "MAX_PROGRAM_FEE_PCT": 0.20,
}

# Rate-category derivation table.
RATE_CATEGORY_TABLE = {
    "TRANSIENT": {
        "base_earn_rate_per_dollar": 10,
        "is_qualifying": True,
        "program_fee_eligible": True,
        "counts_toward_elite": True,
    },
    "CORPORATE_NEGOTIATED": {
        "base_earn_rate_per_dollar": 8,
        "is_qualifying": True,
        "program_fee_eligible": True,
        "counts_toward_elite": True,
    },
    "GROUP": {
        "base_earn_rate_per_dollar": 6,
        "is_qualifying": True,
        "program_fee_eligible": True,
        "counts_toward_elite": False,
    },
    "OPAQUE_WHOLESALE": {
        "base_earn_rate_per_dollar": 0,
        "is_qualifying": False,
        "program_fee_eligible": False,
        "counts_toward_elite": False,
    },
    "EMPLOYEE_COMP": {
        "base_earn_rate_per_dollar": 0,
        "is_qualifying": False,
        "program_fee_eligible": False,
        "counts_toward_elite": False,
    },
    "AWARD": {
        "base_earn_rate_per_dollar": 0,
        "is_qualifying": False,
        "program_fee_eligible": False,
        "counts_toward_elite": False,
    },
}

# Elite bonus multipliers, keyed on the tier the earning rule reads.
BONUS_MULTIPLIER = {"BASE": 0.00, "SILVER": 0.20, "GOLD": 0.50, "PLATINUM": 0.75}

# Award tier discount percentages.
TIER_DISCOUNT_PCT = {"BASE": 0.00, "SILVER": 0.00, "GOLD": 0.05, "PLATINUM": 0.10}

# Peak surcharge percentages, keyed on the property's market tier.
PEAK_SURCHARGE_PCT = {"URBAN": 0.25, "RESORT": 0.35, "SELECT": 0.15}

# Benefit entitlement matrix, keyed on the stay's tier_at_checkin.
BENEFIT_ENTITLEMENT = {
    "BASE": [],
    "SILVER": ["UPGRADE"],
    "GOLD": ["UPGRADE", "BREAKFAST"],
    "PLATINUM": ["UPGRADE", "BREAKFAST", "LATE_CHECKOUT"],
}

TIER_RANK = {"BASE": 0, "SILVER": 1, "GOLD": 2, "PLATINUM": 3}

# Statuses that keep a stay inside the property's fee ledger derivation.
FEE_LEDGER_STAY_STATUSES = (
    "POSTED_QUALIFYING",
    "POSTED_NON_QUALIFYING",
    "DISPUTED",
    "ADJUSTED",
)

# Obligation statuses counted by Hotel.benefit_denial_count.
DENIAL_COUNTED_STATUSES = ("DENIED", "ESCALATED", "DENIED_FINAL")

TEST_DEFAULTS = {
    "PROGRAM_FEE_PCT": 0.05,
    "ROOMS_COUNT": 100,
    "OCCUPANCY_PCT": 0.82,
    "ADR_CENTS": 30_000,
    "POINTS_PER_NIGHT": 40_000,
    "AWARD_ALLOTMENT_PER_NIGHT": 5,
}
