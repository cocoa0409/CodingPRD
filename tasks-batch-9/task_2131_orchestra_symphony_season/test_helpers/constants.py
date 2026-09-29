"""Domain thresholds and constants stated in the PRD narratives."""

# --- Single ticket dynamic pricing (PRD 3.7) -------------------------------
DEMAND_MULTIPLIER_BP = {"LOW": 9000, "MODERATE": 10000, "HIGH": 11500, "PEAK": 13000}
DEMAND_BAND_FILL_BP_THRESHOLDS = {"PEAK": 8000, "HIGH": 5000, "MODERATE": 2000}
DONOR_DISCOUNT_BP = {
    "NONE": 0,
    "FRIEND": 250,
    "SUSTAINER": 500,
    "BENEFACTOR": 1000,
    "LAUREATE": 1500,
}
PRICE_FLOOR_BP = 8500
PRICE_CEILING_BP = 12000

# --- Subscription package pricing (PRD 3.5 / 3.6) --------------------------
PACKAGE_DISCOUNT_BP = {"8_plus": 1500, "5_to_7": 1000, "3_to_4": 500, "under_3": 0}
LOYALTY_CAP_BP = 2000
LOYALTY_BP_PER_RENEWAL_YEAR = 100

# --- Donor standing (PRD 3.4) ----------------------------------------------
DONOR_THRESHOLDS_CENTS = {
    "FRIEND": 250_000,
    "SUSTAINER": 1_000_000,
    "BENEFACTOR": 2_500_000,
    "LAUREATE": 5_000_000,
}
DONOR_POINTS = {
    "NONE": 0,
    "FRIEND": 50,
    "SUSTAINER": 150,
    "BENEFACTOR": 400,
    "LAUREATE": 900,
}
POINTS_PER_CONSECUTIVE_RENEWAL_YEAR = 100
POINTS_PER_SENIORITY_YEAR = 10

# --- Program book advertising (PRD 3.8) ------------------------------------
AD_SIZE_RATE_CENTS = {"FULL_PAGE": 120_000, "HALF_PAGE": 70_000, "QUARTER_PAGE": 40_000}
AD_VOLUME_DISCOUNT_TIERS_BP = [(500_000, 1200), (250_000, 800), (100_000, 400)]
PLACEMENT_FEE_BP = {"BACK_COVER": 2500, "INSIDE_FRONT_COVER": 1500, "RUN_OF_BOOK": 0}

# --- Union agreement defaults (PRD 3.1) ------------------------------------
UNION_DEFAULTS = {
    "max_service_minutes": 150,
    "overtime_rate_cents_per_minute": 400,
    "min_rest_minutes_between_services": 90,
    "max_services_per_day": 2,
    "doubling_premium_bp": 1250,
    "mandatory_break_minutes": 20,
    "principal_premium_bp": 2000,
}
DOUBLING_COUNT_LIMIT = 2
BREAK_RULE_THRESHOLD_MINUTES = 90
NEGOTIATION_ROUND_LIMIT = 3

# --- Other declared defaults ------------------------------------------------
DEFAULT_CHANGEOVER_BUFFER_MINUTES = 60
DEFAULT_LOYALTY_DISCOUNT_BP = 500
DEFAULT_MIN_RENEWAL_PRIORITY_SCORE = 0
HOLD_EXPIRY_OPS_RUN_OFFSET = 2
DONOR_BENEFIT_MAX_RANK = 2

# --- Logical clock ----------------------------------------------------------
INITIAL_LOGICAL_CLOCK_UTC = "2026-08-01T00:00:00Z"

# --- Values used across the generated tests --------------------------------
TEST_DEFAULTS = {
    "CLOCK": "2026-09-01T00:00:00Z",
    "BASE_TICKET_PRICE_CENTS": 6000,
    "RENEWAL_DEADLINE_UTC": "2026-10-01T00:00:00Z",
    "SCALE_SERVICE_FEE_CENTS": 20000,
}
