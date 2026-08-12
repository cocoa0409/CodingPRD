"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class LeaseStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"


class AbstractionStatus(str, Enum):
    PENDING = "PENDING"
    ABSTRACTED = "ABSTRACTED"
    CERTIFIED = "CERTIFIED"


class BillingPosture(str, Enum):
    CURRENT = "CURRENT"
    FROZEN = "FROZEN"
    DELINQUENT = "DELINQUENT"


class PropertyPosture(str, Enum):
    OPERATING = "OPERATING"
    SUSPENDED = "SUSPENDED"


class EscalationType(str, Enum):
    NONE = "NONE"
    FIXED_PCT = "FIXED_PCT"
    CPI = "CPI"
    STEPPED = "STEPPED"


class RecoveryStructure(str, Enum):
    NNN = "NNN"
    MODIFIED_GROSS = "MODIFIED_GROSS"
    GROSS = "GROSS"


class EscalationStepKind(str, Enum):
    FIXED_PCT = "FIXED_PCT"
    CPI_LOOKUP = "CPI_LOOKUP"
    STEPPED_AMOUNT = "STEPPED_AMOUNT"


class RecoveryCategory(str, Enum):
    CAM = "CAM"
    TAX = "TAX"
    INSURANCE = "INSURANCE"
    UTILITIES = "UTILITIES"
    MANAGEMENT_FEE = "MANAGEMENT_FEE"


class RecoveryBillingStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PAID = "PAID"
    DISPUTED = "DISPUTED"
    VOID = "VOID"


class ReconciliationStatus(str, Enum):
    OPEN = "OPEN"
    POSTED = "POSTED"
    APPROVED = "APPROVED"
    CLOSED = "CLOSED"
    CHALLENGED = "CHALLENGED"


class CriticalDateKind(str, Enum):
    OPTION_EXERCISE = "OPTION_EXERCISE"
    NOTICE_DEADLINE = "NOTICE_DEADLINE"
    EXPIRATION = "EXPIRATION"
    RENEWAL_WINDOW_OPEN = "RENEWAL_WINDOW_OPEN"
    RENEWAL_WINDOW_CLOSE = "RENEWAL_WINDOW_CLOSE"
    AUDIT_WINDOW_CLOSE = "AUDIT_WINDOW_CLOSE"


class CriticalDateStatus(str, Enum):
    PENDING = "PENDING"
    NOTIFIED = "NOTIFIED"
    EXERCISED = "EXERCISED"
    LAPSED = "LAPSED"
    WAIVED = "WAIVED"


class ComplianceDocKind(str, Enum):
    INSURANCE_CERT = "INSURANCE_CERT"
    ESTOPPEL = "ESTOPPEL"
    FINANCIAL_STMT = "FINANCIAL_STMT"
    SNDA = "SNDA"


class ComplianceDocStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class AmendmentKind(str, Enum):
    EXTENSION = "EXTENSION"
    CONTRACTION = "CONTRACTION"
    EXPANSION = "EXPANSION"
    ASSIGNMENT = "ASSIGNMENT"
    RENT_CHANGE = "RENT_CHANGE"
    USE_CHANGE = "USE_CHANGE"


class AmendmentStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    APPLIED = "APPLIED"
    REJECTED = "REJECTED"


class ChallengeReasonCode(str, Enum):
    GROSS_UP_DISPUTE = "GROSS_UP_DISPUTE"
    PRO_RATA_DISPUTE = "PRO_RATA_DISPUTE"
    AUDIT_FINDING = "AUDIT_FINDING"
    MATH_ERROR = "MATH_ERROR"
    POOL_MISCLASS = "POOL_MISCLASS"


class TenantChallengeStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    RESOLVED_ACCEPTED = "RESOLVED_ACCEPTED"
    RESOLVED_REJECTED = "RESOLVED_REJECTED"
    ESCALATED = "ESCALATED"
    WITHDRAWN = "WITHDRAWN"


