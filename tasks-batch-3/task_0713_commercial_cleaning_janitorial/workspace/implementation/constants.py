"""Domain constants, all pinned from PRD §3 and the scaffold §1.3."""
from decimal import Decimal

# --- labor_load ---
PROD_RATE = {"LIGHT": Decimal("4000"), "MEDIUM": Decimal("3000"), "HEAVY": Decimal("2000")}
WEEKS_PER_MONTH = Decimal("4.33")

# --- bid_buildup ---
SUPPLY_RATE_CENTS_PER_SQFT = {
    "LIGHT": Decimal("1.0"),
    "MEDIUM": Decimal("1.5"),
    "HEAVY": Decimal("3.0"),
}
EQUIP_AMORT_CENTS = 7500
OVERHEAD_PCT = Decimal("0.15")
BURDEN_T1 = Decimal("1.20")
BURDEN_T2 = Decimal("1.28")
BURDEN_T3 = Decimal("1.35")
BURDEN_BREAK_1 = Decimal("160")
BURDEN_BREAK_2 = Decimal("320")

# --- proposal_pricing ---
DISCOUNT_BREAK_1_CENTS = 500000
DISCOUNT_BREAK_2_CENTS = 800000
DISCOUNT_T1_PCT = Decimal("0.03")
DISCOUNT_T2_PCT = Decimal("0.05")
MIN_MARGIN_PCT = Decimal("15.0")

# --- renewal_escalation ---
CPI_PCT = Decimal("0.032")
FLAT_INCREASE_CENTS = 15000

# --- crew shift overlap ---
CREW_TRAVEL_BUFFER_MIN = 30

# --- retention health cascades ---
HEALTH_ABORT_PENALTY = 10
HEALTH_SUSPEND_PENALTY = 5
HEALTH_RENEW_BONUS = 5
HEALTH_LAPSE_PENALTY = 10
HEALTH_UPSELL_BONUS = 3

# --- enums ---
INDUSTRIES = {"OFFICE", "MEDICAL", "INDUSTRIAL", "RETAIL", "EDUCATION"}
SOIL_LEVELS = {"LIGHT", "MEDIUM", "HEAVY"}
LOADING_METHODS = {"ESTIMATE", "LOADED"}
ESCALATION_METHODS = {"CPI", "FLAT"}

# --- logical clock default ---
DEFAULT_CLOCK_ISO = "2026-03-01T00:00:00Z"

# --- roles ---
ROLES = {"SalesRep", "BidEstimator", "OperationsManager", "AccountManager", "PlatformAdmin"}
