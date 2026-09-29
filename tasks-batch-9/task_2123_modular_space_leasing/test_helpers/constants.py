"""Domain thresholds and pre-computed expected figures drawn from the PRD.

Every money figure is an integer number of cents (PRD §2.5).
"""

# ─── Logical clock (PRD §2.6) ────────────────────────────────────────────────
CLOCK_BOOT_UTC = "2026-08-01T00:00:00Z"
CLOCK_BOOT_DATE = "2026-08-01"

# ─── Pagination (PRD §2.3) ───────────────────────────────────────────────────
PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "DEFAULT_OFFSET": 0,
}

# ─── Floorplan build-out surcharge (PRD §3.2) ────────────────────────────────
CONFIG_SURCHARGE = {
    "OFFICE_UNIT_CENTS": 42_000,
    "RESTROOM_UNIT_CENTS": 175_000,
    "PARTITION_SEGMENT_FT": 4.0,
    "PARTITION_SEGMENT_CENTS": 9_500,
    "SQFT_PER_INCLUDED_HALF_TON": 400.0,
    "HVAC_HALF_TON_CENTS": 68_000,
}

# ─── Monthly rent (PRD §3.4) ─────────────────────────────────────────────────
TERM_FACTOR = {"SHORT": 1.25, "MEDIUM": 1.10, "STANDARD": 1.00, "LONG": 0.92}
WIND_ZONE_MULTIPLIER = {1: 1.00, 2: 1.15, 3: 1.35, 4: 1.60}
TIER_DISCOUNT = {"PLATINUM": 0.06, "GOLD": 0.03, "STANDARD": 0.00, "WATCH": 0.00}
CONFIG_AMORT_MONTHS = 36

# ─── Mobilization (PRD §3.4) ─────────────────────────────────────────────────
ANCHOR_COST_CENTS = {
    "NONE": 0,
    "GROUND_ANCHOR": 85_000,
    "PIER_FOUNDATION": 240_000,
    "ENGINEERED_SLAB": 610_000,
}
MOBILIZATION_TIER1_FLOOR_CENTS = 300_000
MOBILIZATION_TIER2_FLOOR_CENTS = 800_000
MOBILIZATION_TIER1_PCT = 0.05
MOBILIZATION_TIER2_PCT = 0.09

# ─── Accessory package (PRD §3.5) ────────────────────────────────────────────
ACCESSORY_BASE_CENTS = {"STEPS": 12_500, "RAMP_ADA": 47_500, "COMBO": 55_000}
RAMP_SEGMENT_FT = 4.0
RAMP_SEGMENT_CENTS = 3_800
LANDING_CENTS = 6_200
LANDING_INTERVAL_FT = 30.0
INCHES_PER_FOOT = 12.0

# ─── Permit fee (PRD §3.6) ───────────────────────────────────────────────────
AREA_BLOCK_SQFT = 100.0
AREA_BLOCK_CENTS = 1_500

# ─── Transport cost (PRD §3.8) ───────────────────────────────────────────────
BAND1_CAP_MI = 50
BAND2_CEILING_MI = 150
BAND2_CENTS_PER_MI = 950
BAND3_CENTS_PER_MI = 1_450
JOB_TYPE_CREW_FACTOR = {
    "DELIVERY_INSTALL": 1.0,
    "TEARDOWN_RETURN": 0.75,
    "RELOCATION": 1.5,
}
OVERSIZE_SECTION_CENTS = 78_000
RELOCATION_PASSTHROUGH_PCT = 0.85

# ─── Damage (PRD §3.9) ───────────────────────────────────────────────────────
COMPONENT_BASE_CENTS = {
    "FLOOR": 32_000,
    "WALL": 18_000,
    "HVAC": 145_000,
    "ROOF": 96_000,
    "DOOR": 41_000,
    "ELECTRICAL": 73_000,
}
SEVERITY_FACTOR = {"MINOR": 0.35, "MODERATE": 1.00, "SEVERE": 2.25}
WEAR_CAP_PCT_PER_MONTH = 0.0025
DAMAGE_CAP_PCT = 0.40
MAX_DISPUTE_ROUNDS = 2

