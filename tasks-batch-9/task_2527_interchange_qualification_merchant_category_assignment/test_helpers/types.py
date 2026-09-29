"""Domain types: status enums, role enum and entity TypedDicts (PRD Sections 2 and 3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    NETWORK_ADMIN = "NetworkAdmin"
    ACQUIRER_OPS = "AcquirerOps"
    CATEGORY_ANALYST = "CategoryAnalyst"
    CATEGORY_APPROVER = "CategoryApprover"
    COMPLIANCE_AUDITOR = "ComplianceAuditor"


class RegionCode(str, Enum):
    NA = "NA"
    EU = "EU"
    AP = "AP"
    LAC = "LAC"
    CEMEA = "CEMEA"


class ComplianceStatus(str, Enum):
    COMPLIANT = "COMPLIANT"
    NON_COMPLIANT = "NON_COMPLIANT"


class ProgramEligibility(str, Enum):
    SMALL_TICKET = "SMALL_TICKET"
    UTILITY = "UTILITY"
    GOVERNMENT = "GOVERNMENT"
    CHARITY = "CHARITY"


class RateProgramCategory(str, Enum):
    CPS_RETAIL = "CPS_RETAIL"
    SMALL_TICKET = "SMALL_TICKET"
    UTILITY = "UTILITY"
    GOVERNMENT = "GOVERNMENT"
    CHARITY = "CHARITY"
    STANDARD = "STANDARD"


class RateProgramVersionStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


class ImplementationWindowStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    COMPLETED_LATE = "COMPLETED_LATE"
    MISSED = "MISSED"


class MccStatus(str, Enum):
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    VERIFIED = "VERIFIED"
    UNDER_REVIEW = "UNDER_REVIEW"
    MISREPRESENTED = "MISREPRESENTED"


class ReclassificationRequestStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    INFO_REQUESTED = "INFO_REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    SUPERSEDED = "SUPERSEDED"
    SUSPENDED_PENDING_AUDIT = "SUSPENDED_PENDING_AUDIT"


class SettlementBatchStatus(str, Enum):
    OPEN = "OPEN"
    SUBMITTED = "SUBMITTED"
    FINALIZED = "FINALIZED"


class AuthorizationStatus(str, Enum):
    AUTH_APPROVED = "AUTH_APPROVED"
    AUTH_REVERSED = "AUTH_REVERSED"
    AUTH_EXPIRED = "AUTH_EXPIRED"


class QualificationStatus(str, Enum):
    PENDING = "PENDING"
    QUALIFIED = "QUALIFIED"
    DOWNGRADED = "DOWNGRADED"
    REVERSED = "REVERSED"


class DowngradeReason(str, Enum):
    MISSING_DATA_ELEMENTS = "MISSING_DATA_ELEMENTS"
    LATE_CLEARING = "LATE_CLEARING"
    TICKET_SIZE_INELIGIBLE = "TICKET_SIZE_INELIGIBLE"
    AUTH_MISSING = "AUTH_MISSING"
    MCC_INELIGIBLE = "MCC_INELIGIBLE"


class ReversalType(str, Enum):
    AUTH_REVERSAL = "AUTH_REVERSAL"
    CLEARING_REVERSAL = "CLEARING_REVERSAL"


class EnrollmentState(str, Enum):
    OPEN = "OPEN"
    CLOSED_FULL = "CLOSED_FULL"


class EnrollmentStatus(str, Enum):
    PENDING = "PENDING"
    ENROLLED = "ENROLLED"
    WAITLISTED = "WAITLISTED"
    PROBATION = "PROBATION"
    TERMINATED_SHORTFALL = "TERMINATED_SHORTFALL"
    TERMINATED_INELIGIBLE = "TERMINATED_INELIGIBLE"
    WITHDRAWN = "WITHDRAWN"


class PerformanceBasis(str, Enum):
    TRAILING = "TRAILING"
    PROJECTED = "PROJECTED"


class TierCode(str, Enum):
    TIER_0 = "TIER_0"
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"


class AuditStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    FIELDWORK = "FIELDWORK"
    FINDINGS_SUSTAINED = "FINDINGS_SUSTAINED"
    FINDINGS_CLEARED = "FINDINGS_CLEARED"
    CLOSED = "CLOSED"


class AuditTriggerReason(str, Enum):
    DOWNGRADE_THRESHOLD = "DOWNGRADE_THRESHOLD"
    RECLASS_SUSPICION = "RECLASS_SUSPICION"
    PERIODIC = "PERIODIC"
    COMPLAINT = "COMPLAINT"


class ReclassificationDecision(str, Enum):
    APPROVE = "APPROVE"
    DENY = "DENY"


# ── Entity TypedDicts ─────────────────────────────────────────────────────
# PRD 2.4: every resource in this service carries id, created_at, updated_at
# and version.


class ProcessingPlatform(TypedDict):
    id: str
    name: str
    region_code: str
    max_concurrent_windows: int
    blackout_buffer_days: int
    created_at: str
    updated_at: str
    version: int


class Acquirer(TypedDict):
    id: str
    name: str
    bin_prefix: str
    platform_id: str
    country_code: str
    settlement_currency: str
    compliance_status: str
    missed_window_count: int
    created_at: str
    updated_at: str
    version: int


class MccDefinition(TypedDict):
    id: str
    mcc_code: str
    description: str
    business_type_key: str
    program_eligibility: List[str]
    requires_documentation: bool
    high_risk: bool
    created_at: str
    updated_at: str
    version: int


class RateProgram(TypedDict):
    id: str
    program_code: str
    name: str
    category: str
    eligible_mcc_codes: List[str]
    base_rate_bps: int
    per_item_fee_cents: int
    requires_data_elements: List[str]
    max_clearing_delay_hours: int
    created_at: str
    updated_at: str
    version: int


class RateProgramVersion(TypedDict):
    id: str
    rate_program_id: str
    publication_quarter: str
    effective_from: str
    effective_to: str
    base_rate_bps: int
    per_item_fee_cents: int
    implementation_deadline: str
    status: str
    published_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AcquirerImplementationWindow(TypedDict):
    id: str
    acquirer_id: str
    rate_program_version_id: str
    platform_id: str
    window_start: str
    window_end: str
    status: str
    started_at: Optional[str]
    completion_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Merchant(TypedDict):
    id: str
    legal_name: str
    business_type_key: str
    acquirer_id: str
    home_country_code: str
    assigned_mcc: str
    mcc_status: str
    mcc_status_before_review: Optional[str]
    documentation_ref: Optional[str]
    verified_by_user_id: Optional[str]
    downgrade_count_current_quarter: int
    lifetime_net_assessed_cents: int
    created_at: str
    updated_at: str
    version: int


class ReclassificationRequest(TypedDict):
    id: str
    merchant_id: str
    requested_mcc: str
    justification: str
    status: str
    review_round: int
    supporting_doc_ref: Optional[str]
    reviewer_user_id: Optional[str]
    info_request_note: Optional[str]
    decider_user_id: Optional[str]
    decision_note: Optional[str]
    decided_mcc: Optional[str]
    prior_status_before_suspension: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FxRate(TypedDict):
    id: str
    base_currency: str
    quote_currency: str
    rate: float
    markup_bps: int
    effective_from: str
    created_at: str
    updated_at: str
    version: int


class SettlementBatch(TypedDict):
    id: str
    acquirer_id: str
    batch_date: str
    currency_code: str
    status: str
    record_count: int
    total_assessed_cents: int
    finalized_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TransactionRecord(TypedDict):
    id: str
    settlement_batch_id: str
    merchant_id: str
    amount_cents: int
    transaction_currency: str
    auth_code: str
    auth_timestamp: str
    clearing_timestamp: str
    data_elements: List[str]
    clearing_delay_hours: int
    cross_border: bool
    authorization_status: str
    qualification_status: str
    provisional_rate_program_id: Optional[str]
    provisional_assessed_cents: int
    qualified_rate_program_id: Optional[str]
    mcc_at_qualification: Optional[str]
    assessed_interchange_cents: int
    cross_border_surcharge_cents: int
    fx_markup_cents: int
    downgrade_reason: Optional[str]
    reversal_type: Optional[str]
    reversal_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class IncentiveProgram(TypedDict):
    id: str
    program_name: str
    eligible_mcc_codes: List[str]
    total_capacity_cents: int
    min_commitment_cents: int
    reopen_threshold_cents: int
    performance_threshold_pct: float
    enrollment_state: str
    uncommitted_capacity_cents: int
    enrolled_count: int
    created_at: str
    updated_at: str
    version: int


class IncentiveEnrollment(TypedDict):
    id: str
    incentive_program_id: str
    merchant_id: str
    committed_volume_cents: int
    waitlist_requested: bool
    status: str
    enrolled_at: Optional[str]
    achieved_volume_cents: int
    gross_assessed_volume_cents: int
    incentive_credit_cents: int
    net_assessed_volume_cents: int
    probation_count: int
    performance_score_pct: float
    last_evaluated_basis: Optional[str]
    tier_code: Optional[str]
    withdrawal_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MerchantCategoryAudit(TypedDict):
    id: str
    merchant_id: str
    trigger_reason: str
    status: str
    auditor_user_id: Optional[str]
    fieldwork_start: Optional[str]
    fieldwork_end: Optional[str]
    correct_mcc: Optional[str]
    findings_note: Optional[str]
    closed_by_user_id: Optional[str]
    penalty_assessed_cents: int
    mcc_at_audit_open: Optional[str]
    created_at: str
    updated_at: str
    version: int
