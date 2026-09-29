"""Domain constants for the Long-Term Disaster Recovery Group API.

Every literal here traces to PRD.md (sections 2 and 3) / SCAFFOLD.yaml section 1.3.
"""

# ---------------------------------------------------------------------------
# Roles (PRD 2.1)
# ---------------------------------------------------------------------------
ROLE_INTAKE = "IntakeSpecialist"
ROLE_CASE_MANAGER = "CaseManager"
ROLE_CHAIR = "UnmetNeedsChair"
ROLE_DELEGATE = "MemberOrgDelegate"
ROLE_OFFICER = "DisbursementOfficer"
ROLE_CONSTRUCTION = "ConstructionManager"
ROLE_VOLUNTEER = "VolunteerCoordinator"
ROLE_ADMIN = "LTRGAdmin"

ALL_ROLES = (
    ROLE_INTAKE,
    ROLE_CASE_MANAGER,
    ROLE_CHAIR,
    ROLE_DELEGATE,
    ROLE_OFFICER,
    ROLE_CONSTRUCTION,
    ROLE_VOLUNTEER,
    ROLE_ADMIN,
)

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------
INCOME_BANDS = ("ELI", "VLI", "LOW", "MODERATE", "ABOVE")

RESIDENCE_STATUSES = ("OWNER_OCCUPIED", "RENTER", "MOBILE_HOME", "OTHER")

CASE_STATUSES = (
    "INTAKE",
    "ASSESSED",
    "PRESENTED",
    "ACTIVE_RECOVERY",
    "CLOSURE_PENDING",
    "CLOSED",
    "INACTIVE",
)

FUNDING_STATUSES = (
    "UNFUNDED",
    "PARTIALLY_COMMITTED",
    "FULLY_COMMITTED",
    "DISBURSING",
    "SATISFIED",
)

DAMAGE_CATEGORIES = (
    "STRUCTURE",
    "ROOF",
    "HVAC",
    "PLUMBING",
    "ELECTRICAL",
    "CONTENTS",
    "ACCESSIBILITY",
)

VERIFICATION_STATUSES = ("UNVERIFIED", "VERIFIED", "REJECTED")
VERIFICATION_OUTCOMES = ("VERIFIED", "REJECTED")

ASSISTANCE_SOURCE_TYPES = (
    "INSURANCE_SETTLEMENT",
    "FEMA_IA",
    "SBA_LOAN",
    "NONPROFIT_GRANT",
    "STATE_PROGRAM",
    "CROWDFUNDING",
    "OTHER",
)

DOCUMENTATION_STATUSES = ("UNDOCUMENTED", "DOCUMENTED", "DISPUTED")

PURPOSE_CODES = (
    "STRUCTURE_REPAIR",
    "CONTENTS_REPLACEMENT",
    "ACCESSIBILITY_MOD",
    "TEMPORARY_HOUSING",
)

ASSESSMENT_VARIANTS = ("PURPOSE_MATCHED", "POOLED")

ORG_TYPES = ("FAITH_BASED", "NONPROFIT", "GOVERNMENT", "CIVIC_CLUB", "FOUNDATION")
ORG_STATUSES = ("ACTIVE", "CAPPED", "SUSPENDED", "WITHDRAWN")
ORG_SETTABLE_STATUSES = ("ACTIVE", "SUSPENDED", "WITHDRAWN")

SESSION_STATUSES = ("SCHEDULED", "IN_SESSION", "ADJOURNED", "CANCELLED")

PRESENTATION_STATUSES = (
    "QUEUED",
    "PRESENTING",
    "DELIBERATING",
    "AWARDED",
    "DEFERRED",
    "DENIED",
)

DECISIONS = ("AWARD", "DEFER", "DENY")

COMMITMENT_STATUSES = ("PLEDGED", "CONFIRMED", "DISBURSED", "RESCINDED")

FUNDING_SOURCE_TYPES = (
    "INDIVIDUAL_DONATION",
    "FOUNDATION_GRANT",
    "GOVERNMENT_GRANT",
    "IN_KIND_MATERIAL",
    "MEMBER_ORG_TRANSFER",
)

RESTRICTION_CODES = (
    "UNRESTRICTED",
    "STRUCTURE_REPAIR_ONLY",
    "CONTENTS_ONLY",
    "ACCESSIBILITY_ONLY",
    "TEMPORARY_HOUSING_ONLY",
    "MATERIALS_ONLY",
)

FUNDING_SOURCE_STATUSES = ("OPEN", "EXHAUSTED", "EXPIRED")

DISBURSEMENT_STATUSES = (
    "REQUESTED",
    "DOB_CLEARED",
    "DOB_FLAGGED",
    "APPROVED",
    "PAID",
    "REVERSED",
    "VOIDED",
)

SCOPE_CODES = (
    "ROOF_REPLACEMENT",
    "STRUCTURE_REBUILD",
    "INTERIOR_REPAIR",
    "ACCESSIBILITY_RAMP",
    "MECHANICAL_REPAIR",
)

PROJECT_STATUSES = (
    "SCOPED",
    "PERMITTED",
    "IN_PROGRESS",
    "SUSPENDED",
    "PUNCHLIST",
    "CLOSED_OUT",
    "CANCELLED",
)

PROJECT_ACTIONS = (
    "PERMIT",
    "START",
    "SUSPEND",
    "RESUME",
    "PUNCHLIST",
    "CLOSE_OUT",
    "CANCEL",
)

TRADE_CODES = (
    "FRAMING",
    "ROOFING",
    "DRYWALL",
    "ELECTRICAL",
    "PLUMBING",
    "PAINTING",
    "GENERAL_LABOR",
)

