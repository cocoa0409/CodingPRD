"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the Online Will & Estate Planning PRD. Entities that can be
mutated after creation carry `updated_at` and `version`; the plan catalog is
configuration and carries only `id` and `created_at`.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Role enum -----------------------------------------------------------
class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    MEMBER = "Member"
    ATTORNEY = "Attorney"
    NOTARY = "Notary"
    PLATFORM_ADMIN = "PlatformAdmin"


# --- Value enums ---------------------------------------------------------
class PlanTier(str, Enum):
    BASIC = "BASIC"
    PLUS = "PLUS"
    PREMIER = "PREMIER"


class BundleType(str, Enum):
    INDIVIDUAL = "INDIVIDUAL"
    COUPLE = "COUPLE"


class DocumentType(str, Enum):
    WILL = "WILL"
    TRUST = "TRUST"
    POA = "POA"
    HEALTHCARE_DIRECTIVE = "HEALTHCARE_DIRECTIVE"


class Relationship(str, Enum):
    SPOUSE = "SPOUSE"
    CHILD = "CHILD"
    RELATIVE = "RELATIVE"
    CHARITY = "CHARITY"
    OTHER = "OTHER"


class AssetType(str, Enum):
    REAL_ESTATE = "REAL_ESTATE"
    BANK = "BANK"
    INVESTMENT = "INVESTMENT"
    VEHICLE = "VEHICLE"
    PERSONAL = "PERSONAL"
    BUSINESS = "BUSINESS"


class FundingStatus(str, Enum):
    UNFUNDED = "UNFUNDED"
    PENDING = "PENDING"
    FUNDED = "FUNDED"


class ShareScope(str, Enum):
    VIEW = "VIEW"
    FULL = "FULL"
    EXECUTOR_ACCESS = "EXECUTOR_ACCESS"


# --- Status enums --------------------------------------------------------
class SubscriptionStatus(str, Enum):
    PENDING_PAYMENT = "PENDING_PAYMENT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class QuestionnaireStatus(str, Enum):
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    LOCKED = "LOCKED"


class EstateDocumentStatus(str, Enum):
    GENERATED = "GENERATED"
    IN_REVIEW = "IN_REVIEW"
    PENDING_EXECUTION = "PENDING_EXECUTION"
    EXECUTED = "EXECUTED"
    SUPERSEDED = "SUPERSEDED"
    REVOKED = "REVOKED"


class AttorneyReviewStatus(str, Enum):
    REQUESTED = "REQUESTED"
    IN_REVIEW = "IN_REVIEW"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    APPROVED = "APPROVED"
    CLOSED = "CLOSED"


class ExecutorStatus(str, Enum):
    NOMINATED = "NOMINATED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    REVOKED = "REVOKED"


class ShareGrantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


# --- Entity TypedDicts ---------------------------------------------------
# PlanCatalog: configuration — id + created_at only (no updated_at / version).
class PlanCatalog(TypedDict):
    id: str
    created_at: str
    plan_tier: str
    base_price_cents: int
    included_document_types: List[str]
    max_documents: int
    allows_trust: bool


class Member(TypedDict):
    id: str
    email: str
    full_name: str
    state_code: str
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict):
    id: str
    member_id: str
    plan_tier: str
    bundle_type: str
    spouse_name: Optional[str]
    spouse_email: Optional[str]
    attorney_support: bool
    status: str
    price_cents: int
    pending_charge_cents: int
    paid_to_date_cents: int
    refunded_cents: int
    current_period_start: Optional[str]
    current_period_end: Optional[str]
    renewal_count: int
    renewal_pending: bool
    created_at: str
    updated_at: str
    version: int


class Questionnaire(TypedDict):
    id: str
    subscription_id: str
    document_type: str
    state_code: str
    answers: dict
    required_field_count: int
    answered_field_count: int
    completeness_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class EstateDocument(TypedDict):
    id: str
    subscription_id: str
    questionnaire_id: str
    document_type: str
    state_code: str
    status: str
    doc_version: int
    requires_notary: bool
    witness_count_required: int
    witnesses_count: int
    execution_date: Optional[str]
    superseded_by_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Beneficiary(TypedDict):
    id: str
    subscription_id: str
    full_name: str
    relationship: str
    allocation_pct: float
    is_contingent: bool
    allocated_cents: int
    created_at: str
    updated_at: str
    version: int


class Asset(TypedDict):
    id: str
    subscription_id: str
    asset_type: str
    description: str
    estimated_value_cents: int
    funding_status: str
    assigned_beneficiary_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Executor(TypedDict):
    id: str
    subscription_id: str
    full_name: str
    email: str
    priority_order: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ShareGrant(TypedDict):
    id: str
    document_id: str
    grantee_email: str
    scope: str
    status: str
    expires_at: str
    created_at: str
    updated_at: str
    version: int


class AttorneyReview(TypedDict):
    id: str
    document_id: str
    attorney_user_id: Optional[str]
    status: str
    notes: Optional[str]
    created_at: str
    updated_at: str
    version: int
