"""
Business constants for the Bridge Inspection & Load Rating Program API.

Every literal in this module is transcribed from PRD.md. Nothing here is
invented: the enum member lists, the weights, the ladders, the unit repair
costs, the rounding steps and the threshold values are all named explicitly in
the PRD sections cited beside them.
"""

# ─── Logical clock (PRD §2.4) ──────────────────────────────────────────────
# "Before any client sets it, the logical clock reads exactly
#  `2026-08-01T00:00:00Z`; this startup default is mandatory".
MANDATORY_CLOCK_DEFAULT = "2026-08-01T00:00:00Z"

# The instant every scenario in this suite pins before doing anything else.
BASE_CLOCK = "2026-09-01T00:00:00Z"
FIELD_DAY_CLOCK = "2026-09-02T12:00:00Z"
QA_DAY_CLOCK = "2026-09-03T09:00:00Z"

CLOCK_PATH = "/_clock/set_current_utc"


# ─── Roles (PRD §2.1) ──────────────────────────────────────────────────────
ROLE_PROGRAM_ADMIN = "ProgramAdmin"
ROLE_BRIDGE_INSPECTOR = "BridgeInspector"
ROLE_QA_REVIEWER = "QaReviewer"
ROLE_RATING_ENGINEER = "RatingEngineer"
ROLE_DISTRICT_ENGINEER = "DistrictEngineer"
ROLE_PERMIT_OFFICER = "PermitOfficer"
ROLE_FHWA_REVIEWER = "FhwaReviewer"

ALL_ROLES = [
    ROLE_PROGRAM_ADMIN,
    ROLE_BRIDGE_INSPECTOR,
    ROLE_QA_REVIEWER,
    ROLE_RATING_ENGINEER,
    ROLE_DISTRICT_ENGINEER,
    ROLE_PERMIT_OFFICER,
    ROLE_FHWA_REVIEWER,
]

# "Four roles are entity-backed against the `Personnel` roster."
ENTITY_BACKED_ROLES = [
    ROLE_BRIDGE_INSPECTOR,
    ROLE_QA_REVIEWER,
    ROLE_RATING_ENGINEER,
    ROLE_DISTRICT_ENGINEER,
]

# "Three roles are opaque operators."
OPAQUE_ROLES = [ROLE_PROGRAM_ADMIN, ROLE_PERMIT_OFFICER, ROLE_FHWA_REVIEWER]


# ─── Enumerations (PRD §3.1 – §3.9) ────────────────────────────────────────
STRUCTURE_TYPES = ["GIRDER", "TRUSS", "ARCH", "SUSPENSION", "CULVERT"]

INSPECTION_TYPES = ["ROUTINE", "UNDERWATER", "FRACTURE_CRITICAL", "SPECIAL", "DAMAGE"]
INSPECTION_STATUSES = ["DRAFT", "SUBMITTED", "IN_QA", "ACCEPTED", "VOIDED"]

ELEMENT_KEYS = [
    "DECK",
    "JOINT",
    "RAILING",
    "GIRDER",
    "BEARING",
    "PIER_CAP",
    "COLUMN",
    "ABUTMENT",
]
ELEMENT_GROUPS = ["DECK_GROUP", "SUPERSTRUCTURE", "SUBSTRUCTURE"]
UNITS = ["SQM", "M", "EA"]

# "`DECK`, `JOINT` and `RAILING` belong to `DECK_GROUP`; `GIRDER` and `BEARING`
#  belong to `SUPERSTRUCTURE`; `PIER_CAP`, `COLUMN` and `ABUTMENT` belong to
#  `SUBSTRUCTURE`." (PRD §3.2)
ELEMENT_GROUP_OF = {
    "DECK": "DECK_GROUP",
    "JOINT": "DECK_GROUP",
    "RAILING": "DECK_GROUP",
    "GIRDER": "SUPERSTRUCTURE",
    "BEARING": "SUPERSTRUCTURE",
    "PIER_CAP": "SUBSTRUCTURE",
    "COLUMN": "SUBSTRUCTURE",
    "ABUTMENT": "SUBSTRUCTURE",
}

FINDING_SEVERITIES = ["URGENT", "IMMEDIATE"]
FINDING_STATUSES = ["OPEN", "MITIGATED", "RESOLVED"]
NOTIFICATION_STATUSES = ["PENDING", "OWNER_NOTIFIED", "FHWA_REPORTED"]
RESTRICTION_ACTIONS = ["NONE", "RESTRICT", "CLOSE"]
NOTIFICATION_TIERS = ["BRIDGE_OWNER", "FHWA"]
NOTIFICATION_CHANNELS = ["EMAIL", "PHONE", "PORTAL"]

RATING_METHODS = ["LRFR", "LFR", "ASD"]
RATING_VEHICLES = ["HL93", "HS20"]
RATING_STATUSES = ["DRAFT", "SEALED", "APPROVED", "REJECTED", "SUPERSEDED"]

