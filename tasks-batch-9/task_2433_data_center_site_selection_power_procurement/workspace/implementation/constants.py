"""Domain constants.

Every value here is taken literally from PRD.md 3.x and cross-checked against the
scaffold `calculations[].constants` blocks. All arithmetic uses Decimal (PRD 2.7:
rounding is half-up, money 2dp, MW/MWh 3dp, percentages 2dp).
"""

from decimal import Decimal as D

# --- roles -------------------------------------------------------------------
ROLES = (
    "SiteScreeningAnalyst",
    "PortfolioDirector",
    "UtilityPlanner",
    "IncentiveNegotiator",
    "CapitalCommitteeChair",
    "PermittingAuthority",
)

# --- enums -------------------------------------------------------------------
PROGRAM_STATUSES = ("SCREENING", "SITE_COMMITTED", "ENERGIZATION_SECURED", "STALLED")
QUEUE_POLICIES = ("FIRST_COME_FIRST_SERVED", "FIRST_READY_FIRST_SERVED")
DROUGHT_STAGES = ("NORMAL", "STAGE_1", "STAGE_2", "STAGE_3")
SITE_STATUSES = ("DRAFT", "SCREENED", "COMMITTED", "DISQUALIFIED")
COOLING_TYPES = ("EVAPORATIVE", "AIR_COOLED", "HYBRID")
HAZARD_TIERS = ("LOW", "MODERATE", "SEVERE")
RISK_TIERS = ("ON_TRACK", "AT_RISK", "BREACHED")
LAND_CONTROL_STATUSES = ("NONE", "PARTIAL", "FULL")
APPLICATION_STATUSES = (
    "DRAFT",
    "SUBMITTED",
    "STUDY_COMPLETE",
    "CAPACITY_RESERVED",
    "ENERGIZATION_COMMITTED",
    "WITHDRAWN",
)
LIVE_RESERVED_STATUSES = ("CAPACITY_RESERVED", "ENERGIZATION_COMMITTED")
QUEUED_STATUSES = (
    "SUBMITTED",
    "STUDY_COMPLETE",
    "CAPACITY_RESERVED",
    "ENERGIZATION_COMMITTED",
)
NEGOTIATION_STATUSES = (
    "DRAFT",
    "AUTHORITY_COUNTER_PENDING",
    "COMPANY_OFFER_PENDING",
    "SIGNED",
    "RATIFIED",
)
AUTHORITY_LEVELS = ("STATE", "LOCAL")
PARTIES = ("COMPANY", "AUTHORITY")
ZONING_STATUSES = ("SUBMITTED", "CONTINUED", "APPROVED_WITH_CONDITIONS", "DENIED")
ZONING_OUTCOMES = ("APPROVED_WITH_CONDITIONS", "CONTINUED", "DENIED")
MITIGATION_TIERS = ("NONE", "BERM", "BERM_AND_SCREENING", "FULL_ENCLOSURE")
OBJECTION_TYPES = ("NOISE", "TRAFFIC", "VISUAL", "WATER")
PPA_TECHNOLOGIES = ("SOLAR", "WIND", "STORAGE_HYBRID", "NUCLEAR")
MATCHING_MODES = ("ANNUAL_VOLUMETRIC", "HOURLY_MATCHED")
PPA_STATUSES = ("DRAFT", "EXECUTED")
OPTION_STATUSES = ("OPTIONED", "EXERCISED", "LAPSED", "RELEASED")

# --- site screening score (PRD 3.2) -----------------------------------------
WEIGHT_POWER = D("30")
WEIGHT_FIBER = D("15")
WEIGHT_WATER = D("15")
WEIGHT_WORKFORCE = D("25")
WEIGHT_LAND = D("15")
MIN_FIBER_ROUTES = D("3")
MIN_SITE_ACRES = D("200")
WAGE_PREMIUM_THRESHOLD = D("0.15")
WAGE_PENALTY_FACTOR = D("0.8")
HAZARD_SEVERE_THRESHOLD = D("0.70")
HAZARD_MODERATE_THRESHOLD = D("0.40")
HAZARD_PENALTY = {"LOW": D("0"), "MODERATE": D("6"), "SEVERE": D("15")}

# --- load study (PRD 3.4) ----------------------------------------------------
COOLING_FLOOR_FACTOR = D("0.85")
UPGRADE_TRIGGER_RATIO = D("0.50")
HAZARD_UPLIFT = {"LOW": D("0.00"), "MODERATE": D("0.08"), "SEVERE": D("0.20")}

# --- reservation / energization (PRD 3.5) -----------------------------------
RESTUDY_TOLERANCE = D("0.10")
MAX_ENERGIZATION_DELAY_DAYS = 90
DELAY_PENALTY_USD_PER_DAY_PER_MW = D("250")

# --- incentives (PRD 3.7) ----------------------------------------------------
EQUIPMENT_SHARE = D("0.62")
ASSESSED_RATIO = D("0.85")
MILL_RATE = D("0.0225")
DISCOUNT_RATE = D("0.07")
SALES_TAX_TIER_LOW = D("0.0625")
SALES_TAX_TIER_MID = D("0.0550")
SALES_TAX_TIER_HIGH = D("0.0475")
TIER_MID_FLOOR_USD = D("500000000")
TIER_HIGH_FLOOR_USD = D("1500000000")
JOBS_THRESHOLD = 100
CLAWBACK_SHARE_HIGH_JOBS = D("0.40")
CLAWBACK_SHARE_LOW_JOBS = D("0.60")
MIN_NEGOTIATION_ROUNDS = 2

# --- zoning (PRD 3.6) --------------------------------------------------------
OBJECTION_WEIGHT = {
    "NOISE": D("1.5"),
    "TRAFFIC": D("1.0"),
    "VISUAL": D("1.2"),
    "WATER": D("2.0"),
}
TIER_BASE = {
    "NONE": D("0"),
    "BERM": D("750000"),
    "BERM_AND_SCREENING": D("2100000"),
    "FULL_ENCLOSURE": D("5400000"),
}
DBA_UNIT_COST = D("125000")
ESCROW_PCT_SMALL = D("0.10")
ESCROW_PCT_MID = D("0.15")
ESCROW_PCT_LARGE = D("0.20")
ESCROW_MID_FLOOR_USD = D("1000000")
ESCROW_HIGH_FLOOR_USD = D("4000000")
MITIGATION_RANK = {"NONE": 0, "BERM": 1, "BERM_AND_SCREENING": 2, "FULL_ENCLOSURE": 3}
MAX_ZONING_CONTINUANCES = 2

# --- renewables (PRD 3.9) ----------------------------------------------------
CURTAILMENT = {
    "SOLAR": D("0.06"),
    "WIND": D("0.11"),
    "STORAGE_HYBRID": D("0.04"),
    "NUCLEAR": D("0.01"),
}
HOURLY_DELIVERABILITY = D("0.98")
HOURS_PER_YEAR = D("8760")
PROGRAM_LOAD_FACTOR = D("0.90")
MIN_RENEWABLE_COVERAGE_PCT = D("80.0")

# --- water (PRD 3.3) ---------------------------------------------------------
STAGE_CURTAILMENT = {
    "NORMAL": D("0.00"),
    "STAGE_1": D("0.10"),
    "STAGE_2": D("0.30"),
    "STAGE_3": D("0.55"),
}

# --- pagination (PRD 2.3) ----------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0
