"""Domain constants fixed by the PRD: reference defaults, bands, tiers, clock.

Every value here is quoted from the PRD's own default tables or step functions.
Tests import these rather than repeating magic numbers, so that a constant used
by twenty assertions is written down exactly once.
"""

# ───────────────────────── logical clock ─────────────────────────
# "Before any call the clock reads exactly 2026-08-01T00:00:00Z and never falls
# back to wall-clock time; it never rewinds."
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

# ────────────────── WarrantyProgram reference defaults ──────────────────
DEFAULT_COVERAGE_MONTHS = 96
DEFAULT_COVERAGE_MILES = 100000
DEFAULT_RETENTION_SCHEDULE = [
    {"through_months": 48, "through_miles": 50000, "min_retention_pct": 80.00},
    {"through_months": 96, "through_miles": 100000, "min_retention_pct": 70.00},
]
DEFAULT_PACK_REPLACEMENT_RETENTION_PCT = 60.00
DEFAULT_MODULE_REPLACEMENT_CAP = 3
DEFAULT_CELL_DELTA_PACK_THRESHOLD_MV = 250
DEFAULT_GOODWILL_MONTHS = 12
DEFAULT_GOODWILL_MILES = 15000
DEFAULT_LIABILITY_CAP_CENTS = 50000000
DEFAULT_INFO_REQUEST_LIMIT = 2
DEFAULT_LAB_TOLERANCE_PCT = 2.00
DEFAULT_DISPUTE_WINDOW_DAYS = 30
DEFAULT_DIAGNOSTIC_FEE_CENTS = 12000
DEFAULT_MODULE_UNIT_PRICE_CENTS = 145000
DEFAULT_PACK_PRICE_NEW_CENTS = 1420000
DEFAULT_PACK_PRICE_REMAN_CENTS = 890000
DEFAULT_LABOR_HOURS_MODULE = 3.25
DEFAULT_LABOR_HOURS_PACK = 6.50
DEFAULT_SURCHARGE_UN3480_CENTS = 4000
DEFAULT_SURCHARGE_UN3481_CENTS = 2500
DEFAULT_SURCHARGE_UN3536_CENTS = 18000
DEFAULT_SNAPSHOT_FRESHNESS_DAYS = 30
DEFAULT_SNAPSHOT_WINDOW_SIZE = 5
DEFAULT_SNAPSHOT_MIN_COUNT = 3
DEFAULT_REMAN_MIN_SOH_PCT = 85.00
DEFAULT_ALLOW_NEW_PACK_SUBSTITUTION = False

# ────────────────── ServiceCenter reference defaults ──────────────────
DEFAULT_CENTER_REGION = "US-WEST"
DEFAULT_CENTER_HV_LEVEL = "L3"
DEFAULT_CENTER_HAS_PACK_LIFT = False
DEFAULT_CENTER_INSULATION_TESTER_CAL_DUE_AT = "2027-01-01T00:00:00Z"
DEFAULT_CENTER_HV_BAY_COUNT = 2
DEFAULT_CENTER_LABOR_RATE_CENTS_PER_HOUR = 18333

# ─────────────────── Technician reference defaults ───────────────────
DEFAULT_TECHNICIAN_HV_CERT_LEVEL = "L3"
DEFAULT_TECHNICIAN_CERT_EXPIRES_AT = "2027-06-01T00:00:00Z"

# ──────────────────── Vehicle / pack reference defaults ────────────────────
DEFAULT_MODEL_CODE = "MX-90"
DEFAULT_NOMINAL_CAPACITY_KWH = 80.000
DEFAULT_MODULE_COUNT = 16
DEFAULT_PACK_GROSS_WEIGHT_KG = 483.296
DEFAULT_PACK_TYPE = "NEW"
DEFAULT_STOCK_REGION = "US-WEST"

# ─────────────────── TelematicsSnapshot optional defaults ───────────────────
DEFAULT_SNAPSHOT_CHARGE_CYCLES = 400
DEFAULT_SNAPSHOT_MAX_CELL_DELTA_MV = 40
DEFAULT_SNAPSHOT_COOLANT_TEMP_C = 20.0
DEFAULT_SNAPSHOT_DCFC_SESSION_COUNT = 0

# ───────────────── temperature correction step function ─────────────────
# "below 0.0 -> 1.06; [0.0, 15.0) -> 1.03; [15.0, 35.0] -> 1.00; above 35.0 -> 0.97"
TEMPERATURE_CORRECTION_BANDS = [
    (-0.1, 1.06),
    (0.0, 1.03),
    (15.0, 1.00),
    (35.0, 1.00),
    (35.0001, 0.97),
]


def correction_factor(coolant_temp_c: float) -> float:
    """The PRD's four-band temperature correction step function."""
    if coolant_temp_c < 0.0:
        return 1.06
    if coolant_temp_c < 15.0:
        return 1.03
    if coolant_temp_c <= 35.0:
        return 1.00
    return 0.97


# ─────────────────────── administrative fee tiers ───────────────────────
ADMIN_FEE_TIER_LOW_CENTS = 0
ADMIN_FEE_TIER_MID_CENTS = 7500
ADMIN_FEE_TIER_HIGH_CENTS = 15000
ADMIN_FEE_MID_THRESHOLD_CENTS = 200000
ADMIN_FEE_HIGH_THRESHOLD_CENTS = 500000


def admin_fee_for_oem_share(oem_share_cents: int) -> int:
    """Administrative fee keyed on the OEM share, not on the remedy cost."""
    if oem_share_cents < ADMIN_FEE_MID_THRESHOLD_CENTS:
        return ADMIN_FEE_TIER_LOW_CENTS
    if oem_share_cents < ADMIN_FEE_HIGH_THRESHOLD_CENTS:
        return ADMIN_FEE_TIER_MID_CENTS
    return ADMIN_FEE_TIER_HIGH_CENTS


# ───────────────────────── compliance scoring ─────────────────────────
COMPLIANCE_SCORE_BASE = 100
COMPLIANCE_PENALTY_PER_REJECTION = 15
COMPLIANCE_PENALTY_PER_LATE_NOTIFICATION = 40
COMPLIANCE_DECERTIFY_AT_OR_BELOW = 20


def compliance_score(rejected_shipment_count: int, late_notification_count: int) -> int:
    """100 minus 15 per rejected shipment minus 40 per late notification, floored at 0."""
    return max(
        0,
        COMPLIANCE_SCORE_BASE
        - COMPLIANCE_PENALTY_PER_REJECTION * rejected_shipment_count
        - COMPLIANCE_PENALTY_PER_LATE_NOTIFICATION * late_notification_count,
    )


# ─────────────────── hazmat declaration constants ───────────────────
SOC_LIMIT_RESTRICTED_PCT = 30.00
SOC_LIMIT_STANDARD_PCT = 50.00

# ───────────────────── regulatory notification deadlines ─────────────────────
NOTIFICATION_DEADLINE_HOURS = {"S4": 24, "S3": 72, "S2": None, "S1": None}

# ───────────────────────── other fixed windows ─────────────────────────
CONSENT_EXPIRY_DAYS = 14
TECHNICIAN_COOLDOWN_MINUTES = 60
