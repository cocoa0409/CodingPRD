"""System constants for the Community-Supported Fishery API.

Every value here traces to a verbatim PRD sentence (PRD sections 2.10, 3.1,
3.2, 3.3, 3.5, 3.6, 3.7, 3.8, 3.9).  Where SCAFFOLD.yaml and PRD.md disagree
the PRD is the contract -- see DOCK_FEE_CENTS below.
"""
from decimal import Decimal

API_PREFIX = "/csf"

# --- roles (PRD 2.1) -------------------------------------------------------
ROLE_ADMIN = "CsfAdmin"
ROLE_MEMBER = "Member"
ROLE_VENDOR = "Vendor"
ROLE_HUB = "HubOperator"
ROLE_QUALITY = "QualityOfficer"
ALL_ROLES = (ROLE_ADMIN, ROLE_MEMBER, ROLE_VENDOR, ROLE_HUB, ROLE_QUALITY)

# --- logical clock (PRD 2.4) ----------------------------------------------
CLOCK_DEFAULT_UTC = "2026-05-01T00:00:00Z"

# --- vocabulary (PRD 2.10) -------------------------------------------------
SPECIES = ("COD", "HADDOCK", "POLLOCK", "HALIBUT", "SALMON", "TUNA",
           "LOBSTER", "SCALLOP", "OYSTER")
SPECIES_TIER_MAP = {
    "COD": "WHITEFISH", "HADDOCK": "WHITEFISH", "POLLOCK": "WHITEFISH",
    "HALIBUT": "PREMIUM_FINFISH", "SALMON": "PREMIUM_FINFISH",
    "TUNA": "PREMIUM_FINFISH",
    "LOBSTER": "SHELLFISH", "SCALLOP": "SHELLFISH", "OYSTER": "SHELLFISH",
}
SPECIES_TIERS = ("WHITEFISH", "PREMIUM_FINFISH", "SHELLFISH")
GEAR_TYPES = ("HOOK_AND_LINE", "TRAP", "DIVE", "GILLNET", "TRAWL")
SUSTAINABILITY_BANDS = ("GREEN", "YELLOW", "ORANGE", "RED")
CUSTODY_LEGS = ("DOCK_TO_HUB", "HUB_HOLD", "HUB_TO_DOOR")
DESTINATION_TYPES = ("HUB", "ROUTE")
RECALL_REASONS = ("PATHOGEN", "MISLABEL", "COLD_CHAIN", "REGULATORY")
AMBIENT_BANDS = ("COOL", "MILD", "HOT")
FEE_TIERS = ("TIER_1", "TIER_2", "TIER_3")
SHARE_SIZES = ("SMALL", "MEDIUM", "LARGE")
DELIVERY_FREQUENCIES = ("WEEKLY", "BIWEEKLY")
FULFILLMENT_MODES = ("HUB_PICKUP", "HOME_DELIVERY")
PAYMENT_BASES = ("PREPAID_FULL_SEASON", "INSTALLMENT")
DISPOSITIONS = ("RELEASE", "DISCOUNT", "DISCARD")
COMPLIANCE_STATUSES = ("COMPLIANT", "PROBATION", "SUSPENDED")

# --- share plan pricing (PRD 3.1) -----------------------------------------
SHARE_SIZE_BASE_CENTS = {"SMALL": 2400, "MEDIUM": 3600, "LARGE": 5200}
SPECIES_TIER_MULTIPLIER = {
    "WHITEFISH": Decimal("1.00"),
    "PREMIUM_FINFISH": Decimal("1.25"),
    "SHELLFISH": Decimal("1.55"),
}
FREQUENCY_FACTOR = {"WEEKLY": Decimal("1.00"), "BIWEEKLY": Decimal("1.10")}
SHARE_SIZE_WEIGHT_UNITS = {"SMALL": 1, "MEDIUM": 2, "LARGE": 3}
LB_PER_WEIGHT_UNIT = Decimal("2.5")
SHARE_MIN_FLOOR_LB = {
    "SMALL": Decimal("1.00"), "MEDIUM": Decimal("2.00"), "LARGE": Decimal("3.00"),
}
PREPAY_DISCOUNT_PCT = Decimal("0.08")
RETAIL_CENTS_PER_LB = {"WHITEFISH": 1150, "PREMIUM_FINFISH": 1850, "SHELLFISH": 2650}

