"""Constants drawn from the PRD: clock defaults, pagination bounds, rating
tables, the standard control catalog and the standard coverage tower.
"""

# --------------------------------------------------------------------------
# Logical clock (PRD §2.5). The clock starts at this instant on a cold start.
# --------------------------------------------------------------------------
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

# --------------------------------------------------------------------------
# Pagination (PRD §2.3)
# --------------------------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# --------------------------------------------------------------------------
# Premium rating (PRD §3.3)
# --------------------------------------------------------------------------
BASE_RATE_PER_MILLION = {
    "HEALTHCARE": 9000.0,
    "FINANCIAL": 8000.0,
    "RETAIL": 7000.0,
    "MANUFACTURING": 6000.0,
    "PUBLIC_SECTOR": 7500.0,
    "TECHNOLOGY": 5500.0,
}

REVENUE_TIER_BREAKPOINTS_USD = (50_000_000.0, 250_000_000.0)
REVENUE_TIER_MULTIPLIERS = (1.00, 1.15, 1.35)

LAYER_BREAKPOINTS_USD = (1_000_000.0, 5_000_000.0)
LAYER_UNIT_FACTORS = (1.00, 0.60, 0.35)

MINIMUM_PREMIUM_USD = 7500.00

# Control score modifier bands
CONTROL_MODIFIER_STRONG = -0.15      # score >= 90
CONTROL_MODIFIER_GOOD = -0.05        # 75 <= score < 90
CONTROL_MODIFIER_WEAK = 0.10         # 70 <= score < 75
CONTROL_MODIFIER_POOR = 0.30         # score < 70

# Retention credit bands
RETENTION_CREDIT_HIGH = -0.10        # retention >= 250000
RETENTION_CREDIT_MID = -0.05         # 100000 <= retention < 250000
RETENTION_CREDIT_NONE = 0.00

DEPENDENCY_LOAD = 0.08               # primary_dependency_key other than NONE

# --------------------------------------------------------------------------
# Control posture scoring (PRD §3.2)
# --------------------------------------------------------------------------
MATURITY_CREDIT = {"NONE": 0.0, "PARTIAL": 0.5, "FULL": 1.0}
MINIMUM_QUOTABLE_CONTROL_SCORE = 70.0

# --------------------------------------------------------------------------
# Limits and periods
# --------------------------------------------------------------------------
MIN_AGGREGATE_LIMIT_USD = 250_000.0
LIMIT_INCREMENT_USD = 250_000.0
QUOTE_VALIDITY_DAYS = 30
NOTIFICATION_WINDOW_DAYS = 30
RENEWAL_WINDOW_DAYS = 90
VENDOR_CHANGEOVER_BUFFER_HOURS = 24
MAX_PROOF_REVIEW_ROUNDS = 2
MAX_REMEDIATION_VERIFICATION_ROUNDS = 2

# --------------------------------------------------------------------------
# Renewal pricing (PRD §3.9)
# --------------------------------------------------------------------------
LOSS_RATIO_ADJUSTMENT_EXCELLENT = -0.05   # loss_ratio <= 0.30
LOSS_RATIO_ADJUSTMENT_GOOD = 0.05         # 0.30 < loss_ratio <= 0.60
LOSS_RATIO_ADJUSTMENT_POOR = 0.20         # 0.60 < loss_ratio <= 1.00
LOSS_RATIO_ADJUSTMENT_SEVERE = 0.45       # loss_ratio > 1.00
AGGREGATION_LOAD = 0.10
CONTROL_CREDIT_PER_KEY_USD = 750.00
CONTROL_CREDIT_CAP_PCT = 0.12

# --------------------------------------------------------------------------
# Extra expense cap (PRD §3.7)
# --------------------------------------------------------------------------
EXTRA_EXPENSE_CAP_PCT_OF_BI = 0.25

# --------------------------------------------------------------------------
# The standard five-row control catalog used across the suite. Weights sum
# to 100 so weighted percentages are easy to reason about.
# --------------------------------------------------------------------------
STANDARD_CATALOG = [
    {"control_key": "MFA_PRIVILEGED", "min_level_required": "FULL", "weight": 30, "is_mandatory": True},
    {"control_key": "OFFLINE_BACKUPS", "min_level_required": "FULL", "weight": 25, "is_mandatory": True},
    {"control_key": "EDR_COVERAGE", "min_level_required": "PARTIAL", "weight": 20, "is_mandatory": True},
    {"control_key": "EMAIL_FILTERING", "min_level_required": "PARTIAL", "weight": 15, "is_mandatory": False},
    {"control_key": "INCIDENT_RESPONSE_PLAN", "min_level_required": "PARTIAL", "weight": 10, "is_mandatory": False},
]

ALL_CONTROL_KEYS = [row["control_key"] for row in STANDARD_CATALOG]
MANDATORY_CONTROL_KEYS = [row["control_key"] for row in STANDARD_CATALOG if row["is_mandatory"]]

# Attestation set that yields attested_control_score 95.00
ATTEST_95 = {
    "MFA_PRIVILEGED": "FULL",
    "OFFLINE_BACKUPS": "FULL",
    "EDR_COVERAGE": "FULL",
    "EMAIL_FILTERING": "FULL",
    "INCIDENT_RESPONSE_PLAN": "PARTIAL",
}