DEPLOYMENT_STATUSES = ("REQUESTED", "CONFIRMED", "CANCELLED", "COMPLETED")
DEPLOYMENT_ACTIONS = ("CONFIRM", "CANCEL", "COMPLETE")

HOUSING_STATUSES = ("ACTIVE", "RELEASED")

CONTACT_TYPES = (
    "CHECK_IN_30_DAY",
    "CHECK_IN_90_DAY",
    "CLOSURE_REVIEW",
    "ANNIVERSARY",
    "REFERRAL",
)

CONTACT_OUTCOMES = ("REACHED", "NO_ANSWER", "DECLINED", "NEEDS_REOPENED")

SKILL_FIT_VARIANTS = ("COVERAGE_WEIGHTED", "HEADCOUNT_WEIGHTED")

# ---------------------------------------------------------------------------
# calculations.survivor_priority_score (PRD 3.1)
# ---------------------------------------------------------------------------
INCOME_POINTS = {"ELI": 40, "VLI": 30, "LOW": 20, "MODERATE": 10, "ABOVE": 0}
HOUSEHOLD_POINT_PER_EXTRA_MEMBER = 4
HOUSEHOLD_POINT_CAP = 20
DISABILITY_POINTS = 15
ELDER_POINTS = 10
ELDER_AGE_THRESHOLD = 65
UNINSURED_POINTS = 15
SCORE_CEILING = 100

# ---------------------------------------------------------------------------
# calculations.verified_damage_total (PRD 3.2)
# ---------------------------------------------------------------------------
CATEGORY_CAP_CENTS = {
    "STRUCTURE": 12000000,
    "ROOF": 3500000,
    "HVAC": 1200000,
    "PLUMBING": 900000,
    "ELECTRICAL": 900000,
    "CONTENTS": 1500000,
    "ACCESSIBILITY": 2500000,
}

# ---------------------------------------------------------------------------
# calculations.unmet_need_determination (PRD 3.3)
# ---------------------------------------------------------------------------
BUCKET_ORDER = (
    "STRUCTURE_REPAIR",
    "CONTENTS_REPLACEMENT",
    "ACCESSIBILITY_MOD",
    "TEMPORARY_HOUSING",
)

BUCKET_OF_CATEGORY = {
    "STRUCTURE": "STRUCTURE_REPAIR",
    "ROOF": "STRUCTURE_REPAIR",
    "HVAC": "STRUCTURE_REPAIR",
    "PLUMBING": "STRUCTURE_REPAIR",
    "ELECTRICAL": "STRUCTURE_REPAIR",
    "CONTENTS": "CONTENTS_REPLACEMENT",
    "ACCESSIBILITY": "ACCESSIBILITY_MOD",
}

DAMAGE_BUCKETS = ("STRUCTURE_REPAIR", "CONTENTS_REPLACEMENT", "ACCESSIBILITY_MOD")

# ---------------------------------------------------------------------------
# calculations.dob_exposure_check (PRD 3.6)
# ---------------------------------------------------------------------------
DOB_FLAG_THRESHOLD_CENTS = 0
DOB_COUNTED_DOCUMENTATION_STATUSES = ("DOCUMENTED", "DISPUTED")

# ---------------------------------------------------------------------------
# calculations.restricted_fund_waterfall (PRD 2.8 / 3.6)
# ---------------------------------------------------------------------------
ADMIN_RETENTION_BPS = 350

ELIGIBLE_PURPOSES_BY_RESTRICTION = {
    "UNRESTRICTED": [
        "STRUCTURE_REPAIR",
        "CONTENTS_REPLACEMENT",
        "ACCESSIBILITY_MOD",
        "TEMPORARY_HOUSING",
    ],
    "STRUCTURE_REPAIR_ONLY": ["STRUCTURE_REPAIR"],
    "CONTENTS_ONLY": ["CONTENTS_REPLACEMENT"],
    "ACCESSIBILITY_ONLY": ["ACCESSIBILITY_MOD"],
    "TEMPORARY_HOUSING_ONLY": ["TEMPORARY_HOUSING"],
    "MATERIALS_ONLY": ["STRUCTURE_REPAIR"],
}

RESTRICTION_SPECIFICITY = {
    "UNRESTRICTED": 0,
    "STRUCTURE_REPAIR_ONLY": 1,
    "CONTENTS_ONLY": 1,
    "ACCESSIBILITY_ONLY": 1,
    "TEMPORARY_HOUSING_ONLY": 1,
    "MATERIALS_ONLY": 1,
}

# ---------------------------------------------------------------------------
# calculations.table_award_assembly (PRD 3.5)
# ---------------------------------------------------------------------------
TIER_A_CEILING_CENTS = 500000
TIER_B_CEILING_CENTS = 2500000
BRIDGE_PCT_BPS = {"TIER_A": 5000, "TIER_B": 3000, "TIER_C": 1500}
MAX_DEFERRALS = 3

# ---------------------------------------------------------------------------
# calculations.volunteer_skill_fit_score (PRD 3.8)
# ---------------------------------------------------------------------------
VOLUNTEER_HOURS_PER_DAY = 6
CRITICAL_TRADE_WEIGHT = 3
NORMAL_TRADE_WEIGHT = 1
MIN_FIT_BPS = 6000
DEPLOYMENT_TURNAROUND_DAYS = 1

# ---------------------------------------------------------------------------
# Pagination (PRD 2.3)
# ---------------------------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# Logical clock default (PRD 2.4)
CLOCK_DEFAULT = "2026-08-01T00:00:00Z"