# --- allocation (PRD 3.4) --------------------------------------------------
SURPLUS_SECONDARY_MAX_PCT = Decimal("0.60")
ALLOCATION_POUND_PRECISION = Decimal("0.01")

# --- cold chain (PRD 3.6) --------------------------------------------------
COLD_CHAIN_CUMULATIVE_BUDGET_MIN = 45
COLD_CHAIN_SINGLE_EXCURSION_MAX_MIN = 20
COLD_CHAIN_RELEASE_LIMIT_MIN = 60
COLD_CHAIN_DISCOUNT_LIMIT_MIN = 90
QUALITY_RELEASE_TEMP_C = Decimal("7.0")
QUALITY_DISCOUNT_CREDIT_PCT = Decimal("0.30")
VENDOR_DISCOUNT_HOLDBACK_RELEASE_PCT = Decimal("0.50")

# --- packing and the fee chain (PRD 3.7) -----------------------------------
PACK_SMALL_MAX_LB = Decimal("6.00")
PACK_MEDIUM_MAX_LB = Decimal("14.00")
PACK_BASE_FEE_CENTS = {"SMALL": 300, "MEDIUM": 450, "LARGE": 600}
GEL_PACK_FEE_CENTS = 175
GEL_PACK_HOURS = {
    "COOL": {"SMALL": Decimal("3.0"), "MEDIUM": Decimal("6.0"), "LARGE": Decimal("8.0")},
    "MILD": {"SMALL": Decimal("2.0"), "MEDIUM": Decimal("4.0"), "LARGE": Decimal("5.5")},
    "HOT": {"SMALL": Decimal("1.5"), "MEDIUM": Decimal("3.0"), "LARGE": Decimal("4.0")},
}
ZONE_BASE_FEE_CENTS = {"TIER_1": 500, "TIER_2": 800, "TIER_3": 1250}
REMOTE_SURCHARGE_CENTS = 250
FREE_SURCHARGE_THRESHOLD_CENTS = 6000

# --- hub pickup (PRD 3.1, 3.7) ---------------------------------------------
DEFAULT_GRACE_MINUTES = 90
NO_SHOW_WARN_THRESHOLD = 1
NO_SHOW_RESTRICT_THRESHOLD = 2

# --- skips and transfers (PRD 3.8) -----------------------------------------
SKIP_CAP_PER_SEASON = 4
DEFAULT_LANDING_COMMIT_LEAD_HOURS = 72
TRANSFER_FEE_CENTS = 2500

# --- sustainability (PRD 3.3) ----------------------------------------------
GEAR_BASE_SCORE = {"HOOK_AND_LINE": 90, "TRAP": 78, "DIVE": 85,
                   "GILLNET": 60, "TRAWL": 45}
SUSTAINABILITY_GREEN_MIN = 80
SUSTAINABILITY_YELLOW_MIN = 60
SUSTAINABILITY_ORANGE_MIN = 40
BAND_PREMIUM_FACTOR = {
    "GREEN": Decimal("1.00"), "YELLOW": Decimal("0.85"),
    "ORANGE": Decimal("0.50"), "RED": Decimal("0.00"),
}

# --- vendor settlement (PRD 3.9) -------------------------------------------
CSF_PREMIUM_BRACKET_1_MAX_LB = Decimal("100.00")
CSF_PREMIUM_BRACKET_2_MAX_LB = Decimal("300.00")
CSF_PREMIUM_RATE_1_CENTS_PER_LB = 60
CSF_PREMIUM_RATE_2_CENTS_PER_LB = 45
CSF_PREMIUM_RATE_3_CENTS_PER_LB = 30
# Adjudication of friction 1: DOCK_FEE_CENTS is 800, not the 4500 that
# SCAFFOLD.yaml's global constant block carries.  PRD 3.9 states "a flat charge
# of 800 cents levied on every landing regardless of its size" and every worked
# settlement figure in PRD 3.9 (deductions 2174 = 800 + 120 + 1140 + 114) is
# consistent with 800 and inconsistent with 4500.  The PRD is the contract.
DOCK_FEE_CENTS = 800
ICE_HANDLING_CENTS_PER_LB = 12
OFFLOAD_LABOR_CENTS_PER_MINUTE = 95
HOLDBACK_PCT = Decimal("0.10")
QUOTA_WARNING_PCT = Decimal("0.85")
HANDLING_LEVY_PCT = Decimal("0.0125")
DISCARD_OFFSET_PCT = Decimal("0.25")
TRUE_UP_MIN_REFUND_CENTS = 5000
