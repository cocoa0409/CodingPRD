"""Domain thresholds — numeric constants drawn from the PRD's stated formulas."""

# ---------------------------------------------------------------------------
# Proof-torque requirement (PRD §3.1)
# ---------------------------------------------------------------------------
BASE_TORQUE_PER_MM = {"WRENCH": 4.2, "SOCKET": 6.5, "PLIER": 2.8}
ALLOY_FACTOR = {"CR_V": 1.00, "CR_MO": 1.15, "S2": 1.30}
CHANNEL_FACTOR = {"BRANDED": 1.10, "PRIVATE_LABEL": 1.00, "PROFESSIONAL": 1.25}
# Per-millimetre size-tier adder: 0 at or below 10 mm, 1.5 above 10 up to and
# including 19 mm, 3.0 above 19 mm.
SIZE_TIER_ADDER = {"SMALL": 0.0, "MEDIUM": 1.5, "LARGE": 3.0}
SIZE_TIER_SMALL_MAX_MM = 10
SIZE_TIER_MEDIUM_MAX_MM = 19
TORQUE_FLOOR_NM = 12.0
TORQUE_CEILING_NM = 900.0

# ---------------------------------------------------------------------------
# Test adjudication (PRD §3.4) and certification margins (PRD §3.5)
# ---------------------------------------------------------------------------
ALLOY_MIN_HARDNESS_HRC = {"CR_V": 47.0, "CR_MO": 50.0, "S2": 55.0}
CHANNEL_HARDNESS_MARGIN_HRC = {"BRANDED": 1.0, "PRIVATE_LABEL": 0.0, "PROFESSIONAL": 2.5}
SALT_SPRAY_REQUIRED_HOURS = {"BRANDED": 96, "PRIVATE_LABEL": 48, "PROFESSIONAL": 168}
MECHANISM_CYCLE_REQUIREMENT = 5000
DIMENSIONAL_TOLERANCE_MM = 0.15
MANDATORY_TESTS = {
    "WRENCH": ["HARDNESS", "PROOF_TORQUE", "DIMENSIONAL", "SALT_SPRAY"],
    "SOCKET": ["HARDNESS", "PROOF_TORQUE", "DIMENSIONAL", "SALT_SPRAY"],
    "PLIER": ["HARDNESS", "DIMENSIONAL", "SALT_SPRAY", "MECHANISM_CYCLE"],
}
# Test types that may only be scheduled once the metal has reached a stage.
TEST_STAGE_REQUIREMENT = {
    "DIMENSIONAL": "MACHINED",
    "PROOF_TORQUE": "MACHINED",
    "SALT_SPRAY": "PLATED",
    "MECHANISM_CYCLE": "ASSEMBLED",
}
PROCESS_STAGE_ORDER = ["FORGED", "HEAT_TREATED", "MACHINED", "PLATED", "ASSEMBLED"]

# ---------------------------------------------------------------------------
# Furnaces, campaigns and rework (PRD §3.2, §3.5)
# ---------------------------------------------------------------------------
RAMP_BUFFER_MINUTES = 45
MIN_SOAK_MINUTES = 60
REWORK_LIMIT = 2
LINEAGE_MAX_DEPTH = 3

# ---------------------------------------------------------------------------
# Packaging (PRD §3.6)
# ---------------------------------------------------------------------------
PACK_TYPE_DISCOUNT = {"RETAIL_DISPLAY": 1.00, "SECURITY": 1.00, "MULTIPACK": 0.88}
SECURITY_SURCHARGE_LOW_CENTS = 350
SECURITY_SURCHARGE_MID_CENTS = 700
SECURITY_SURCHARGE_LOW_MAX_SUBTOTAL_CENTS = 5_000
SECURITY_SURCHARGE_MID_MAX_SUBTOTAL_CENTS = 20_000
SECURITY_SURCHARGE_HIGH_RATE = 0.04
RETAIL_DISPLAY_MIN_MEMBERS = 1
RETAIL_DISPLAY_MAX_MEMBERS = 12
SECURITY_MIN_MEMBERS = 1
SECURITY_MAX_MEMBERS = 3
MULTIPACK_MIN_MEMBERS = 2
MULTIPACK_MIN_TOTAL_QUANTITY = 3

