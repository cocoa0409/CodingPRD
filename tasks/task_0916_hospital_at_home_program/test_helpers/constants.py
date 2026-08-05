"""Program thresholds and rates stated in the PRD.

Every value here is quoted verbatim from the PRD narrative — the admission
gauntlet (§3.1), the daily verdict (§3.4), travel banding (§3.3), the delivery
handling fee (§3.6), meal accrual (§3.7), the escalation ladder (§3.8) and the
claim arithmetic (§3.9).
"""

# ─── Logical clock (PRD §2.4) ──────────────────────────────────────────────
DEFAULT_CLOCK_UTC = "2026-05-01T00:00:00Z"

# ─── Admission gauntlet (PRD §3.1, §3.2) ───────────────────────────────────
SERVICE_RADIUS_KM = 40.0
EVAL_WINDOW_HOURS = 24
QUALIFYING_CONDITION_CODES = [
    "CHF_EXAC",
    "COPD_EXAC",
    "CAP_PNEUMONIA",
    "CELLULITIS",
    "UTI_COMPLICATED",
    "COVID_MODERATE",
]
ELIGIBLE_REFERRAL_ORIGINS = ["ED", "INPATIENT_WARD"]

# ─── Daily verdict (PRD §3.4) ──────────────────────────────────────────────
WAIVER_REQUIRED_IN_PERSON_VISITS = 2
FFS_REQUIRED_IN_PERSON_VISITS = 1
MAX_MONITORING_LAPSE_MINUTES_PER_DAY = 240

# ─── Visits (PRD §3.3) ─────────────────────────────────────────────────────
TURNAROUND_BUFFER_MINUTES = 15
TRAVEL_BAND_1_MAX_KM = 10.0
TRAVEL_BAND_1_RATE_USD_PER_KM = 0.92
TRAVEL_BAND_2_MAX_KM = 25.0
TRAVEL_BAND_2_RATE_USD_PER_KM = 0.74
TRAVEL_BAND_3_RATE_USD_PER_KM = 0.61
MIN_VISIT_TRAVEL_PAYMENT_USD = 8.00

# ─── Device kits (PRD §3.5) ────────────────────────────────────────────────
KIT_MAX_REFURB_CYCLES_BEFORE_RETIREMENT = 5

# ─── Delivery handling fee (PRD §3.6) ──────────────────────────────────────
CONTROLLED_HANDLING_BASE_USD = 45.00
CONTROLLED_WITNESS_FEE_USD = 12.50
NON_CONTROLLED_HANDLING_BASE_USD = 12.00
COLD_CHAIN_SURCHARGE_USD = 22.00
HANDLING_FEE_PER_KG_USD = 1.40
HANDLING_FEE_PER_REDELIVERY_USD = 9.00
HANDLING_FEE_FLOOR_USD = 15.00
HANDLING_FEE_CAP_USD = 120.00
COLD_CHAIN_MAX_EXCURSION_MINUTES = 30
MAX_REDELIVERIES = 2

# ─── Meals (PRD §3.7) ──────────────────────────────────────────────────────
MEAL_CREDIT_PER_DAY_USD_FFS = 28.00
MEAL_CREDIT_PER_DAY_USD_WAIVER = 0.00
MIN_DAILY_DELIVERY_COUNT = 1
MAX_DAILY_DELIVERY_COUNT = 3

# ─── Escalation ladder (PRD §3.8) ──────────────────────────────────────────
STANDARD_TIER_SLA_MINUTES = {1: 10, 2: 20, 3: 30, 4: 15}
HIGH_ACUITY_TIER_SLA_MINUTES = {1: 5, 2: 10, 3: 15, 4: 8}
BED_HOLD_MINUTES = 120

# ─── Claim arithmetic (PRD §3.9) ───────────────────────────────────────────
WAIVER_PER_DIEM_USD = 1850.00
FFS_DRG_BASE_USD = 9600.00
FFS_OUTLIER_PER_DAY_USD = 640.00
FFS_OUTLIER_DAY_THRESHOLD = 6
CLAIM_WITHHOLD_TIER_THRESHOLD_USD = 9600.00
CLAIM_WITHHOLD_RATE_LOW = 0.02
CLAIM_WITHHOLD_RATE_HIGH = 0.05
APPEAL_RECOVERY_RATE = 0.60
MAX_APPEALS = 2

# ─── Pagination (PRD §2.3) ─────────────────────────────────────────────────
DEFAULT_PAGE_LIMIT = 10
MIN_PAGE_LIMIT = 1
MAX_PAGE_LIMIT = 100

# ─── Convenience test defaults ─────────────────────────────────────────────
TEST_DEFAULTS = {
    "CLOCK": "2026-06-01T08:00:00Z",
    "SERVICE_DATE": "2026-06-01",
    "EVAL_AT": "2026-06-01T06:00:00Z",
    "HOME_DISTANCE_KM": 5.0,
    "PHYSICIAN_USER_ID": "phys-1",
    "NURSE_USER_ID": "rn-1",
    "PARAMEDIC_USER_ID": "medic-1",
    "LOGISTICS_USER_ID": "log-1",
    "PHARMACY_USER_ID": "pharm-9",
}