# Attestation set that yields attested_control_score 87.50
ATTEST_87_50 = {
    "MFA_PRIVILEGED": "FULL",
    "OFFLINE_BACKUPS": "FULL",
    "EDR_COVERAGE": "FULL",
    "EMAIL_FILTERING": "PARTIAL",
    "INCIDENT_RESPONSE_PLAN": "PARTIAL",
}

# Attestation set that yields attested_control_score 70.00 (exactly quotable)
ATTEST_70 = {
    "MFA_PRIVILEGED": "FULL",
    "OFFLINE_BACKUPS": "FULL",
    "EDR_COVERAGE": "PARTIAL",
    "EMAIL_FILTERING": "NONE",
    "INCIDENT_RESPONSE_PLAN": "PARTIAL",
}

# Attestation set that yields attested_control_score 65.00 (below minimum)
ATTEST_65 = {
    "MFA_PRIVILEGED": "FULL",
    "OFFLINE_BACKUPS": "FULL",
    "EDR_COVERAGE": "PARTIAL",
    "EMAIL_FILTERING": "NONE",
    "INCIDENT_RESPONSE_PLAN": "NONE",
}

# --------------------------------------------------------------------------
# Standard insured accounts
# --------------------------------------------------------------------------
ACCOUNT_AURORA = {
    "legal_name": "Aurora Health",
    "industry_code": "HEALTHCARE",
    "annual_revenue_usd": 43800000,
    "record_count": 12345,
    "primary_dependency_key": "CSP_ALPHA",
}

ACCOUNT_REDSTONE = {
    "legal_name": "Redstone Capital",
    "industry_code": "FINANCIAL",
    "annual_revenue_usd": 300000000,
    "record_count": 5000,
    "primary_dependency_key": "NONE",
}

ACCOUNT_BITWISE = {
    "legal_name": "Bitwise Systems",
    "industry_code": "TECHNOLOGY",
    "annual_revenue_usd": 43800000,
    "record_count": 0,
    "primary_dependency_key": "NONE",
}

ACCOUNT_CORDIAL = {
    "legal_name": "Cordial Clinics",
    "industry_code": "HEALTHCARE",
    "annual_revenue_usd": 43800000,
    "record_count": 100,
    "primary_dependency_key": "CSP_ALPHA",
}

# --------------------------------------------------------------------------
# The standard five-section coverage tower for a 5,000,000 aggregate.
# --------------------------------------------------------------------------
STANDARD_TOWER = [
    {
        "section_key": "FIRST_PARTY_RESPONSE",
        "sublimit_usd": 1000000,
        "waiting_period_hours": None,
        "coinsurance_pct": 0.0,
        "erosion_priority": 10,
    },
    {
        "section_key": "BUSINESS_INTERRUPTION",
        "sublimit_usd": 2000000,
        "waiting_period_hours": 12,
        "coinsurance_pct": 0.1,
        "erosion_priority": 20,
    },
    {
        "section_key": "DEPENDENT_BI",
        "sublimit_usd": 500000,
        "waiting_period_hours": 24,
        "coinsurance_pct": 0.2,
        "erosion_priority": 30,
    },
    {
        "section_key": "THIRD_PARTY_LIABILITY",
        "sublimit_usd": 3000000,
        "waiting_period_hours": None,
        "coinsurance_pct": 0.0,
        "erosion_priority": 40,
    },
    {
        "section_key": "CYBER_EXTORTION",
        "sublimit_usd": 500000,
        "waiting_period_hours": None,
        "coinsurance_pct": 0.0,
        "erosion_priority": 50,
    },
]

# Two-section tower for a 250,000 aggregate with no coinsurance.
SMALL_TOWER = [
    {
        "section_key": "FIRST_PARTY_RESPONSE",
        "sublimit_usd": 250000,
        "waiting_period_hours": None,
        "coinsurance_pct": 0.0,
        "erosion_priority": 10,
    },
    {
        "section_key": "BUSINESS_INTERRUPTION",
        "sublimit_usd": 250000,
        "waiting_period_hours": 12,
        "coinsurance_pct": 0.0,
        "erosion_priority": 20,
    },
]

# --------------------------------------------------------------------------
# Standard panel vendors
# --------------------------------------------------------------------------
VENDOR_POSTMARK_NOTIFY = {
    "vendor_name": "Postmark Notify",
    "vendor_type": "NOTIFICATION",
    "pre_approved_hourly_rate_usd": 200,
    "per_record_notification_rate_usd": 3.5,
    "specialty_sectors": ["HEALTHCARE", "TECHNOLOGY"],
    "tier": 1,
    "capacity_concurrent_engagements": 5,
}

VENDOR_IRONGATE_FORENSICS = {
    "vendor_name": "Irongate Forensics",
    "vendor_type": "FORENSICS",
    "pre_approved_hourly_rate_usd": 500,
    "per_record_notification_rate_usd": 0,
    "specialty_sectors": ["HEALTHCARE", "TECHNOLOGY"],
    "tier": 1,
    "capacity_concurrent_engagements": 2,
}
