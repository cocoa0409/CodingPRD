"""Domain constants, canonical payload values and pre-computed expectations.

Every literal here is taken from the product requirements document under test so
that the test suite never re-derives a rule it is supposed to be checking.
"""

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
ROLE_PROGRAM_ADMIN = "ProgramAdmin"
ROLE_FIELD_INSPECTOR = "FieldInspector"
ROLE_DETERMINATION_REVIEWER = "DeterminationReviewer"
ROLE_PROCUREMENT_OFFICER = "ProcurementOfficer"
ROLE_AWARD_AUTHORITY = "AwardAuthority"
ROLE_FUNDING_OFFICER = "FundingOfficer"
ROLE_CONTRACTOR = "Contractor"
ROLE_OPERATOR = "Operator"

ALL_ROLES = [
    ROLE_PROGRAM_ADMIN,
    ROLE_FIELD_INSPECTOR,
    ROLE_DETERMINATION_REVIEWER,
    ROLE_PROCUREMENT_OFFICER,
    ROLE_AWARD_AUTHORITY,
    ROLE_FUNDING_OFFICER,
    ROLE_CONTRACTOR,
    ROLE_OPERATOR,
]

# ---------------------------------------------------------------------------
# Opaque actor identifiers
# ---------------------------------------------------------------------------
U_ADMIN = "u_admin"
U_INSPECTOR = "u_insp"
U_REVIEWER = "u_rev"
U_REVIEWER_2 = "u_rev2"
U_PROCUREMENT = "u_proc"
U_PROCUREMENT_2 = "u_proc2"
U_PROCUREMENT_3 = "u_proc3"
U_AWARD = "u_award"
U_FUNDING_1 = "u_fund1"
U_FUNDING_2 = "u_fund2"

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------
OPERATOR_STATUSES = ["ACTIVE", "DELINQUENT", "INSOLVENT", "REVOKED"]
ASSURANCE_TIERS = ["INDIVIDUAL", "BLANKET"]

WELL_STATUSES = [
    "PRODUCING",
    "INACTIVE",
    "ORPHAN_CANDIDATE",
    "ORPHAN_CONFIRMED",
    "PLUGGING_SCHEDULED",
    "PLUGGED",
    "RECLAIMED",
]
WELL_ACCESS_STATUSES = [
    "NO_ACCESS_REQUESTED",
    "ACCESS_PENDING",
    "AGREEMENT_EXECUTED",
    "ENTRY_ORDERED",
    "ACCESS_DENIED",
]

DETERMINATION_STATUSES = [
    "DRAFT",
    "SUBMITTED",
    "REVISION_REQUESTED",
    "CONFIRMED",
    "REJECTED",
    "SUPERSEDED",
]
SITE_ACCESS_MODES = ["AGREEMENT", "STATUTORY_ENTRY"]
SITE_ACCESS_STATUSES = ["REQUESTED", "AGREEMENT_EXECUTED", "ENTRY_ORDERED", "DENIED"]
TRANSFER_STATUSES = ["PENDING", "APPROVED", "DENIED", "VOIDED"]
VOID_REASONS = ["MANUAL_VOID", "TRANSFEREE_INSOLVENT"]
LICENSE_STATUSES = ["GOOD_STANDING", "SUSPENDED", "DEBARRED"]
SOLICITATION_STATUSES = ["DRAFT", "OPEN", "EVALUATING", "AWARDED", "CANCELLED"]
BID_STATUSES = ["SUBMITTED", "RESPONSIVE", "NONRESPONSIVE", "AWARDED", "NOT_AWARDED"]
CONTRACT_STATUSES = ["ACTIVE", "SUSPENDED", "CLOSED"]
JOB_STATUSES = [
    "SCHEDULED",
    "MOBILIZED",
    "FIELD_REPORTED",
    "REWORK_REQUIRED",
    "PLUGGED",
    "RECLAIMED",
]
TASK_TYPES = ["EQUIPMENT_REMOVAL", "PIT_CLOSURE", "REVEGETATION"]
TASK_STATUSES = ["PENDING", "IN_PROGRESS", "COMPLETE", "REWORK_NEEDED"]
FUNDING_KINDS = ["FORFEITED_BOND", "FEDERAL_GRANT", "STATE_FUND"]
FUNDING_SOURCE_STATUSES = ["ACTIVE", "EXHAUSTED", "EXPIRED"]
COST_CATEGORIES = ["PLUGGING", "RECLAMATION", "ADMIN"]
ALLOCATION_STATUSES = ["COMMITTED", "DISBURSED", "DEOBLIGATED"]
GRANT_REPORT_STATUSES = ["DUE", "SUBMITTED", "ACCEPTED", "REJECTED"]

