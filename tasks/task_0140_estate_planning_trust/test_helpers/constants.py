"""Domain thresholds and constants — anchored to PRD verbatim sentences.

Each constant traces back to a sentence in PRD.md.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Bond tier constants — PRD §3.5
# ---------------------------------------------------------------------------
# PRD §3.5: "The first 10,000,000 cents of gross — i.e., the first
# $100,000 — is bonded at the rate of one hundred basis points; the next
# 90,000,000 cents — i.e., the band from $100,000 up to and including
# $1,000,000 — is bonded at fifty basis points; every cent of gross
# strictly above 100,000,000 cents — i.e., above $1,000,000 — is bonded
# at twenty-five basis points."
TIER1_LIMIT_CENTS: int = 10_000_000
TIER2_LIMIT_CENTS: int = 100_000_000
TIER1_RATE: float = 0.0100
TIER2_RATE: float = 0.0050
TIER3_RATE: float = 0.0025

# PRD §3.5: "finally a flat fee of 25,000 cents is added unrounded".
FLAT_BOND_FEE_CENTS: int = 25_000


# ---------------------------------------------------------------------------
# Designation share — PRD §3.6
# ---------------------------------------------------------------------------
# PRD §3.6: "a share_basis_points integer in the range 0 to 10000".
# PRD §3.6: "the sum of share_basis_points across all PROPOSED and
# LOCKED designations targeting the same asset_id, including the
# proposed new row, must not exceed 10000".
SHARE_BP_MIN: int = 0
SHARE_BP_FULL: int = 10_000


# ---------------------------------------------------------------------------
# Pagination — PRD §2.3
# ---------------------------------------------------------------------------
# PRD §2.3: "The default limit is 10, the minimum is 1, and the maximum
# is 100. The default offset is 0 and offset may not be negative."
PAGINATION_DEFAULT_LIMIT: int = 10
PAGINATION_MIN_LIMIT: int = 1
PAGINATION_MAX_LIMIT: int = 100
PAGINATION_MIN_OFFSET: int = 0


# ---------------------------------------------------------------------------
# Settlement window — PRD §3.3
# ---------------------------------------------------------------------------
# PRD §3.3: "settlement_due_at is set to eighteen months after
# petition_filed_at (the procedural deadline against which the eventual
# distribution must stay in advance)".
SETTLEMENT_WINDOW_MONTHS: int = 18

# PRD §3.14: "the count of days in the eighteen-month statutory window"
# — used as the denominator for time_factor.
SETTLEMENT_WINDOW_DAYS: int = 540


# ---------------------------------------------------------------------------
# Fiduciary risk score weights — PRD §3.14
# ---------------------------------------------------------------------------
# PRD §3.14: "the time factor with weight 1.0, the bond factor with
# weight 2.0, and the filing factor with weight 2.0".
TIME_FACTOR_WEIGHT: float = 1.0
BOND_FACTOR_WEIGHT: float = 2.0
FILING_FACTOR_WEIGHT: float = 2.0

# PRD §3.14: "clamped between a floor of 0.0000 and a ceiling of 5.0000".
SCORE_FLOOR: float = 0.0
SCORE_CEILING: float = 5.0


# ---------------------------------------------------------------------------
# Asset description / directive instructions length — PRD §3.1
# ---------------------------------------------------------------------------
# PRD §3.1: "a free-text description up to 500 characters".
ASSET_DESCRIPTION_MAX_LEN: int = 500

# PRD §3.1: "free-text instructions up to 4000 characters".
DIRECTIVE_INSTRUCTIONS_MAX_LEN: int = 4_000


# ---------------------------------------------------------------------------
# Enumeration sets (verbatim from PRD §3)
# ---------------------------------------------------------------------------
# PRD §3.1: "asset_class chosen from REAL_ESTATE, FINANCIAL,
# PERSONAL_PROPERTY, or DIGITAL".
ASSET_CLASSES = ["REAL_ESTATE", "FINANCIAL", "PERSONAL_PROPERTY", "DIGITAL"]

# PRD §3.1: "Beneficiaries carry a full_name, a relationship chosen
# from SPOUSE, CHILD, PARENT, SIBLING, CHARITY, or OTHER".
RELATIONSHIPS = ["SPOUSE", "CHILD", "PARENT", "SIBLING", "CHARITY", "OTHER"]

# PRD §3.1: "scope_type from EXECUTOR | TRUSTEE | GUARDIAN".
SCOPE_TYPES = ["EXECUTOR", "TRUSTEE", "GUARDIAN"]

# PRD §3.1: "poa_type from FINANCIAL_DURABLE, MEDICAL, or LIMITED".
POA_TYPES = ["FINANCIAL_DURABLE", "MEDICAL", "LIMITED"]

# PRD §3.13 / §3.1: "scope chosen from MEDICAL_RECORDS, MENTAL_HEALTH,
# SUBSTANCE_ABUSE, or ALL".
HIPAA_SCOPES = ["MEDICAL_RECORDS", "MENTAL_HEALTH", "SUBSTANCE_ABUSE", "ALL"]

# PRD §3.1: "directive_type from LIVING_WILL, DNR, DNI, or POLST".
DIRECTIVE_TYPES = ["LIVING_WILL", "DNR", "DNI", "POLST"]

# PRD §3.7: "filing_type enumeration is PETITION_TO_PROBATE,
# INVENTORY_REPORT, INTERIM_ACCOUNTING, FINAL_ACCOUNTING, and
# DISTRIBUTION_PETITION".
FILING_TYPES = [
    "PETITION_TO_PROBATE",
    "INVENTORY_REPORT",
    "INTERIM_ACCOUNTING",
    "FINAL_ACCOUNTING",
    "DISTRIBUTION_PETITION",
]

# Roles — PRD §2.1.
USER_ROLES = ["Executor", "Beneficiary", "CourtClerk", "Fiduciary"]

# PRD §3.1: admin_phase values.
ESTATE_ADMIN_PHASES = [
    "DRAFT", "IN_PROBATE", "INVENTORIED", "DISTRIBUTING",
    "SETTLED", "CONTESTED",
]

# PRD §2.8: probate_posture values.
PROBATE_POSTURES = ["OPEN", "UNDER_COURT_REVIEW", "FROZEN"]

# Asset statuses — PRD §3.1, §3.4.
ASSET_STATUSES = [
    "DECLARED", "INVENTORIED", "APPRAISED", "DISTRIBUTED", "EXCLUDED",
]

# Beneficiary statuses — PRD §3.1, §3.9.
BENEFICIARY_STATUSES = ["ACTIVE", "DISCLAIMED", "REMOVED"]

# Designation statuses — PRD §3.6.
DESIGNATION_STATUSES = ["PROPOSED", "LOCKED", "VOIDED"]

# Fiduciary statuses — PRD §3.1.
FIDUCIARY_STATUSES = ["NOMINATED", "CONFIRMED", "RESIGNED", "REMOVED"]

# Guardianship statuses — PRD §3.1.
GUARDIANSHIP_STATUSES = ["DRAFT", "EFFECTIVE", "SUPERSEDED", "REVOKED"]

# HIPAA statuses — PRD §3.1, §3.13.
HIPAA_STATUSES = ["ACTIVE", "EXPIRED", "REVOKED"]

# POA statuses — PRD §3.1, §3.2.
POA_STATUSES = ["PENDING", "ACTIVE", "REVOKED", "TERMINATED"]

# Directive statuses — PRD §3.1, §3.13.
DIRECTIVE_STATUSES = ["DRAFT", "EXECUTED", "SUPERSEDED", "REVOKED"]

# Filing statuses — PRD §3.7.
FILING_STATUSES = ["SUBMITTED", "ACCEPTED", "REJECTED", "REVISION_REQUESTED"]

# Distribution statuses — PRD §3.11.
DISTRIBUTION_STATUSES = ["PLANNED", "EXECUTED", "REVERSED"]


# ---------------------------------------------------------------------------
# Test defaults — PRD-anchored values reused across fixtures.
# ---------------------------------------------------------------------------
TEST_DEFAULTS = {
    "TESTATOR_NAME": "John Doe",
    "DOMICILE_STATE": "NY",
    "FILING_COURT_ID": "COURT-NY-001",
    "BENEFICIARY_NAME": "Jane Doe",
    "FIDUCIARY_NAME": "Trustee Tom",
    "ASSET_DESCRIPTION": "Family home",
    "HIPAA_RECIPIENT": "Memorial Hospital",
    "DIRECTIVE_INSTRUCTIONS": "Do not resuscitate; comfort care only.",
    "REJECTION_REASON": "Missing schedule of assets.",
}


__all__ = [
    "TIER1_LIMIT_CENTS",
    "TIER2_LIMIT_CENTS",
    "TIER1_RATE",
    "TIER2_RATE",
    "TIER3_RATE",
    "FLAT_BOND_FEE_CENTS",
    "SHARE_BP_MIN",
    "SHARE_BP_FULL",
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_MIN_OFFSET",
    "SETTLEMENT_WINDOW_MONTHS",
    "SETTLEMENT_WINDOW_DAYS",
    "TIME_FACTOR_WEIGHT",
    "BOND_FACTOR_WEIGHT",
    "FILING_FACTOR_WEIGHT",
    "SCORE_FLOOR",
    "SCORE_CEILING",
    "ASSET_DESCRIPTION_MAX_LEN",
    "DIRECTIVE_INSTRUCTIONS_MAX_LEN",
    "ASSET_CLASSES",
    "RELATIONSHIPS",
    "SCOPE_TYPES",
    "POA_TYPES",
    "HIPAA_SCOPES",
    "DIRECTIVE_TYPES",
    "FILING_TYPES",
    "USER_ROLES",
    "ESTATE_ADMIN_PHASES",
    "PROBATE_POSTURES",
    "ASSET_STATUSES",
    "BENEFICIARY_STATUSES",
    "DESIGNATION_STATUSES",
    "FIDUCIARY_STATUSES",
    "GUARDIANSHIP_STATUSES",
    "HIPAA_STATUSES",
    "POA_STATUSES",
    "DIRECTIVE_STATUSES",
    "FILING_STATUSES",
    "DISTRIBUTION_STATUSES",
    "TEST_DEFAULTS",
]
