"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    LITIGATION_COUNSEL = "LitigationCounsel"
    DEPUTY_GENERAL_COUNSEL = "DeputyGeneralCounsel"
    GENERAL_COUNSEL = "GeneralCounsel"
    CHIEF_FINANCIAL_OFFICER = "ChiefFinancialOfficer"
    BOARD_COMMITTEE = "BoardCommittee"
    LEGAL_OPERATIONS_ANALYST = "LegalOperationsAnalyst"
    FINANCE_BUSINESS_PARTNER = "FinanceBusinessPartner"
    STAFF_USER = "StaffUser"


class MatterStatus(str, Enum):
    INTAKE = "INTAKE"
    ASSESSMENT = "ASSESSMENT"
    STAFFING = "STAFFING"
    ACTIVE = "ACTIVE"
    SETTLEMENT_PENDING = "SETTLEMENT_PENDING"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"
    REOPENED = "REOPENED"


class MatterType(str, Enum):
    COMMERCIAL = "COMMERCIAL"
    EMPLOYMENT = "EMPLOYMENT"
    IP = "IP"
    REGULATORY = "REGULATORY"
    PRODUCT_LIABILITY = "PRODUCT_LIABILITY"
    CLASS_ACTION = "CLASS_ACTION"


class ExposureTier(str, Enum):
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"
    TIER_4 = "TIER_4"


class Posture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class ResolutionType(str, Enum):
    SETTLEMENT = "SETTLEMENT"
    JUDGMENT = "JUDGMENT"
    DISMISSAL = "DISMISSAL"
    SUMMARY_JUDGMENT = "SUMMARY_JUDGMENT"


class JobFamily(str, Enum):
    LEGAL = "LEGAL"
    FINANCE = "FINANCE"
    OPERATIONS = "OPERATIONS"
    EXECUTIVE = "EXECUTIVE"


class PanelStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class ConflictCheckStatus(str, Enum):
    UNCHECKED = "UNCHECKED"
    CLEARED = "CLEARED"
    WAIVED = "WAIVED"
    FLAGGED = "FLAGGED"


class EngagementRoleType(str, Enum):
    LEAD_COUNSEL = "LEAD_COUNSEL"
    CO_COUNSEL = "CO_COUNSEL"
    LOCAL_COUNSEL = "LOCAL_COUNSEL"
    SPECIALIST = "SPECIALIST"


class EngagementStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class FeeArrangement(str, Enum):
    HOURLY = "HOURLY"
    FLAT_FEE = "FLAT_FEE"
    CONTINGENCY = "CONTINGENCY"
    HYBRID = "HYBRID"


class BudgetStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    SUPERSEDED = "SUPERSEDED"
    REJECTED = "REJECTED"


class AccrualEntryStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    POSTED = "POSTED"
    VOID = "VOID"


class EntryKind(str, Enum):
    ACCRUAL = "ACCRUAL"
    INVOICE = "INVOICE"
    ADJUSTMENT = "ADJUSTMENT"


class HoldStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RELEASED = "RELEASED"


class CustodianStatus(str, Enum):
    NOTICED = "NOTICED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    ESCALATED = "ESCALATED"
    EXEMPTED = "EXEMPTED"
    RELEASED = "RELEASED"


class ReleaseReason(str, Enum):
    MATTER_RESOLVED = "MATTER_RESOLVED"
    SCOPE_NARROWED = "SCOPE_NARROWED"
    COURT_ORDER = "COURT_ORDER"
    ERROR = "ERROR"


class ClearanceLevel(str, Enum):
    STANDARD = "STANDARD"
    ENHANCED = "ENHANCED"
    RESTRICTED = "RESTRICTED"


class ServiceType(str, Enum):
    COLLECTION = "COLLECTION"
    PROCESSING = "PROCESSING"
    HOSTING = "HOSTING"
    REVIEW = "REVIEW"
    PRODUCTION = "PRODUCTION"


class WorkOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    AUTHORIZED = "AUTHORIZED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class DeadlineType(str, Enum):
    COURT_DEADLINE = "COURT_DEADLINE"
    HEARING = "HEARING"
    DISCOVERY_CUTOFF = "DISCOVERY_CUTOFF"
    FILING = "FILING"
    INTERNAL_REVIEW = "INTERNAL_REVIEW"
    LIMITATION_EXPIRY = "LIMITATION_EXPIRY"


class DeadlineStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    MET = "MET"
    MISSED = "MISSED"
    VACATED = "VACATED"
    EXPIRED = "EXPIRED"


class ApproverRole(str, Enum):
    DEPUTY_GENERAL_COUNSEL = "DeputyGeneralCounsel"
    GENERAL_COUNSEL = "GeneralCounsel"
    CHIEF_FINANCIAL_OFFICER = "ChiefFinancialOfficer"
    BOARD_COMMITTEE = "BoardCommittee"


