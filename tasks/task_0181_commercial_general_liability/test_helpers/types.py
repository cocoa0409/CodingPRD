"""Domain types: entity TypedDicts, status enums, role enum for the CGL platform."""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Role enum (PRD §2.1) ---
class UserRole(str, Enum):
    INSURER_ADMIN = "InsurerAdmin"
    UNDERWRITER = "Underwriter"
    CLAIMS_ADJUSTER = "ClaimsAdjuster"
    PREMIUM_AUDITOR = "PremiumAuditor"
    CERTIFICATE_HOLDER = "CertificateHolder"


# --- Status enums ---
class PolicyStatus(str, Enum):
    DRAFT = "DRAFT"
    BOUND = "BOUND"
    IN_FORCE = "IN_FORCE"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"
    AUDIT_CLOSED = "AUDIT_CLOSED"


class PolicyPosture(str, Enum):
    HEALTHY = "HEALTHY"
    IMPAIRED = "IMPAIRED"
    EXHAUSTED = "EXHAUSTED"


class CoverageTrigger(str, Enum):
    OCCURRENCE = "OCCURRENCE"
    CLAIMS_MADE = "CLAIMS_MADE"


class PremiumBasis(str, Enum):
    PAYROLL = "PAYROLL"
    SALES = "SALES"


class EndorsementStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    VOID = "VOID"


class EndorsementForm(str, Enum):
    CG2010 = "CG2010"
    CG2037 = "CG2037"
    CG2010_2037 = "CG2010_2037"


class EndorsementScope(str, Enum):
    ONGOING_OPS = "ONGOING_OPS"
    COMPLETED_OPS = "COMPLETED_OPS"
    BOTH = "BOTH"


class CertificateStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class ClaimStatus(str, Enum):
    OPEN = "OPEN"
    RESERVED = "RESERVED"
    PAID = "PAID"
    CLOSED = "CLOSED"
    DENIED = "DENIED"
    REOPENED = "REOPENED"


class LossType(str, Enum):
    BODILY_INJURY = "BODILY_INJURY"
    PROPERTY_DAMAGE = "PROPERTY_DAMAGE"
    PRODUCTS_COMPLETED_OPS = "PRODUCTS_COMPLETED_OPS"


class AggregateBucket(str, Enum):
    GENERAL = "GENERAL"
    PRODUCTS = "PRODUCTS"


class TxnType(str, Enum):
    RESERVE_SET = "RESERVE_SET"
    RESERVE_RELEASE = "RESERVE_RELEASE"
    PAYMENT = "PAYMENT"
    RECOVERY = "RECOVERY"


class AuditStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    DISPUTED = "DISPUTED"
    FINALIZED = "FINALIZED"
    WAIVED = "WAIVED"


# --- Entity TypedDicts ---
# common_fields: true -> id + created_at + updated_at + version

class Insurer(TypedDict):
    id: str
    name: str
    naic_code: str
    current_date: str
    audit_waiver_threshold_cents: int
    created_at: str
    updated_at: str
    version: int


class Insured(TypedDict):
    id: str
    insurer_id: str
    legal_name: str
    fein: str
    primary_basis: str
    created_at: str
    updated_at: str
    version: int


class CertificateHolder(TypedDict):
    id: str
    insurer_id: str
    holder_name: str
    address: str
    created_at: str
    updated_at: str
    version: int


class Policy(TypedDict):
    id: str
    insurer_id: str
    insured_id: str
    policy_number: str
    coverage_trigger: str
    retroactive_date: Optional[str]
    effective_date: str
    expiration_date: str
    each_occurrence_limit_cents: int
    general_aggregate_limit_cents: int
    products_aggregate_limit_cents: int
    premium_basis: str
    rate_per_unit_cents: int
    minimum_premium_cents: int
    estimated_exposure_units: int
    estimated_premium_cents: Optional[int]
    audited_premium_cents: Optional[int]
    general_aggregate_remaining_cents: Optional[int]
    products_aggregate_remaining_cents: Optional[int]
    posture: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AdditionalInsuredEndorsement(TypedDict):
    id: str
    policy_id: str
    certificate_holder_id: str
    form_number: str
    scope: str
    ai_effective_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CertificateOfInsurance(TypedDict):
    id: str
    policy_id: str
    certificate_holder_id: str
    additional_insured_endorsement_id: Optional[str]
    names_as_additional_insured: bool
    issue_date: Optional[str]
    snapshot_each_occurrence_cents: Optional[int]
    snapshot_general_aggregate_remaining_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict):
    id: str
    policy_id: str
    claimant_name: str
    loss_type: str
    occurrence_date: str
    reported_date: str
    aggregate_bucket: str
    incurred_cents: int
    recognized_incurred_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false -> immutable ledger entry: ONLY id + created_at
class ClaimTransaction(TypedDict):
    id: str
    claim_id: str
    txn_type: str
    amount_cents: int
    posted_sequence: int
    memo: Optional[str]
    created_at: str


class PremiumAudit(TypedDict):
    id: str
    policy_id: str
    audit_basis: str
    audited_exposure_units: int
    computed_audited_premium_cents: Optional[int]
    net_adjustment_cents: Optional[int]
    revision_round: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ExposureRecord(TypedDict):
    id: str
    premium_audit_id: str
    class_code: str
    basis_amount_units: int
    created_at: str
    updated_at: str
    version: int


class LossRun(TypedDict):
    id: str
    policy_id: str
    as_of_date: str
    total_incurred_cents: int
    general_incurred_cents: int
    products_incurred_cents: int
    claim_count: int
    open_claim_count: int
    created_at: str
    updated_at: str
    version: int
