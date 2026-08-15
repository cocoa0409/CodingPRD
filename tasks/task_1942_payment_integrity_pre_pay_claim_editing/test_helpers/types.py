"""Domain types: entity TypedDicts, status enums, role enum.

All field names follow the PRD exactly. Every resource carries the standard
four system-managed fields id + created_at + updated_at + version (PRD section
on resource identity, timestamps, and entity versions).
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PROVIDER = "Provider"
    PLAN_ADMIN = "PlanAdmin"
    EDIT_LIBRARIAN = "EditLibrarian"
    EDIT_APPROVER = "EditApprover"
    REVIEWER = "Reviewer"
    SENIOR_REVIEWER = "SeniorReviewer"
    DISPUTE_ADJUDICATOR = "DisputeAdjudicator"
    PAYMENT_INTEGRITY_ANALYST = "PaymentIntegrityAnalyst"


class ProviderStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class EditCategory(str, Enum):
    CLINICAL = "CLINICAL"
    CODING = "CODING"
    POLICY = "POLICY"


class EditSource(str, Enum):
    INTERNAL = "INTERNAL"
    VENDOR = "VENDOR"


class Severity(str, Enum):
    DENY = "DENY"
    SUSPEND = "SUSPEND"
    MONITOR = "MONITOR"


class ClaimType(str, Enum):
    PROFESSIONAL = "PROFESSIONAL"
    INSTITUTIONAL_INPATIENT = "INSTITUTIONAL_INPATIENT"
    INSTITUTIONAL_OUTPATIENT = "INSTITUTIONAL_OUTPATIENT"


class DischargeDisposition(str, Enum):
    HOME = "HOME"
    TRANSFER = "TRANSFER"


class EditVersionStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    RETIRED = "RETIRED"


class ComparisonStatus(str, Enum):
    UNMAPPED = "UNMAPPED"
    DUPLICATE = "DUPLICATE"
    COMPLEMENTARY = "COMPLEMENTARY"


class ClaimStatus(str, Enum):
    RECEIVED = "RECEIVED"
    PENDED = "PENDED"
    DETERMINED = "DETERMINED"
    READY_TO_PAY = "READY_TO_PAY"
    DENIED = "DENIED"
    PAID = "PAID"


class EditHitStatus(str, Enum):
    FIRED = "FIRED"
    CONFIRMED = "CONFIRMED"
    OVERRIDDEN = "OVERRIDDEN"
    RELEASED_FALSE_POSITIVE = "RELEASED_FALSE_POSITIVE"
    SUPERSEDED = "SUPERSEDED"


class ReviewTaskStatus(str, Enum):
    PENDING = "PENDING"
    IN_REVIEW = "IN_REVIEW"
    ESCALATED = "ESCALATED"
    DECIDED = "DECIDED"
    CANCELLED = "CANCELLED"


class TaskOutcome(str, Enum):
    UPHOLD = "UPHOLD"
    OVERRIDE = "OVERRIDE"


class DisputeStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    AWAITING_PROVIDER_INFO = "AWAITING_PROVIDER_INFO"
    DECIDED = "DECIDED"


class DisputeOutcome(str, Enum):
    UPHELD = "UPHELD"
    OVERTURNED = "OVERTURNED"
    PARTIAL = "PARTIAL"


class IbrStatus(str, Enum):
    REQUESTED = "REQUESTED"
    DOCUMENTS_RECEIVED = "DOCUMENTS_RECEIVED"
    IN_AUDIT = "IN_AUDIT"
    COMPLETED = "COMPLETED"
    EXPIRED = "EXPIRED"


class InpatientReviewType(str, Enum):
    DRG_VALIDATION = "DRG_VALIDATION"
    READMISSION = "READMISSION"


class InpatientReviewStatus(str, Enum):
    OPEN = "OPEN"
    FINDINGS_RECORDED = "FINDINGS_RECORDED"
    DECIDED = "DECIDED"


class InpatientOutcome(str, Enum):
    NO_CHANGE = "NO_CHANGE"
    DRG_REASSIGNED = "DRG_REASSIGNED"
    DENIED_READMISSION = "DENIED_READMISSION"
    PARTIAL_REDUCTION = "PARTIAL_REDUCTION"


class AbrasionTier(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class SavingsPeriodStatus(str, Enum):
    OPEN = "OPEN"
    RECONCILING = "RECONCILING"
    FINALIZED = "FINALIZED"


class Provider(TypedDict):
    id: str
    npi: str
    name: str
    status: str
    created_at: str
    updated_at: str
    version: int


class EditRule(TypedDict):
    id: str
    edit_code: str
    category: str
    source: str
    description: str
    active_version_count: int
    created_at: str
    updated_at: str
    version: int


class EditVersion(TypedDict):
    id: str
    edit_rule_id: str
    version_number: int
    severity: str
    applies_to_claim_types: List[str]
    logic_expression: str
    effective_from: str
    effective_to: Optional[str]
    status: str
    created_by_user_id: str
    approved_by_user_id: Optional[str]
    resolved_hits_count: int
    fp_hits_count: int
    fp_rate: float
    created_at: str
    updated_at: str
    version: int


class VendorEdit(TypedDict):
    id: str
    vendor_name: str
    vendor_edit_key: str
    description: str
    mapped_edit_rule_id: Optional[str]
    comparison_status: str
    conflict_policy: str
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict):
    id: str
    claim_number: str
    provider_id: str
    member_id: str
    claim_type: str
    total_billed_cents: int
    service_from: str
    service_to: str
    admission_date: Optional[str]
    discharge_date: Optional[str]
    drg_code: Optional[str]
    discharge_disposition: str
    status: str
    initial_allowed_cents: int
    allowed_amount_cents: int
    denied_amount_cents: int
    high_dollar_flag: bool
    readmission_flag: bool
    determined_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ClaimLine(TypedDict):
    id: str
    claim_id: str
    line_number: int
    procedure_code: str
    units: int
    billed_cents: int
    allowed_cents: int
    denied_cents: int
    created_at: str
    updated_at: str
    version: int


class EditHit(TypedDict):
    id: str
    claim_id: str
    claim_line_id: str
    edit_version_id: str
    vendor_edit_id: Optional[str]
    status: str
    applied: bool
    expected_savings_cents: int
    attributed_savings_cents: int
    released_cents: int
    confirmed_by_user_id: Optional[str]
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReviewTask(TypedDict):
    id: str
    claim_id: str
    edit_hit_id: str
    status: str
    assigned_reviewer_user_id: Optional[str]
    requires_senior: bool
    outcome: Optional[str]
    decision_reason: str
    created_at: str
    updated_at: str
    version: int


class Dispute(TypedDict):
    id: str
    claim_id: str
    edit_hit_id: str
    provider_id: str
    reason: str
    status: str
    outcome: Optional[str]
    released_cents: int
    submitted_at: str
    decided_at: Optional[str]
    adjudicated_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ItemizedBillReview(TypedDict):
    id: str
    claim_id: str
    provider_id: str
    status: str
    requested_at: str
    due_at: str
    completed_at: Optional[str]
    findings_cents: int
    repriced_total_cents: Optional[int]
    auditor_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InpatientReview(TypedDict):
    id: str
    claim_id: str
    review_type: str
    status: str
    provider_drg_code: str
    audited_drg_code: Optional[str]
    prior_claim_id: Optional[str]
    gap_days: Optional[int]
    outcome: Optional[str]
    payment_delta_cents: int
    created_at: str
    updated_at: str
    version: int


class ProviderAbrasionProfile(TypedDict):
    id: str
    provider_id: str
    confirmed_count: int
    overridden_count: int
    fp_count: int
    superseded_count: int
    denied_cents_lifetime: int
    released_cents_lifetime: int
    open_ibr_count: int
    standard_index: float
    regulatory_index: float
    tier: str
    monitor_only: bool
    created_at: str
    updated_at: str
    version: int


class SavingsPeriod(TypedDict):
    id: str
    period_key: str
    status: str
    provisional_savings_cents: int
    finalized_savings_cents: int
    pending_pipeline_cents: int
    reversed_cents: int
    finalized_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
