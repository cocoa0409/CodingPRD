"""Domain constants, thresholds and literals taken from the PRD narrative.

Everything here is quoted from §2 or §3 of the PRD; nothing is invented. Tests
import these rather than re-typing magic numbers so that a single reading of the
contract governs every assertion.
"""

# --- The logical clock (§2.6) ----------------------------------------------- #
# "At startup the logical clock reads exactly `2026-08-01T00:00:00Z`".
INITIAL_CLOCK_UTC = "2026-08-01T00:00:00Z"

# --- Pagination (§2.3) ------------------------------------------------------ #
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# --- Program load (§3.1) ---------------------------------------------------- #
HOURS_PER_YEAR = 8760
PROGRAM_LOAD_FACTOR = 0.90

# --- Screening score (§3.2) ------------------------------------------------- #
WEIGHT_POWER = 30
WEIGHT_FIBER = 15
WEIGHT_WATER = 15
WEIGHT_WORKFORCE = 25
WEIGHT_LAND = 15
MIN_FIBER_ROUTES = 3
MIN_SITE_ACRES = 200
WAGE_PREMIUM_THRESHOLD = 0.15
WAGE_PENALTY_FACTOR = 0.8
HAZARD_SEVERE_THRESHOLD = 0.70
HAZARD_MODERATE_THRESHOLD = 0.40
HAZARD_PENALTY = {"LOW": 0, "MODERATE": 6, "SEVERE": 15}
SCREENING_SCORE_MIN = 0.0
SCREENING_SCORE_MAX = 100.0

HAZARD_TIERS = ("LOW", "MODERATE", "SEVERE")
COOLING_TYPES = ("EVAPORATIVE", "AIR_COOLED", "HYBRID")

# --- Cooling water (§3.3) --------------------------------------------------- #
DROUGHT_STAGES = ("NORMAL", "STAGE_1", "STAGE_2", "STAGE_3")
STAGE_CURTAILMENT = {
    "NORMAL": 0.00,
    "STAGE_1": 0.10,
    "STAGE_2": 0.30,
    "STAGE_3": 0.55,
}

# --- Load studies and upgrades (§3.4) --------------------------------------- #
COOLING_FLOOR_FACTOR = 0.85
UPGRADE_TRIGGER_RATIO = 0.50
HAZARD_UPLIFT = {"LOW": 0.00, "MODERATE": 0.08, "SEVERE": 0.20}

QUEUE_POLICIES = ("FIRST_COME_FIRST_SERVED", "FIRST_READY_FIRST_SERVED")

# --- Reservation, energization and risk (§3.5) ------------------------------ #
RESTUDY_TOLERANCE = 0.10
DEFAULT_COMMISSIONING_BUFFER_DAYS = 90
MAX_ENERGIZATION_DELAY_DAYS = 90
DELAY_PENALTY_USD_PER_DAY_PER_MW = 250
RISK_TIERS = ("ON_TRACK", "AT_RISK", "BREACHED")

# --- Zoning, objections, mitigation and escrow (§3.6) ---------------------- #
OBJECTION_WEIGHT = {"NOISE": 1.5, "TRAFFIC": 1.0, "VISUAL": 1.2, "WATER": 2.0}
MITIGATION_TIERS = ("NONE", "BERM", "BERM_AND_SCREENING", "FULL_ENCLOSURE")
MITIGATION_RANK = {"NONE": 0, "BERM": 1, "BERM_AND_SCREENING": 2, "FULL_ENCLOSURE": 3}
TIER_BASE_USD = {
    "NONE": 0,
    "BERM": 750000,
    "BERM_AND_SCREENING": 2100000,
    "FULL_ENCLOSURE": 5400000,
}
DBA_UNIT_COST_USD = 125000
FULL_ENCLOSURE_EXCESS_DBA = 10
FULL_ENCLOSURE_OPPOSITION = 12
BERM_AND_SCREENING_EXCESS_DBA = 5
BERM_AND_SCREENING_OPPOSITION = 6
BERM_OPPOSITION = 3
ESCROW_PCT_SMALL = 0.10
ESCROW_PCT_MID = 0.15
ESCROW_PCT_LARGE = 0.20
ESCROW_MID_FLOOR_USD = 1000000
ESCROW_HIGH_FLOOR_USD = 4000000
MAX_ZONING_CONTINUANCES = 2
ZONING_DENIED_REASON = "ZONING_DENIED"