# ---------------------------------------------------------------------------
# Warranty reserve arithmetic (PRD §3.7)
# ---------------------------------------------------------------------------
CHANNEL_RESERVE_PCT = {"BRANDED": 0.62, "PRIVATE_LABEL": 0.45, "PROFESSIONAL": 0.78}
WARRANTY_TIER_FACTOR = {"LIFETIME": 1.00, "LIMITED_5Y": 0.70, "NONE": 0.00}

# ---------------------------------------------------------------------------
# Fraud scoring (PRD §3.7 intake variant, §3.8 adjudication variant)
# ---------------------------------------------------------------------------
FRAUD_POINTS_PER_CLAIM = 9
FRAUD_DUPLICATE_SERIAL_POINTS = 18
FRAUD_COUNTERFEIT_POINTS = 25
FRAUD_ALLOWANCE = {"CONSUMER": 0, "PRO_ACCOUNT": 2}
FRAUD_INTAKE_WINDOW_DAYS = 365
FRAUD_SCORE_MIN = 0
FRAUD_SCORE_MAX = 100

# ---------------------------------------------------------------------------
# Brand-protection roll-up (PRD §3.9)
# ---------------------------------------------------------------------------
EVIDENCE_POINTS = {"WEAK": 5, "MODERATE": 15, "STRONG": 30}
UNIT_SCALE_LOW_MAX = 50
UNIT_SCALE_MID_MAX = 500
UNIT_SCALE_POINTS = {"LOW": 0, "MID": 8, "HIGH": 20}
CHANNEL_EXPOSURE = {"BRANDED": 1.0, "PRIVATE_LABEL": 0.6, "PROFESSIONAL": 0.8}
BRAND_RISK_CAP = 100
POSTURE_RESTRICT_AT = 40
POSTURE_SUSPEND_AT = 85

# ---------------------------------------------------------------------------
# Global system contract (PRD §2.3, §2.8)
# ---------------------------------------------------------------------------
DEFAULT_PAGE_LIMIT = 10
MIN_PAGE_LIMIT = 1
MAX_PAGE_LIMIT = 100
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

# ---------------------------------------------------------------------------
# Shared window literals used by composite setups
# ---------------------------------------------------------------------------
CAMPAIGN_WINDOW_START = "2026-08-02T06:00:00Z"
CAMPAIGN_WINDOW_END = "2026-08-02T10:00:00Z"
CAMPAIGN_BUFFERED_END = "2026-08-02T10:45:00Z"
HARDNESS_WINDOW = ("2026-08-03T08:00:00Z", "2026-08-03T09:00:00Z")
TORQUE_WINDOW = ("2026-08-03T10:00:00Z", "2026-08-03T11:00:00Z")
DIMENSIONAL_WINDOW = ("2026-08-03T12:00:00Z", "2026-08-03T13:00:00Z")
SALT_SPRAY_WINDOW = ("2026-08-04T00:00:00Z", "2026-08-08T00:00:00Z")
MECHANISM_WINDOW = ("2026-08-09T08:00:00Z", "2026-08-09T18:00:00Z")

TEST_DEFAULTS = {
    "SKU_LIST_PRICE_CENTS": 3300,
    "LOT_UNIT_COUNT": 500,
    "SPECIMEN_POOL_TOTAL": 40,
    "RESERVE_FUNDED_CENTS": 5_000_000,
    "FRAUD_SCORE_THRESHOLD": 60,
    "COUPON_CAPACITY": 24,
    "MAX_CHARGE_KG": 900,
    "CHARGE_KG": 800,
    "SOAK_MINUTES": 120,
}
