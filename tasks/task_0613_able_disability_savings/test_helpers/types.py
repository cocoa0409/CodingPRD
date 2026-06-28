"""Domain types: entity TypedDicts, status enums, role enum for the ABLE program API."""
from enum import Enum
from typing import TypedDict, Optional


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PROGRAM_ADMINISTRATOR = "ProgramAdministrator"
    BENEFICIARY = "Beneficiary"
    AUTHORIZED_REPRESENTATIVE = "AuthorizedRepresentative"
    MEDICAID_AGENCY = "MedicaidAgency"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------
class EligibilityStatus(str, Enum):
    UNCERTIFIED = "UNCERTIFIED"
    CERTIFIED = "CERTIFIED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"


class CertificationStatus(str, Enum):
    PENDING = "PENDING"
    CERTIFIED = "CERTIFIED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"


class AccountStatus(str, Enum):
    OPEN = "OPEN"
    SUSPENDED = "SUSPENDED"
    FROZEN_DEATH = "FROZEN_DEATH"
    CLOSED = "CLOSED"


class SsiPosture(str, Enum):
    SSI_OK = "SSI_OK"
    SSI_SUSPENDED = "SSI_SUSPENDED"


class RepresentativeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class RepresentativeRelationship(str, Enum):
    PARENT = "PARENT"
    GUARDIAN = "GUARDIAN"
    POA_AGENT = "POA_AGENT"
    SPOUSE = "SPOUSE"


class ContributionType(str, Enum):
    REGULAR = "REGULAR"
    ABLE_TO_WORK = "ABLE_TO_WORK"
    ROLLOVER_529 = "ROLLOVER_529"


class ContributionStatus(str, Enum):
    POSTED = "POSTED"
    REVERSED = "REVERSED"


class DistributionStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DISBURSED = "DISBURSED"
    REJECTED = "REJECTED"
    SUBSTANTIATED = "SUBSTANTIATED"
    CLAWED_BACK = "CLAWED_BACK"


class ExpenseCategory(str, Enum):
    HOUSING = "HOUSING"
    EDUCATION = "EDUCATION"
    HEALTH = "HEALTH"
    TRANSPORTATION = "TRANSPORTATION"
    BASIC_LIVING = "BASIC_LIVING"
    LEGAL = "LEGAL"
    OTHER = "OTHER"


class RiskTier(str, Enum):
    CONSERVATIVE = "CONSERVATIVE"
    MODERATE = "MODERATE"
    AGGRESSIVE = "AGGRESSIVE"
    CASH = "CASH"


class CertificationBasis(str, Enum):
    SSI_SSDI_ENTITLEMENT = "SSI_SSDI_ENTITLEMENT"
    DISABILITY_DIAGNOSIS = "DISABILITY_DIAGNOSIS"


class MedicaidClaimStatus(str, Enum):
    FILED = "FILED"
    SETTLED = "SETTLED"


class MeansTestVariant(str, Enum):
    SSI = "SSI"
    MEDICAID = "MEDICAID"


# ---------------------------------------------------------------------------
# Entity TypedDicts — every entity carries id, created_at, updated_at, version.
# ---------------------------------------------------------------------------
class Program(TypedDict):
    id: str
    name: str
    state_code: str
    annual_contribution_cap_cents: int
    able_to_work_fpl_cents: int
    ssi_suspension_threshold_cents: int
    ssi_resource_limit_cents: int
    program_fee_bps: int
    nonqualified_additional_tax_pct: float
    max_investment_changes_per_year: int
    disability_onset_max_age: int
    created_at: str
    updated_at: str
    version: int


class InvestmentOption(TypedDict):
    id: str
    program_id: str
    name: str
    risk_tier: str
    is_open: bool
    created_at: str
    updated_at: str
    version: int


class Beneficiary(TypedDict):
    id: str
    program_id: str
    full_name: str
    birth_date: str
    disability_onset_date: str
    state_code: str
    other_countable_resources_cents: int
    receives_ssi: bool
    receives_medicaid: bool
    employer_retirement_plan_participant: bool
    gross_employment_income_ytd_cents: int
    is_deceased: bool
    eligibility_status: str
    created_at: str
    updated_at: str
    version: int


class Certification(TypedDict):
    id: str
    beneficiary_id: str
    basis: str
    diagnosis_code: Optional[str]
    effective_date: str
    expires_on: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Account(TypedDict):
    id: str
    beneficiary_id: str
    investment_option_id: str
    status: str
    balance_cents: int
    basis_cents: int
    earnings_cents: int
    regular_contrib_ytd_cents: int
    atw_contrib_ytd_cents: int
    investment_changes_ytd: int
    ssi_posture: str
    medicaid_paid_since_open_cents: int
    premiums_paid_by_beneficiary_cents: int
    created_at: str
    updated_at: str
    version: int


class AuthorizedRepresentative(TypedDict):
    id: str
    account_id: str
    full_name: str
    relationship: str
    authority_start: str
    authority_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Contribution(TypedDict):
    id: str
    account_id: str
    contribution_type: str
    amount_cents: int
    source_529_plan: Optional[str]
    contribution_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Distribution(TypedDict):
    id: str
    account_id: str
    amount_cents: int
    category: str
    status: str
    earnings_portion_cents: int
    qualified_amount_cents: int
    nonqualified_amount_cents: int
    additional_tax_cents: int
    counts_against_ssi_housing: bool
    created_at: str
    updated_at: str
    version: int


class QDERecord(TypedDict):
    id: str
    distribution_id: str
    expense_category: str
    amount_cents: int
    receipt_reference: str
    expense_date: str
    created_at: str
    updated_at: str
    version: int


class MedicaidClaim(TypedDict):
    id: str
    account_id: str
    claimed_amount_cents: int
    allowed_payback_cents: int
    residual_to_estate_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