class SettlementKind(str, Enum):
    PAY_OUT = "PAY_OUT"
    PAY_IN = "PAY_IN"
    NON_MONETARY = "NON_MONETARY"


class SettlementStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    COUNTERED = "COUNTERED"
    EXECUTED = "EXECUTED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"


class PaymentKind(str, Enum):
    SETTLEMENT = "SETTLEMENT"
    JUDGMENT = "JUDGMENT"
    COST_AWARD = "COST_AWARD"


class PaymentStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    FINANCE_APPROVED = "FINANCE_APPROVED"
    DISBURSED = "DISBURSED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class PaymentRail(str, Enum):
    NOT_SENT = "NOT_SENT"
    SENT = "SENT"
    CONFIRMED = "CONFIRMED"
    RETURNED = "RETURNED"


class Matter(TypedDict, total=False):
    id: str
    matter_number: str
    title: str
    matter_type: str
    adverse_party: str
    jurisdiction: str
    filing_date: str
    status: str
    exposure_low_cents: Optional[int]
    exposure_high_cents: Optional[int]
    probability_of_loss_pct: Optional[int]
    exposure_tier: Optional[str]
    reserve_amount_cents: Optional[int]
    accrued_to_date_cents: int
    posture: str
    resolution_type: Optional[str]
    resolved_at: Optional[str]
    owning_counsel_id: str
    close_checklist_ack: bool
    created_at: str
    updated_at: str
    version: int


class StaffUser(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    job_family: str
    is_active: bool
    created_at: str
    updated_at: str
    version: int


class CounselFirm(TypedDict, total=False):
    id: str
    firm_name: str
    panel_status: str
    conflict_check_status: str
    blended_rate_cap_cents: int
    is_active: bool
    created_at: str
    updated_at: str
    version: int


class Engagement(TypedDict, total=False):
    id: str
    matter_id: str
    firm_id: str
    role_type: str
    status: str
    fee_arrangement: str
    proposed_rate_cents: Optional[int]
    contingency_pct: Optional[int]
    approved_by_user_id: Optional[str]
    engagement_letter_executed: bool
    supersedes_engagement_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Budget(TypedDict, total=False):
    id: str
    matter_id: str
    fiscal_year: int
    lifecycle_budget_cents: int
    fy_budget_cents: int
    status: str
    submitted_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    utilization_pct: float
    prior_version_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AccrualEntry(TypedDict, total=False):
    # Append-only ledger row: id + created_at only; no updated_at, no version.
    id: str
    matter_id: str
    engagement_id: str
    period: str
    entry_kind: str
    amount_cents: int
    status: str
    submitted_at: Optional[str]
    reverses_entry_id: Optional[str]
    created_at: str


class LitigationHold(TypedDict, total=False):
    id: str
    matter_id: str
    scope_description: str
    status: str
    issued_at: Optional[str]
    released_at: Optional[str]
    release_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class HoldCustodian(TypedDict, total=False):
    id: str
    hold_id: str
    staff_user_id: str
    status: str
    noticed_at: str
    acknowledged_at: Optional[str]
    escalation_count: int
    exemption_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DiscoveryVendor(TypedDict, total=False):
    id: str
    vendor_name: str
    security_clearance_level: str
    capacity_gb: int
    committed_gb: int
    is_active: bool
    created_at: str
    updated_at: str
    version: int


class VendorWorkOrder(TypedDict, total=False):
    id: str
    matter_id: str
    vendor_id: str
    hold_id: str
    service_type: str
    status: str
    estimated_gb: int
    actual_gb: Optional[int]
    rate_per_gb_cents: int
    scheduled_start: str
    scheduled_end: str
    estimated_cost_cents: int
    created_at: str
    updated_at: str
    version: int


class Deadline(TypedDict, total=False):
    id: str
    matter_id: str
    deadline_type: str
    title: str
    due_at: str
    status: str
    is_jurisdictional: bool
    completed_at: Optional[str]
    reminder_days: int
    created_at: str
    updated_at: str
    version: int


class SettlementAuthorityPolicy(TypedDict, total=False):
    id: str
    tier: str
    approver_role: str
    max_single_amount_cents: int
    dual_approval_required_over_cents: int
    is_active: bool
    created_at: str
    updated_at: str
    version: int


class SettlementRequest(TypedDict, total=False):
    id: str
    matter_id: str
    proposed_amount_cents: int
    settlement_kind: str
    status: str
    counter_amount_cents: Optional[int]
    requested_by_user_id: Optional[str]
    approved_by_user_ids: List[str]
    authority_tier_at_submission: Optional[str]
    terms_summary: str
    expires_at: str
    created_at: str
    updated_at: str
    version: int


class PaymentRequest(TypedDict, total=False):
    id: str
    matter_id: str
    settlement_request_id: Optional[str]
    payment_kind: str
    amount_cents: int
    payee_name: str
    status: str
    payment_status: str
    submitted_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    disbursed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