# --- Incentive negotiation money (§3.7) ------------------------------------ #
EQUIPMENT_SHARE = 0.62
ASSESSED_RATIO = 0.85
MILL_RATE = 0.0225
DISCOUNT_RATE = 0.07
SALES_TAX_TIER_LOW = 0.0625
SALES_TAX_TIER_MID = 0.0550
SALES_TAX_TIER_HIGH = 0.0475
TIER_MID_FLOOR_USD = 500000000
TIER_HIGH_FLOOR_USD = 1500000000
JOBS_THRESHOLD = 100
CLAWBACK_SHARE_HIGH_JOBS = 0.40
CLAWBACK_SHARE_LOW_JOBS = 0.60
MIN_NEGOTIATION_ROUNDS = 2
AUTHORITY_LEVELS = ("STATE", "LOCAL")
NEGOTIATION_PARTIES = ("COMPANY", "AUTHORITY")

# --- Land options (§3.8) ---------------------------------------------------- #
DEFAULT_PREMIUM_CREDIT_PCT = 0.5
LAND_CONTROL_STATUSES = ("NONE", "PARTIAL", "FULL")
OPTION_STATUSES = ("OPTIONED", "EXERCISED", "LAPSED", "RELEASED")

# --- Renewable procurement (§3.9) ------------------------------------------ #
CURTAILMENT = {"SOLAR": 0.06, "WIND": 0.11, "STORAGE_HYBRID": 0.04, "NUCLEAR": 0.01}
HOURLY_DELIVERABILITY = 0.98
MIN_RENEWABLE_COVERAGE_PCT = 80.0
PPA_TECHNOLOGIES = ("SOLAR", "WIND", "STORAGE_HYBRID", "NUCLEAR")
PPA_MATCHING_MODES = ("ANNUAL_VOLUMETRIC", "HOURLY_MATCHED")

# --- Site commitment and the program rollup (§3.10) ------------------------ #
SITE_STATUSES = ("DRAFT", "SCREENED", "COMMITTED", "DISQUALIFIED")
APPLICATION_STATUSES = (
    "DRAFT",
    "SUBMITTED",
    "STUDY_COMPLETE",
    "CAPACITY_RESERVED",
    "ENERGIZATION_COMMITTED",
    "WITHDRAWN",
)
NEGOTIATION_STATUSES = (
    "DRAFT",
    "AUTHORITY_COUNTER_PENDING",
    "COMPANY_OFFER_PENDING",
    "SIGNED",
    "RATIFIED",
)
ZONING_STATUSES = ("SUBMITTED", "CONTINUED", "APPROVED_WITH_CONDITIONS", "DENIED")
PPA_STATUSES = ("DRAFT", "EXECUTED")
PROGRAM_STATUSES = ("SCREENING", "SITE_COMMITTED", "ENERGIZATION_SECURED", "STALLED")
SITE_DISQUALIFIED_WITHDRAWAL_REASON = "SITE_DISQUALIFIED"

# --- Canonical scenario payload values ------------------------------------- #
# One environment recurs across the whole suite: a 300 MW program in North
# Carolina, a 500 MW serving utility on PJM and a 900 mgal basin.
PROGRAM_NAME = "Hyperscale Alpha"
PROGRAM_TARGET_LOAD_MW = 300
PROGRAM_REQUIRED_ENERGIZATION_DATE = "2029-06-30T00:00:00Z"
PROGRAM_CAPITAL_BUDGET_USD = 60000000
# round(300 * 8760 * 0.90, 3)
PROGRAM_ANNUAL_LOAD_MWH = 2365200.0

UTILITY_NAME = "Piedmont Power"
UTILITY_STATE_CODE = "NC"
UTILITY_BALANCING_AUTHORITY = "PJM"
UTILITY_TOTAL_CAPACITY_MW = 500
UTILITY_STUDY_FEE_PER_MW_USD = 1200
UTILITY_UPGRADE_RATE_USD_PER_MW = 85000
UTILITY_ENERGIZATION_LEAD_DAYS = 540

WATER_SOURCE_NAME = "Yadkin Basin"
WATER_SOURCE_BASIN_CODE = "YAD-03"
WATER_SOURCE_ANNUAL_PERMITTED_MGAL = 900

