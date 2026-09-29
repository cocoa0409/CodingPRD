"""Domain constants of the Motor Fuel Tax API, all taken from the PRD."""

from decimal import Decimal

# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------

API_PREFIX = "/mft"
CLOCK_PATH = "/_clock/set_current_utc"

# --------------------------------------------------------------------------
# The logical clock
# --------------------------------------------------------------------------

#: "Before any client sets it, the logical clock reads exactly 2026-08-01T00:00:00Z".
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

# --------------------------------------------------------------------------
# Gallons, rates and rounding
# --------------------------------------------------------------------------

HOME_STATE = "MN"

#: Per-product tax rate expressed in cents per gallon.
TAX_RATES_CENTS_PER_GALLON = {
    "GASOLINE": Decimal("28.6"),
    "UNDYED_DIESEL": Decimal("30.9"),
    "DYED_DIESEL": Decimal("0.0"),
    "JET_FUEL": Decimal("5.0"),
    "AVIATION_GAS": Decimal("10.0"),
    "ETHANOL_E100": Decimal("28.6"),
    "BIODIESEL_B100": Decimal("30.9"),
}

#: Product codes in the order the tax computation walks them.
PRODUCT_ORDER = [
    "GASOLINE",
    "UNDYED_DIESEL",
    "DYED_DIESEL",
    "JET_FUEL",
    "AVIATION_GAS",
    "ETHANOL_E100",
    "BIODIESEL_B100",
]

# --------------------------------------------------------------------------
# Bonding (PRD 2.7)
# --------------------------------------------------------------------------

NEW_LICENSEE_ASSUMED_LIABILITY_CENTS = 500000
BOND_COVERAGE_MONTHS = 3
BOND_TYPE_MULTIPLIERS = {
    "SUPPLIER": Decimal("1.0"),
    "DISTRIBUTOR": Decimal("1.0"),
    "BLENDER": Decimal("1.0"),
    "TRANSPORTER": Decimal("0.5"),
    "RETAILER": Decimal("0.25"),
}
BOND_SUSPENSION_MULTIPLIER = Decimal("2.0")
BOND_ROUNDING_STEP_CENTS = 100000
MIN_BOND_CENTS = 200000
MAX_BOND_CENTS = 100000000
MIN_BOND_INSTRUMENT_CENTS = 100000
BOND_BASIS_MAX_RETURNS = 3

#: required_bond_cents for a brand-new licensee of each type, with no filed returns.
NEW_LICENSEE_REQUIRED_BOND_CENTS = {
    "SUPPLIER": 1500000,
    "DISTRIBUTOR": 1500000,
    "BLENDER": 1500000,
    "TRANSPORTER": 800000,
    "RETAILER": 400000,
}

# --------------------------------------------------------------------------
# Returns, interest and penalty (PRD 3.5)
# --------------------------------------------------------------------------

DAILY_INTEREST_RATE = Decimal("0.00025")
PENALTY_TIER_30_DAYS = Decimal("0.05")
PENALTY_TIER_60_DAYS = Decimal("0.10")
PENALTY_TIER_BEYOND_60_DAYS = Decimal("0.15")
PENALTY_LARGE_DEFICIENCY_SURCHARGE = Decimal("0.05")
PENALTY_LARGE_DEFICIENCY_THRESHOLD_CENTS = 1000000
PENALTY_FLOOR_CENTS = 5000

SCHEDULE_CODES = [
    "SCH_1_RECEIVED_TAX_PAID",
    "SCH_2_RECEIVED_TAX_UNPAID",
    "SCH_5_DELIVERED_TAX_COLLECTED",
    "SCH_6_EXEMPT_SALES",
    "SCH_7_EXPORTS",
    "SCH_10_DYED_SALES",
]

# --------------------------------------------------------------------------
# Exemption certificates (PRD 3.3)
# --------------------------------------------------------------------------

EXEMPTION_PRODUCT_SETS = {
    "GOVERNMENT": ["GASOLINE", "UNDYED_DIESEL"],
    "AGRICULTURE": ["UNDYED_DIESEL"],
    "EXPORT": [
        "GASOLINE",
        "UNDYED_DIESEL",
        "JET_FUEL",
        "AVIATION_GAS",
        "ETHANOL_E100",
        "BIODIESEL_B100",
    ],
}

# --------------------------------------------------------------------------
# Cross-matching (PRD 3.6)
# --------------------------------------------------------------------------

DEFAULT_TOLERANCE_GALLONS = Decimal("5.00")
AUTO_ESCALATION_THRESHOLD_GALLONS = Decimal("10000.00")
MAX_INQUIRY_ROUNDS = 3

# --------------------------------------------------------------------------
# Refunds (PRD 3.7)
# --------------------------------------------------------------------------

REFUND_RATE_CENTS_PER_GALLON = Decimal("30.9")
REFUND_MINIMUM_PAYABLE_CENTS = 2000
REEFER_MONTHLY_CAP_GALLONS = Decimal("1500.00")
REEFER_REJECT_FACTOR = 10
PTO_ALLOCATION_PERCENTAGES = {
    "CONCRETE_MIXER": Decimal("0.30"),
    "REFUSE_PACKER": Decimal("0.25"),
    "BULK_TANKER_PUMP": Decimal("0.15"),
}

# --------------------------------------------------------------------------
# Roadside enforcement (PRD 3.8)
# --------------------------------------------------------------------------

DYED_PENALTY_FLOOR_CENTS = 100000
DYED_PENALTY_CENTS_PER_GALLON = 1000
DYED_PENALTY_MULTIPLIERS = {0: Decimal("1.0"), 1: Decimal("2.0"), 2: Decimal("3.0")}
DYED_SUSPENSION_THRESHOLD = 2

# --------------------------------------------------------------------------
# Risk scoring and audits (PRD 3.9)
# --------------------------------------------------------------------------

AUDIT_SELECTION_THRESHOLD = 60
LATE_FILING_POINTS_PER_UNIT = 8
LATE_FILING_POINTS_CAP = 24
DYED_VIOLATION_POINTS_PER_UNIT = 15
DYED_VIOLATION_POINTS_CAP = 30
UNREPORTED_GALLONS_PER_POINT = Decimal("500")
VARIANCE_TERM_CAP = 60
FREQUENCY_POINTS_PER_DISCREPANCY = 6
FREQUENCY_TERM_CAP = 60
RISK_SCORE_CAP = 100
ASSESSMENT_PENALTY_RATE_EVASION = Decimal("0.50")
ASSESSMENT_PENALTY_RATE_NO_EVASION = Decimal("0.10")
MAX_AUDIT_RESPONSE_ROUNDS = 2

# --------------------------------------------------------------------------
# Pagination (PRD 2.3)
# --------------------------------------------------------------------------

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
MIN_OFFSET = 0

__all__ = [name for name in dir() if not name.startswith("_") and name != "Decimal"]