class AuditRightStatus(str, Enum):
    INVOKED = "INVOKED"
    FIELDWORK = "FIELDWORK"
    FINDINGS_ISSUED = "FINDINGS_ISSUED"
    SETTLED = "SETTLED"
    TIME_BARRED = "TIME_BARRED"


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    PORTFOLIO_MANAGER = "PortfolioManager"
    PROPERTY_MANAGER = "PropertyManager"
    LEASE_ACCOUNTANT = "LeaseAccountant"
    ABSTRACTOR = "Abstractor"
    CERTIFIER = "Certifier"


# ---------------------------------------------------------------------------
# Entity TypedDicts. Every resource carries the standard system-managed fields
# id / created_at / updated_at / version (PRD §2.4).
# ---------------------------------------------------------------------------


class Property(TypedDict, total=False):
    id: str
    name: str
    address: str
    total_rentable_sf: int
    fiscal_year_end_month: int
    posture: str
    created_at: str
    updated_at: str
    version: int


class Lease(TypedDict, total=False):
    id: str
    property_id: str
    tenant_legal_name: str
    suite: str
    leased_sf: int
    commencement_date: str
    expiration_date: str
    base_rent_annual_cents: int
    escalation_type: str
    recovery_structure: str
    pro_rata_share_bps: int
    status: str
    abstraction_status: str
    billing_posture: str
    cached_annual_rent_cents: int
    cached_recovery_ytd_cents: int
    security_deposit_cents: int
    abstractor_user_id: Optional[str]
    certifier_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RentScheduleLine(TypedDict, total=False):
    id: str
    lease_id: str
    period_start: str
    period_end: str
    base_rent_cents: int
    escalation_step_id: Optional[str]
    effective_rent_cents: int
    created_at: str
    updated_at: str
    version: int


class EscalationStep(TypedDict, total=False):
    id: str
    lease_id: str
    step_index: int
    kind: str
    pct_bps: Optional[int]
    amount_cents: Optional[int]
    effective_on: str
    created_at: str
    updated_at: str
    version: int


class RecoveryPool(TypedDict, total=False):
    id: str
    property_id: str
    category: str
    fiscal_year: int
    budgeted_cents: int
    actual_cents: Optional[int]
    gross_up_floor_pct_bps: int
    created_at: str
    updated_at: str
    version: int


class RecoveryBilling(TypedDict, total=False):
    id: str
    lease_id: str
    pool_id: str
    fiscal_year: int
    period_index: int
    estimate_cents: int
    final_cents: Optional[int]
    status: str
    issued_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Reconciliation(TypedDict, total=False):
    id: str
    lease_id: str
    fiscal_year: int
    status: str
    posted_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    true_up_cents: Optional[int]
    gross_up_applied: Optional[bool]
    created_at: str
    updated_at: str
    version: int


class CriticalDate(TypedDict, total=False):
    id: str
    lease_id: str
    kind: str
    due_date: str
    advance_notice_days: int
    status: str
    linked_amendment_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ComplianceDoc(TypedDict, total=False):
    id: str
    lease_id: str
    kind: str
    period_start: str
    period_end: str
    status: str
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Amendment(TypedDict, total=False):
    id: str
    lease_id: str
    kind: str
    effective_date: str
    new_expiration_date: Optional[str]
    new_leased_sf: Optional[int]
    new_base_rent_annual_cents: Optional[int]
    new_tenant_legal_name: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class TenantChallenge(TypedDict, total=False):
    id: str
    lease_id: str
    reconciliation_id: str
    recovery_billing_id: Optional[str]
    reason_code: str
    claimed_overbilling_cents: int
    status: str
    round_index: int
    resolution_delta_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class AuditRight(TypedDict, total=False):
    id: str
    lease_id: str
    reconciliation_id: str
    invoked_on: str
    window_close_date: str
    status: str
    findings_delta_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int