PERMIT_SPEED_CATEGORIES = ["NORMAL", "CRAWL"]
PERMIT_STATUSES = [
    "RECEIVED",
    "ANALYZED",
    "APPROVED",
    "APPROVED_WITH_CONDITIONS",
    "DENIED",
    "REVOKED",
]
PERMIT_RECOMMENDATIONS = ["PENDING", "APPROVE", "APPROVE_WITH_CONDITIONS", "DENY"]
ANALYSIS_RESULTS = ["ALLOWED", "ALLOWED_WITH_CONDITIONS", "DENIED"]
ANALYSIS_REASONS = [
    "RF_ADEQUATE",
    "RF_MARGINAL",
    "RF_INSUFFICIENT",
    "NO_APPROVED_RATING",
    "BRIDGE_CLOSED",
]

EVALUATION_METHODS = ["HEC18_SCREENING", "DETAILED_HYDRAULIC", "FIELD_OBSERVATION"]
FOUNDATION_TYPES = ["SPREAD_FOOTING", "PILE", "DRILLED_SHAFT", "UNKNOWN"]
SCOUR_STATUSES = ["NOT_EVALUATED", "SCOUR_CRITICAL", "LOW_RISK", "STABILIZED"]
DERIVED_SCOUR_STATUSES = ["SCOUR_CRITICAL", "LOW_RISK", "STABILIZED"]

POA_STATUSES = ["REQUIRED", "DRAFT", "SUBMITTED", "APPROVED"]
COUNTERMEASURE_TYPES = ["NONE", "RIPRAP", "MONITORING_ONLY", "STRUCTURAL"]

SERVICE_POSTURES = ["OPEN", "POSTED", "RESTRICTED", "CLOSED"]

RANKING_POLICIES = ["CONDITION_BASED", "RISK_BASED"]
CYCLE_STATUSES = ["PLANNING", "LOCKED", "SUBMITTED", "CLOSED"]
CANDIDATE_STATUSES = ["IDENTIFIED", "PROGRAMMED", "DEFERRED", "WITHDRAWN"]
CANDIDATE_ORIGINS = ["MANUAL", "AUTO_FROM_INSPECTION"]
WORK_TYPES = ["REPLACEMENT", "REHABILITATION", "REPAIR", "PRESERVATION"]

SUBMISSION_TYPES = ["NBI_ANNUAL", "ELEMENT_DATA", "SCOUR_POA"]
SUBMISSION_STATUSES = ["BUILDING", "SUBMITTED", "ACCEPTED", "REJECTED"]
REJECTION_REASON_CODES = ["NONE", "COMPLIANCE_BELOW_THRESHOLD", "DATA_GAPS"]

QUALIFICATION_STATUSES = ["CURRENT", "EXPIRED"]


# ─── Element health index (PRD §3.2) ───────────────────────────────────────
# "multiply the good quantity by a full weight of 1.00, the fair quantity by
#  0.80, the poor quantity by 0.40 and the severe quantity by 0.00"
CS_WEIGHT_CS1 = 1.00
CS_WEIGHT_CS2 = 0.80
CS_WEIGHT_CS3 = 0.40
CS_WEIGHT_CS4 = 0.00

# "The element weights are: deck 0.30, girder 0.25, bearing 0.10, pier cap
#  0.10, column 0.10, abutment 0.10, joint 0.05 and railing 0.05." (PRD §3.3)
ELEMENT_WEIGHTS = {
    "DECK": 0.30,
    "GIRDER": 0.25,
    "BEARING": 0.10,
    "PIER_CAP": 0.10,
    "COLUMN": 0.10,
    "ABUTMENT": 0.10,
    "JOINT": 0.05,
    "RAILING": 0.05,
}

# "an index of at least 97 rates 9, at least 90 rates 8, at least 80 rates 7,
#  at least 70 rates 6, at least 60 rates 5, at least 45 rates 4, at least 30
#  rates 3, at least 15 rates 2, at least 5 rates 1, and anything below 5
#  rates 0." (PRD §3.3) — descending, first satisfied rung wins.
NBI_RATING_LADDER = [
    (97, 9),
    (90, 8),
    (80, 7),
    (70, 6),
    (60, 5),
    (45, 4),
    (30, 3),
    (15, 2),
    (5, 1),
]


# ─── Inspection frequency policy (PRD §2.11) ───────────────────────────────
INTERVAL_POOR_CONDITION_MONTHS = 12   # min_nbi_rating 4 or lower
INTERVAL_EXTENDED_MONTHS = 48         # min_nbi >= 7 AND year_built >= 1990 AND adt <= 5000
INTERVAL_STANDARD_MONTHS = 24
INTERVAL_FLOOR_FRACTURE_CRITICAL = 12
INTERVAL_FLOOR_SCOUR_CRITICAL = 12
INTERVAL_FLOOR_RESTRICTED_OR_CLOSED = 6

EXTENSION_MIN_NBI = 7
EXTENSION_MIN_YEAR_BUILT = 1990
EXTENSION_MAX_ADT = 5000

UNDERWATER_INTERVAL_BASE_MONTHS = 60
UNDERWATER_INTERVAL_SCOUR_CRITICAL_MONTHS = 24

# "each defaulting to 7 when omitted" (PRD §3.1)
DEFAULT_INITIAL_RATING = 7


