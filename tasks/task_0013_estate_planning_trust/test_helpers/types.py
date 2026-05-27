"""Domain types: entity TypedDicts, status enums, role enum.

All entities in this PRD carry the common fields (id, created_at, updated_at,
version) per the common-resource-properties section.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Status enums ─────────────────────────────────────────────────────────

class EstateStatus(str, Enum):
    DRAFT = "DRAFT"
    ALIVE = "ALIVE"
    DECEASED = "DECEASED"
    PROBATE_PENDING = "PROBATE_PENDING"
    PROBATE_OPEN = "PROBATE_OPEN"
    ADMINISTRATION = "ADMINISTRATION"
    CLOSED = "CLOSED"
    CONTESTED = "CONTESTED"


class AssetStatus(str, Enum):
    DRAFT = "DRAFT"
    INCLUDED = "INCLUDED"
    EXCLUDED = "EXCLUDED"
    LIQUIDATED = "LIQUIDATED"


class AssetCategory(str, Enum):
    REAL_ESTATE = "REAL_ESTATE"
    BROKERAGE = "BROKERAGE"
    BANK_ACCOUNT = "BANK_ACCOUNT"
    RETIREMENT_IRA = "RETIREMENT_IRA"
    LIFE_INSURANCE = "LIFE_INSURANCE"
    PERSONAL_PROPERTY = "PERSONAL_PROPERTY"
    BUSINESS_INTEREST = "BUSINESS_INTEREST"


class BeneficiaryDesignationStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class Relationship(str, Enum):
    SPOUSE = "SPOUSE"
    CHILD = "CHILD"
    GRANDCHILD = "GRANDCHILD"
    PARENT = "PARENT"
    SIBLING = "SIBLING"
    CHARITY = "CHARITY"
    OTHER = "OTHER"


class ExecutorStatus(str, Enum):
    NOMINATED = "NOMINATED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    COURT_CONFIRMED = "COURT_CONFIRMED"
    DISCHARGED = "DISCHARGED"
    REMOVED = "REMOVED"


class ExecutorRoleType(str, Enum):
    EXECUTOR = "EXECUTOR"
    TRUSTEE = "TRUSTEE"


class PowerOfAttorneyStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"
    TERMINATED = "TERMINATED"


class PowerOfAttorneyScope(str, Enum):
    FINANCIAL = "FINANCIAL"
    HEALTHCARE = "HEALTHCARE"
    DURABLE_FINANCIAL = "DURABLE_FINANCIAL"
    DURABLE_HEALTHCARE = "DURABLE_HEALTHCARE"


class DirectiveStatus(str, Enum):
    DRAFT = "DRAFT"
    WITNESSED = "WITNESSED"
    NOTARIZED = "NOTARIZED"
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class DirectiveType(str, Enum):
    LIVING_WILL = "LIVING_WILL"
    DNR = "DNR"
    HEALTHCARE_POA = "HEALTHCARE_POA"
    HIPAA_AUTHORIZATION = "HIPAA_AUTHORIZATION"


class GuardianshipStatus(str, Enum):
    PROPOSED = "PROPOSED"
    COURT_REVIEW = "COURT_REVIEW"
    COURT_CONFIRMED = "COURT_CONFIRMED"
    COURT_DENIED = "COURT_DENIED"
    DISSOLVED = "DISSOLVED"


class CreditorClaimStatus(str, Enum):
    FILED = "FILED"
    ALLOWED = "ALLOWED"
    DISALLOWED = "DISALLOWED"
    PAID = "PAID"


class ClaimClass(str, Enum):
    SECURED = "SECURED"
    ADMIN = "ADMIN"
    FUNERAL = "FUNERAL"
    TAX = "TAX"
    UNSECURED = "UNSECURED"


class ProbateOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    ENTERED = "ENTERED"
    SUPERSEDED = "SUPERSEDED"


class OrderType(str, Enum):
    OPEN_PROBATE = "OPEN_PROBATE"
    CONFIRM_EXECUTOR = "CONFIRM_EXECUTOR"
    APPROVE_INVENTORY = "APPROVE_INVENTORY"
    SETTLE_CREDITORS = "SETTLE_CREDITORS"
    FINAL_DISTRIBUTION = "FINAL_DISTRIBUTION"
    CLOSE_ESTATE = "CLOSE_ESTATE"


class UserRole(str, Enum):
    EstatePlanner = "EstatePlanner"
    Executor = "Executor"
    Judge = "Judge"
    Beneficiary = "Beneficiary"
    Registrar = "Registrar"
    Creditor = "Creditor"
    PlatformAdmin = "PlatformAdmin"


# ─── Entity TypedDicts ────────────────────────────────────────────────────

class Decedent(TypedDict, total=False):
    id: str
    full_legal_name: str
    date_of_birth: str
    date_of_death: Optional[str]
    domicile_state_code: str
    ssn_last4: str
    created_at: str
    updated_at: str
    version: int


class Estate(TypedDict, total=False):
    id: str
    decedent_id: str
    status: str
    gross_estate_value_cents: int
    net_taxable_estate_cents: int
    inventory_snapshot_gross_cents: Optional[int]
    executor_user_id: Optional[str]
    probate_filed_at: Optional[str]
    probate_opened_at: Optional[str]
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Asset(TypedDict, total=False):
    id: str
    estate_id: str
    category: str
    description: str
    appraised_value_cents: int
    status: str
    beneficiary_designation_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BeneficiaryDesignation(TypedDict, total=False):
    id: str
    estate_id: str
    beneficiary_full_name: str
    relationship: str
    share_basis_points: int
    status: str
    contingent_of_designation_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Executor(TypedDict, total=False):
    id: str
    estate_id: str
    full_legal_name: str
    role_type: str
    status: str
    is_also_beneficiary: bool
    created_at: str
    updated_at: str
    version: int


class PowerOfAttorney(TypedDict, total=False):
    id: str
    decedent_id: str
    agent_full_name: str
    scope: str
    status: str
    effective_at: Optional[str]
    effective_until: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EndOfLifeDirective(TypedDict, total=False):
    id: str
    decedent_id: str
    directive_type: str
    status: str
    physician_attester_user_id: Optional[str]
    hipaa_authorized_recipients: List[str]
    created_at: str
    updated_at: str
    version: int


class Guardianship(TypedDict, total=False):
    id: str
    estate_id: str
    ward_full_name: str
    ward_date_of_birth: str
    guardian_full_name: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CreditorClaim(TypedDict, total=False):
    id: str
    estate_id: str
    creditor_name: str
    amount_cents: int
    claim_class: str
    filed_at: str
    paid_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ProbateOrder(TypedDict, total=False):
    id: str
    estate_id: str
    order_type: str
    judge_user_id: str
    status: str
    entered_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