SITE_NAME = "Site Alpha"
SITE_STATE_CODE = "NC"
SITE_COUNTY = "Rowan"
SITE_GROSS_ACRES = 300

APPLICATION_REQUESTED_MW = 300
APPLICATION_WINDOW_START = "2029-01-01T00:00:00Z"
APPLICATION_WINDOW_END = "2029-12-31T00:00:00Z"

# The screening package that scores Site Alpha at 83.00 with a MODERATE tier.
SCREEN_EVAPORATIVE = {
    "transmission_headroom_mw": 240,
    "fiber_route_count": 3,
    "seismic_hazard_index": 0.20,
    "flood_hazard_index": 0.45,
    "wind_hazard_index": 0.30,
    "craft_labor_supply_index": 1600,
    "construction_peak_headcount": 2000,
    "wage_premium_pct": 0.10,
    "cooling_type": "EVAPORATIVE",
    "annual_water_demand_mgal": 250,
}

# The same package with an air-cooled design, which must declare a demand of 0.
SCREEN_AIR_COOLED = dict(
    SCREEN_EVAPORATIVE, cooling_type="AIR_COOLED", annual_water_demand_mgal=0
)

# The load study that splits 318 MW nameplate into 293.52 MW diversified.
LOAD_STUDY_BASE = {
    "it_load_mw": 240,
    "cooling_load_mw": 66,
    "ancillary_load_mw": 12,
    "diversity_factor": 0.92,
}

# The standing terms of the canonical STATE incentive package.
COMPANY_TERMS = {
    "sales_tax_exemption_pct": 1.0,
    "abatement_years": 10,
    "abatement_pct": 0.80,
    "jobs_commitment": 150,
    "capex_commitment_usd": 3200000000,
}
AUTHORITY_TERMS = {
    "sales_tax_exemption_pct": 0.75,
    "abatement_years": 5,
    "abatement_pct": 0.60,
    "jobs_commitment": 60,
    "capex_commitment_usd": 800000000,
}

# A storage-hybrid agreement that credits exactly 80.00 percent coverage on a
# 300 MW program: round(1971000 * (1 - 0.04), 3) == 1892160.0 MWh.
PPA_AT_COVERAGE_FLOOR = {
    "counterparty_name": "Catawba Storage Partners",
    "technology": "STORAGE_HYBRID",
    "contracted_capacity_mw": 600,
    "annual_generation_mwh": 1971000,
    "hourly_matched_mwh": 1500000,
    "strike_price_usd_per_mwh": 40.00,
    "matching_mode": "ANNUAL_VOLUMETRIC",
    "delivery_start": "2029-07-01T00:00:00Z",
    "delivery_end": "2044-06-30T00:00:00Z",
}

# The two parcels that together assemble the full 300-acre campus footprint.
OPTION_APN_100 = {
    "parcel_apn": "APN-100",
    "phase_index": 1,
    "acres": 240,
    "option_premium_usd": 1250000,
    "purchase_price_usd": 42000000,
    "premium_credit_pct": 0.5,
    "window_start": "2027-01-01T00:00:00Z",
    "window_end": "2027-12-31T00:00:00Z",
}
OPTION_APN_200 = {
    "parcel_apn": "APN-200",
    "phase_index": 2,
    "acres": 60,
    "option_premium_usd": 900000,
    "purchase_price_usd": 11000000,
    "premium_credit_pct": 0.5,
    "window_start": "2027-01-01T00:00:00Z",
    "window_end": "2029-12-31T00:00:00Z",
}

# Derived figures the canonical chain produces, quoted once here so that the
# tests that assert them agree with the fixtures that build them.
EXPECTED_SCREENING_SCORE_ALPHA = 83.00
EXPECTED_NAMEPLATE_PEAK_MW = 318.0
EXPECTED_DIVERSIFIED_PEAK_MW = 293.52
EXPECTED_UPGRADE_COST_USD = 26945136.00
EXPECTED_STUDY_FEE_USD = 360000.00
EXPECTED_MITIGATION_COST_USD = 2975000.00
EXPECTED_CONDITIONS_ESCROW_USD = 446250.00

# A sentinel identifier that resolves to no row in any collection.
UNKNOWN_UUID = "00000000-0000-0000-0000-000000009999"