# ─── Load rating (PRD §3.4) ────────────────────────────────────────────────
DEFAULT_IMPACT_IM_FACTOR = 1.33
DEFAULT_SYSTEM_FACTOR_PHI_S = 1.00
DEFAULT_RESISTANCE_FACTOR_PHI = 0.90

GAMMA_DC = 1.25          # "minus 1.25 times the structural dead-load moment"
GAMMA_DW = 1.50          # "minus 1.50 times the wearing-surface dead-load moment"
GAMMA_LL_OPERATING = 1.35
GAMMA_LL_INVENTORY = 1.75

# "the rating vehicle's gross weight of 36.0 tons"
RATING_VEHICLE_TONS = 36.0

# "A worst of good or fair yields a factor of 1.00, a worst of poor yields
#  0.95, and a worst of severe yields 0.85."
PHI_C_GOOD_OR_FAIR = 1.00
PHI_C_POOR = 0.95
PHI_C_SEVERE = 0.85

# "`posting_required` is true exactly when `rating_factor_operating` is
#  strictly less than 1.000"
POSTING_THRESHOLD = 1.000


# ─── Scour (PRD §3.6) ──────────────────────────────────────────────────────
SCOUR_CRITICAL_MAX_CODE = 3      # "a code of 3 or below is `SCOUR_CRITICAL`"
SCOUR_LOW_RISK_MAX_CODE = 6      # "a code from 4 through 6 is `LOW_RISK`"
# "a code of 7 or above is `STABILIZED`"


# ─── Permit analysis (PRD §3.7) ────────────────────────────────────────────
PERMIT_CRAWL_IMPACT_FACTOR = 1.00
PERMIT_BAND_ADEQUATE = 1.000     # ">= 1.000 gives ALLOWED / RF_ADEQUATE"
PERMIT_BAND_MARGINAL = 0.900     # ">= 0.900 but below 1.000 gives ALLOWED_WITH_CONDITIONS"


# ─── Programming (PRD §3.8) ────────────────────────────────────────────────
DEFAULT_RESERVE_PCT = 0.05
MOBILIZATION_FACTOR = 1.15

# "The unit costs in cents are 18000 for `DECK`, 95000 for `GIRDER`, 260000 for
#  `BEARING`, 140000 for `PIER_CAP`, 210000 for `COLUMN`, 175000 for
#  `ABUTMENT`, 55000 for `JOINT` and 40000 for `RAILING`."
UNIT_REPAIR_COST_CENTS = {
    "DECK": 18000,
    "GIRDER": 95000,
    "BEARING": 260000,
    "PIER_CAP": 140000,
    "COLUMN": 210000,
    "ABUTMENT": 175000,
    "JOINT": 55000,
    "RAILING": 40000,
}

# "a rating of 3 or below yields `REPLACEMENT`, exactly 4 yields
#  `REHABILITATION`, exactly 5 yields `REPAIR`, and 6 or above yields
#  `PRESERVATION`."
WORK_TYPE_REPLACEMENT_MAX_NBI = 3
WORK_TYPE_REHABILITATION_NBI = 4
WORK_TYPE_REPAIR_NBI = 5

CONDITION_BASED_WEIGHT_CONDITION_GAP = 0.50
CONDITION_BASED_WEIGHT_RATING_GAP = 0.30
CONDITION_BASED_WEIGHT_DEFICIENCY = 0.20

RISK_BASED_WEIGHT_CONDITION_GAP = 0.35
RISK_BASED_WEIGHT_SCOUR = 0.25
RISK_BASED_WEIGHT_EXPOSURE = 0.25
RISK_BASED_WEIGHT_POSTING = 0.15

# "100 for `SCOUR_CRITICAL`, 70 for `NOT_EVALUATED`, 40 for `LOW_RISK` and 20
#  for `STABILIZED`"
SCOUR_POINTS = {
    "SCOUR_CRITICAL": 100,
    "NOT_EVALUATED": 70,
    "LOW_RISK": 40,
    "STABILIZED": 20,
}

# "100 for `CLOSED`, 80 for `RESTRICTED`, 60 for `POSTED` and 0 for `OPEN`"
POSTING_POINTS = {"CLOSED": 100, "RESTRICTED": 80, "POSTED": 60, "OPEN": 0}

EXPOSURE_ADT_DIVISOR = 250
EXPOSURE_CAP = 100.00

# "the `rating_gap` is the difference between 9 and the structure's
#  `min_nbi_rating`, multiplied by 100 divided by 9"
RATING_GAP_MAX_NBI = 9


# ─── Federal reporting (PRD §3.9) ──────────────────────────────────────────
COMPLIANCE_ACCEPT_THRESHOLD_PCT = 90.00


# ─── Temporal windows (PRD §3.2, §3.5) ─────────────────────────────────────
BRIDGE_ACCESS_BUFFER_HOURS = 72
TEAM_LEADER_CAPACITY = 1
NOTIFICATION_WINDOW_HOURS = 24


# ─── Pagination (PRD §2.3) ─────────────────────────────────────────────────
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
MIN_OFFSET = 0
