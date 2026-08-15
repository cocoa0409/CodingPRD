"""Domain types: entity TypedDicts, status enums, role enum.

Field names and enum members follow PRD.md exactly.
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD section 2.1)
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    MGA_UNDERWRITER = "MGAUnderwriter"
    MGA_FINANCE = "MGAFinance"
    CARRIER_UNDERWRITER = "CarrierUnderwriter"
    CARRIER_AUDITOR = "CarrierAuditor"
    TPA_ADJUSTER = "TPAAdjuster"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------

class CarrierStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class TPAStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ProgramStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    RUN_OFF = "RUN_OFF"
    TERMINATED = "TERMINATED"
    DECLINED = "DECLINED"


class GuidelineStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    INACTIVE = "INACTIVE"


class AllocationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"
    SUPERSEDED = "SUPERSEDED"
    RELEASED = "RELEASED"


class FilingStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DISAPPROVED = "DISAPPROVED"
    EFFECTIVE = "EFFECTIVE"
    SUPERSEDED = "SUPERSEDED"
    WITHDRAWN = "WITHDRAWN"


class PolicyStatus(str, Enum):
    QUOTED = "QUOTED"
    BOUND = "BOUND"
    ISSUED = "ISSUED"
    PENDING_CANCELLATION = "PENDING_CANCELLATION"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    WITHDRAWN = "WITHDRAWN"


class AuditStatus(str, Enum):
    NOT_AUDITED = "NOT_AUDITED"
    AUDITED = "AUDITED"


class ClaimStatus(str, Enum):
    REPORTED = "REPORTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    REFERRED = "REFERRED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    PAID = "PAID"
    REOPENED = "REOPENED"
    CLOSED = "CLOSED"


class AppointmentStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class BordereauStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class CarrierAuditStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    FINDINGS_ISSUED = "FINDINGS_ISSUED"
    REMEDIATION = "REMEDIATION"
    CLOSED = "CLOSED"
    ESCALATED = "ESCALATED"


class LedgerEntryType(str, Enum):
    COLLECTION = "COLLECTION"
    REFUND = "REFUND"
    CLAIM_PAYMENT = "CLAIM_PAYMENT"
    CARRIER_REMITTANCE = "CARRIER_REMITTANCE"


class LineOfBusiness(str, Enum):
    COMMERCIAL_AUTO = "COMMERCIAL_AUTO"
    GENERAL_LIABILITY = "GENERAL_LIABILITY"
    PROPERTY = "PROPERTY"
    WORKERS_COMPENSATION = "WORKERS_COMPENSATION"
    PROFESSIONAL_LIABILITY = "PROFESSIONAL_LIABILITY"


class FilingType(str, Enum):
    RATE = "RATE"
    RULE = "RULE"
    FORM = "FORM"


class ClaimType(str, Enum):
    PROPERTY_DAMAGE = "PROPERTY_DAMAGE"
    BODILY_INJURY = "BODILY_INJURY"
    LIABILITY = "LIABILITY"
    OTHER = "OTHER"


class CancellationReason(str, Enum):
    INSURED_REQUEST = "INSURED_REQUEST"
    CARRIER_REQUEST = "CARRIER_REQUEST"
    NON_PAYMENT = "NON_PAYMENT"


class ReferralReason(str, Enum):
    AUTHORITY_EXCEEDED = "AUTHORITY_EXCEEDED"
    ADJUSTER_ESCALATION = "ADJUSTER_ESCALATION"
    APPOINTMENT_SUSPENDED = "APPOINTMENT_SUSPENDED"


class AuditScope(str, Enum):
    UNDERWRITING = "UNDERWRITING"
    CLAIMS = "CLAIMS"
    TRUST_ACCOUNTING = "TRUST_ACCOUNTING"
    FULL = "FULL"


class AuditOutcome(str, Enum):
    SATISFACTORY = "SATISFACTORY"
    CORRECTIVE_ACTION = "CORRECTIVE_ACTION"
    TERMINATION_RECOMMENDED = "TERMINATION_RECOMMENDED"


class LossEvalOutcome(str, Enum):
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    OK = "OK"
    CORRECTIVE_ACTION = "CORRECTIVE_ACTION"
    TERMINATION_REVIEW = "TERMINATION_REVIEW"


# ---------------------------------------------------------------------------
# Entity TypedDicts (common_fields: true -> id + created_at + updated_at + version)
# ---------------------------------------------------------------------------

class Carrier(TypedDict, total=False):
    id: str
    name: str
    naic_code: str
    contact_email: str
    status: str
    created_at: str
    updated_at: str
    version: int


class TPA(TypedDict, total=False):
    id: str
    name: str
    license_number: str
    contact_email: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Program(TypedDict, total=False):
    id: str
    carrier_id: str
    name: str
    line_of_business: str
    states_covered: List[str]
    inception_date: str
    aggregate_limit_cents: int
    commission_rate_pct: float
    corrective_threshold_pct: int
    termination_threshold_pct: int
    min_trust_balance_cents: int
    min_earned_premium_for_ratio_cents: int
    status: str
    consumed_aggregate_cents: int
    trust_balance_cents: int
    latest_incurred_loss_ratio_pct: Optional[float]
    termination_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class UnderwritingGuideline(TypedDict, total=False):
    id: str
    program_id: str
    state_code: str
    class_code: str
    max_policy_premium_cents: int
    max_policy_limit_cents: int
    min_policy_premium_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CapacityAllocation(TypedDict, total=False):
    id: str
    program_id: str
    period_label: str
    allocated_cents: int
    consumed_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RateFiling(TypedDict, total=False):
    id: str
    program_id: str
    state_code: str
    filing_type: str
    base_rates: Dict[str, int]
    policy_fee_cents: int
    effective_from: str
    effective_to: str
    status: str
    version_seq: int
    submitted_at: Optional[str]
    approved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Policy(TypedDict, total=False):
    id: str
    program_id: str
    filing_id: str
    insured_name: str
    state_code: str
    class_code: str
    exposure_units: int
    coverage_limit_cents: int
    experience_mod: float
    effective_from: str
    effective_to: str
    status: str
    audit_status: str
    gross_premium_cents: int
    final_premium_cents: Optional[int]
    mga_commission_cents: int
    collected_cents: int
    earned_premium_cents: int
    quote_valid_until: str
    bound_at: Optional[str]
    issued_at: Optional[str]
    cancelled_at: Optional[str]
    cancellation_date: Optional[str]
    cancellation_reason: Optional[str]
    pre_cancel_status: Optional[str]
    capacity_released_cents: int
    reported_premium_bordereau_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict, total=False):
    id: str
    policy_id: str
    program_id: str
    assigned_tpa_id: str
    claim_type: str
    occurrence_date: str
    amount_claimed_cents: int
    case_reserve_cents: int
    approved_amount_cents: Optional[int]
    paid_cents: int
    status: str
    denial_reason: Optional[str]
    denied_at: Optional[str]
    reopened_count: int
    paid_at: Optional[str]
    referral_reason: Optional[str]
    reported_claim_bordereau_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TPAAppointment(TypedDict, total=False):
    id: str
    program_id: str
    tpa_id: str
    claim_type: str
    authority_limit_cents: int
    effective_from: str
    effective_to: str
    status: str
    created_at: str
    updated_at: str
    version: int


# TrustLedgerEntry: common_fields false -> id + created_at only (append-only).
class TrustLedgerEntry(TypedDict, total=False):
    id: str
    created_at: str
    program_id: str
    policy_id: Optional[str]
    claim_id: Optional[str]
    entry_type: str
    amount_cents: int
    basis_cents: Optional[int]
    running_balance_cents: int
    memo: Optional[str]


class Bordereau(TypedDict, total=False):
    id: str
    program_id: str
    bordereau_type: str
    period_label: str
    rows: List[Dict[str, Any]]
    declared_totals: Dict[str, int]
    computed_totals: Dict[str, int]
    row_count: int
    due_date: str
    overdue: bool
    status: str
    rejection_reason: Optional[str]
    submitted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CarrierAudit(TypedDict, total=False):
    id: str
    program_id: str
    scope: str
    scheduled_start: str
    scheduled_end: str
    findings: List[Dict[str, Any]]
    status: str
    outcome: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LossEvaluation(TypedDict, total=False):
    id: str
    program_id: str
    period_label: str
    earned_premium_cents: int
    paid_losses_cents: int
    case_reserves_cents: int
    paid_loss_ratio_pct: Optional[float]
    incurred_loss_ratio_pct: Optional[float]
    outcome: str
    created_at: str
    updated_at: str
    version: int