# ---------------------------------------------------------------------------
# Rule constants
# ---------------------------------------------------------------------------
ORPHAN_SCORE_ELIGIBILITY_MIN = 40.00
IDLE_THRESHOLD_MONTHS = 24
WELL_INACTIVE_IDLE_MONTHS = 12
DE_MINIMIS_WINDOW_MONTHS = 60
DE_MINIMIS_BOE = 180.00
GAS_TO_BOE_DIVISOR = 6
NO_PRODUCTION_IDLE_MONTHS = 999

SACKS_BASIS = 120
RIG_DAYS_BASIS = 4
CASING_FT_BASIS = 800

ADMIN_FEE_PCT = 0.0425
REMOB_PCT = 0.50
CREW_DEMOB_BUFFER_DAYS = 2

MAX_REVISION_ROUNDS = 2
MAX_REWORK_ROUNDS = 2
MAX_REOPEN_ROUNDS = 1

TRANSFER_VOID_LOOKBACK_DAYS = 180
FORFEITED_BOND_TERM_DAYS = 3650
REVEGETATION_MIN_WAIT_DAYS = 90

DEFAULT_WAITING_PERIOD_STATUTORY = 30
DEFAULT_WAITING_PERIOD_AGREEMENT = 0

FORFEITED_BOND_NAME_PREFIX = "FORFEITED BOND "

# Depth tiers for the per-well financial assurance base
ASSURANCE_BASE_SHALLOW = 250000       # total_depth_ft <= 3000
ASSURANCE_BASE_MEDIUM = 750000        # total_depth_ft <= 7000
ASSURANCE_BASE_DEEP = 1500000         # deeper than 7000
BLANKET_AGGREGATE_CAP = 25000000
INDIVIDUAL_PER_WELL_CAP = 1000000

# ---------------------------------------------------------------------------
# Canonical well inputs and their pre-computed scores
# ---------------------------------------------------------------------------
CANONICAL_WELL_INPUTS = {
    "spud_year": 1974,
    "total_depth_ft": 2500,
    "casing_strings": 2,
    "methane_scfd": 250,
    "groundwater_depth_ft": 40,
    "population_within_1000ft": 8,
    "surface_disturbance_acres": 2.0,
}
CANONICAL_SCREENING_SCORE = 59.90
CANONICAL_REMEDIATION_SCORE = 81.00

# ---------------------------------------------------------------------------
# Canonical procurement inputs and their pre-computed evaluated unit costs
# ---------------------------------------------------------------------------
CANONICAL_SOLICITATION = {
    "region_code": "WY",
    "scope_description": "single orphan well plugging",
    "bid_due_at": "2026-08-20T00:00:00Z",
    "ceiling_cents": 20000000,
    "min_technical_score": 70,
}

CANONICAL_BID_RATES = {
    "cement_per_sack_cents": 4137,
    "rig_day_rate_cents": 849999,
    "casing_per_ft_cents": 1213,
    "mobilization_fee_cents": 2499999,
}
CANONICAL_BID_UNIT_COST = 7366835

ROUND_BID_RATES = {
    "cement_per_sack_cents": 4000,
    "rig_day_rate_cents": 800000,
    "casing_per_ft_cents": 1200,
    "mobilization_fee_cents": 2400000,
}
ROUND_BID_UNIT_COST = 7040000

EXPENSIVE_BID_RATES = {
    "cement_per_sack_cents": 5000,
    "rig_day_rate_cents": 1000000,
    "casing_per_ft_cents": 1500,
    "mobilization_fee_cents": 3000000,
}
EXPENSIVE_BID_UNIT_COST = 8800000

# ---------------------------------------------------------------------------
# Canonical plugging job plan and its pre-computed estimate
# ---------------------------------------------------------------------------
CANONICAL_JOB_PLAN = {
    "planned_cement_sacks": 100,
    "planned_rig_days": 3,
    "planned_casing_ft": 500,
}
CANONICAL_JOB_ESTIMATE = 6070196

ZERO_UUID = "00000000-0000-0000-0000-000000000000"
