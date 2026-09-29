"""Domain thresholds and pinned literals stated by the PRD.

Every value below is quoted or arithmetically implied by PRD §2 and §3 prose.
Nothing here is a test expectation on its own — the numbers are shared so that
test files never restate a threshold in two different places.
"""

# ─── The logical clock (PRD §2.4) ─────────────────────────────────────────────

CLOCK_START = "2026-08-01T00:00:00Z"
"""At server startup the logical clock reads exactly 2026-08-01T00:00:00Z."""

# The instant nearly every scenario runs at.
CLOCK_T0 = "2026-08-05T08:00:00Z"
CLOCK_DATE_T0 = "2026-08-05"

# ─── Pagination (PRD §2.3) ────────────────────────────────────────────────────

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ─── Targeting score (PRD §3.1) ───────────────────────────────────────────────

SEVERITY_WEIGHT_GROUND_TRUTHED = 2.2
SEVERITY_WEIGHT_MODELED = 1.6
SEVERITY_DIVISOR = 2
HAIL_MM_CAP = 60
POPULATION_CAP = 250_000
POPULATION_DIVISOR = 5_000
SWATH_BONUS_KM2_THRESHOLD = 400
SWATH_BONUS_POINTS = 8
COMPETITOR_PENALTY_PER_SHOP = 1.5
COMPETITOR_CAP = 12
TARGETING_SCORE_FLOOR = 60

# ─── Facility posture and throughput (PRD §2.6, §3.2) ─────────────────────────

VEHICLES_PER_TECH_PER_DAY = 1.5
OCCUPANCY_RATIO_DECIMALS = 4

# ─── Crew deployment (PRD §3.3) ───────────────────────────────────────────────

REST_BUFFER_DAYS = 1

# ─── Paintless / conventional pricing (PRD §3.5) ──────────────────────────────

DENT_TIER_LIGHT_MAX = 15
DENT_TIER_MEDIUM_MAX = 50
TIER_MULTIPLIER_LIGHT = 1.00
TIER_MULTIPLIER_MEDIUM = 0.85
TIER_MULTIPLIER_HEAVY = 0.70
ALUMINUM_MULTIPLIER = 1.30

# ─── Triage and the net-billable waterfall (PRD §3.6) ─────────────────────────

TOTAL_LOSS_THRESHOLD_PCT = 0.75
DISCOUNT_TIER_1_FLOOR_CENTS = 250_000
DISCOUNT_TIER_2_FLOOR_CENTS = 500_000
DISCOUNT_PCT_NONE = 0.00
DISCOUNT_PCT_TIER_1 = 0.02
DISCOUNT_PCT_TIER_2 = 0.04

# ─── Repair floor and crew pay (PRD §3.7) ─────────────────────────────────────

MAX_REWORK_COUNT = 2
LABOR_POOL_PCT = 0.55
POOL_SPLIT_PCT = 0.50
TIER_WEIGHT_APPRENTICE = 0.80
TIER_WEIGHT_JOURNEYMAN = 1.00
TIER_WEIGHT_MASTER = 1.25

# ─── Supplement negotiation (PRD §3.8) ────────────────────────────────────────

SUPPLEMENT_AUTO_APPROVE_FLOOR_CENTS = 15_000
SUPPLEMENT_CUMULATIVE_CAP_PCT = 0.40
SUPPLEMENT_MAX_ROUNDS = 3

# ─── Release, warranty and rental (PRD §3.9) ──────────────────────────────────

WARRANTY_PREFIX = "PDR-"
WARRANTY_COUNTER_WIDTH = 4
WARRANTY_DAYS = 90
RENTAL_MINIMUM_DAYS = 1

# ─── Sentinel identifiers ─────────────────────────────────────────────────────

MISSING_UUID = "00000000-0000-4000-8000-000000000000"
"""A syntactically valid UUID that never names a persisted row."""

# ─── Reusable payload literals ────────────────────────────────────────────────

DEFAULT_STORM_EVENT = {
    "name": "Wichita Supercell",
    "region_state_code": "KS",
    "max_hail_size_mm": 55,
    "swath_area_km2": 520,
    "swath_confidence": "GROUND_TRUTHED",
    "vehicle_population_estimate": 40000,
    "competitor_shop_count": 3,
    "first_hail_at": "2026-08-04T21:00:00Z",
}
DEFAULT_STORM_EVENT_TARGETING_SCORE = 72

DEFAULT_FACILITY = {
    "name": "Wichita North Lot",
    "state_code": "KS",
    "address": "1200 N Broadway",
    "staging_slot_count": 6,
    "pay_model": "FLAT",
}

DEFAULT_JURISDICTION = "City of Wichita"
PERMIT_WINDOW_FROM = "2026-08-01"
PERMIT_WINDOW_TO = "2026-09-30"

DEFAULT_INSURER = {
    "name": "Prairie Mutual",
    "naic_code": "18021",
    "direct_bill_enabled": True,
}

SECOND_INSURER = {
    "name": "Cottonwood Casualty",
    "naic_code": "22114",
    "direct_bill_enabled": True,
}

DEFAULT_RATE_AGREEMENT = {
    "effective_from": "2026-08-01",
    "matrix_rate_dime_cents": 2213,
    "matrix_rate_nickel_cents": 3012,
    "matrix_rate_quarter_cents": 4202,
    "matrix_rate_half_dollar_cents": 5611,
    "labor_rate_cents_per_hour": 6500,
    "panel_cap_cents": 140000,
    "admin_fee_pct": 0.05,
    "admin_fee_cap_cents": 25000,
    "supplement_auto_approve_pct": 0.1,
    "rental_cap_days": 10,
    "rental_daily_rate_cents": 4500,
}

DEFAULT_VEHICLE = {
    "vin": "1HGCM82633A004352",
    "model_year": 2021,
    "make": "Honda",
    "model": "Accord",
    "acv_cents": 2450000,
    "owner_name": "D. Reyes",
    "rental_required": True,
}

SECOND_VEHICLE = {
    "vin": "2T1BURHE0JC014728",
    "model_year": 2019,
    "make": "Toyota",
    "model": "Corolla",
    "acv_cents": 1980000,
    "owner_name": "M. Lang",
    "rental_required": False,
}

THIRD_VEHICLE = {
    "vin": "3VWFA81H4WM123456",
    "model_year": 2020,
    "make": "Volkswagen",
    "model": "Jetta",
    "acv_cents": 1750000,
    "owner_name": "P. Osei",
    "rental_required": False,
}

DEPLOYMENT_START = "2026-08-05"
DEPLOYMENT_END = "2026-09-15"
