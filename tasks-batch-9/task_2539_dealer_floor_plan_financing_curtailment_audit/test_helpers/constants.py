"""Domain thresholds and reusable test literals taken from the PRD."""

# --- logical clock ---------------------------------------------------------
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

# --- numeric thresholds the PRD states -------------------------------------
THRESHOLDS = {
    "DEMO_HIGH_MILEAGE_THRESHOLD_MILES": 3000,
    "DEMO_HIGH_MILEAGE_HAIRCUT_BPS": 500,
    "AGED_INVOICE_HAIRCUT_DAYS": 45,
    "AGED_INVOICE_HAIRCUT_BPS": 250,
    "MAX_FLOOR_AGE_DAYS": 90,
    "LATE_FEE_BPS": 200,
    "LATE_FEE_CAP_CENTS": 50000,
    "MAX_EXTENSION_DAYS_PER_REQUEST": 45,
    "MAX_EXTENSION_DAYS_PER_UNIT": 60,
    "MAX_APPROVED_EXCEPTIONS_PER_UNIT": 2,
    "AUDIT_NOTICE_DAYS": 7,
    "MIN_UNANNOUNCED_GAP_DAYS": 14,
    "SOT_SUSPENSION_EXPOSURE_CENTS": 10_000_000,
    "SOT_CURE_DAYS": 10,
    "COVENANT_BREACH_SUSPENSION_COUNT": 2,
    "COVENANT_TNW_BPS_OF_LIMIT": 1000,
    "COVENANT_MIN_DSCR_LENDER_STANDARD": 1.2500,
    "REINSTATEMENT_MIN_DSCR_DEALER_ADJUSTED": 1.4000,
    "COVENANT_MAX_TRAILING_SOT_INCIDENTS": 1,
    "ADVANCE_REVERSAL_WINDOW_DAYS": 5,
    "RISK_POINTS_PER_OPEN_SOT_INCIDENT": 15,
    "RISK_POINTS_PER_DELINQUENT_UNIT": 10,
    "RISK_POINTS_COVENANT_FAIL": 20,
    "DSCR_ZERO_DENOMINATOR_SENTINEL": 9999.9999,
}

# Audit cadence in days keyed by risk rating.
AUDIT_FREQUENCY_DAYS_BY_RATING = {"A": 180, "B": 90, "C": 45, "D": 21}

# Inclusive lower bounds of each risk rating band.
RISK_RATING_LOWER_BOUNDS = {"A": 90, "B": 75, "C": 55}

# --- pagination ------------------------------------------------------------
DEFAULT_LIMIT = 10
MAX_LIMIT = 100

# --- reusable credit-line shape -------------------------------------------
# The credit-line payload used by nearly every fixture chain.
TEST_DEFAULTS = {
    "CREDIT_LIMIT_CENTS": 500_000_000,
    "ADVANCE_RATE_BPS_NEW": 10000,
    "ADVANCE_RATE_BPS_USED": 9000,
    "ADVANCE_RATE_BPS_DEMONSTRATOR": 8500,
    "MAX_UNIT_ADVANCE_CENTS_NEW": 20_000_000,
    "MAX_UNIT_ADVANCE_CENTS_USED": 10_000_000,
    "MAX_UNIT_ADVANCE_CENTS_DEMONSTRATOR": 10_000_000,
    "CLASS_SUBLIMIT_CENTS_USED": 100_000_000,
    "CLASS_SUBLIMIT_CENTS_DEMONSTRATOR": 50_000_000,
    "CURTAILMENT_GRACE_DAYS": 5,
    "UNIT_INVOICE_AMOUNT_CENTS": 3_000_000,
}