# ─── Refurbishment (PRD §3.9) ────────────────────────────────────────────────
SCOPE_FACTOR = {"COSMETIC": 0.45, "STANDARD": 1.00, "FULL": 1.85}
REFURB_RECOVERY_PCT = 0.60

# ─── Settlement (PRD §3.9) ───────────────────────────────────────────────────
EARLY_TERMINATION_PCT = 0.35
HOLDOVER_PCT = 0.25
DAYS_PER_MONTH = 30

# ─── Occupancy calendar (PRD §3.4) ───────────────────────────────────────────
REFURB_BUFFER_DAYS = 14


# ─── Pre-computed expectations for the two standard catalogs ─────────────────
# "Dallas" catalog: TX-DAL jurisdiction (wind zone 2, PIER_FOUNDATION, permit +
# ADA required) on the 24 x 60 two-section MOB-2460 model with the 2-Office ADA
# configuration, leased to a GOLD customer for 12 months from 2026-09-01.
DALLAS = {
    "CONFIG_SURCHARGE_CENTS": 713_000,
    "FLOOR_AREA_SQFT": 1440,
    "MONTHLY_BASE_RATE_CENTS": 151_435,
    "ACCESSORY_RATE_CENTS": 101_600,
    "MOBILIZATION_FEE_CENTS": 631_750,
    "QUOTED_TOTAL_CENTS": 3_668_170,
    "ACTIVATION_CHARGE_CENTS": 884_785,
    "PERMIT_FEE_CENTS": 167_500,
    "LEASE_START_DATE": "2026-09-01",
    "LEASE_END_DATE": "2027-08-26",
    "VACATE_DATE": "2027-06-15",
    "REQUIRED_RAMP_RUN_FT": 36.0,
}

# "Rural" catalog: TX-RUR jurisdiction (wind zone 1, GROUND_ANCHOR, no permit,
# no ADA) on the 20 x 48 single-section MOB-2048 model with the Open Plan
# configuration, leased to a GOLD customer for 12 months from 2026-10-01.
RURAL = {
    "CONFIG_SURCHARGE_CENTS": 452_000,
    "FLOOR_AREA_SQFT": 960,
    "MONTHLY_BASE_RATE_CENTS": 127_065,
    "MOBILIZATION_FEE_CENTS": 351_500,
    "QUOTED_TOTAL_CENTS": 1_876_280,
    "ACTIVATION_CHARGE_CENTS": 478_565,
    "LEASE_START_DATE": "2026-10-01",
    "LEASE_END_DATE": "2027-09-25",
    "VACATE_DATE": "2026-10-20",
}

# The three standard damage lines used by the Dallas chain.
DALLAS_DAMAGE = {
    "FLOOR_MODERATE_1_CENTS": 32_000,
    "WALL_MINOR_3_CENTS": 18_900,
    "HVAC_SEVERE_1_CENTS": 326_250,
    "GROSS_CENTS": 377_150,
    "WEAR_ALLOWANCE_CENTS": 18_900,
    "CHARGEABLE_CENTS": 358_250,
    "FINAL_SETTLEMENT_CENTS": 3_864_975,
    "FINAL_SETTLEMENT_WITHOUT_DAMAGE_CENTS": 3_506_725,
}

# The single wear-and-tear HVAC line used by the Rural chain.
RURAL_DAMAGE = {
    "HVAC_MODERATE_1_CENTS": 145_000,
    "GROSS_CENTS": 145_000,
    "WEAR_ALLOWANCE_CENTS": 15_500,
    "CHARGEABLE_CENTS": 129_500,
    "FINAL_SETTLEMENT_CENTS": 1_097_265,
}
