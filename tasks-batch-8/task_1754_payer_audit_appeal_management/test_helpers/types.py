"""Domain types: entity TypedDicts, status enums, role enum.

All field names follow the PRD exactly. Every primary resource carries the
standard system-managed fields id + created_at + updated_at + version;
AuditCaseEvent is the single append-only exception and carries only id +
created_at (PRD section on common resource properties).
"""
from enum import Enum
from typing import List, Optional, TypedDict


class PayerType(str, Enum):
    RAC = "RAC"
    COMMERCIAL = "COMMERCIAL"


class AppealTrack(str, Enum):
    MEDICARE = "MEDICARE"
    COMMERCIAL = "COMMERCIAL"


class PayerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class IssueCategory(str, Enum):
    CLINICAL = "CLINICAL"
    TECHNICAL = "TECHNICAL"


class AuditType(str, Enum):
    RAC_COMPLEX = "RAC_COMPLEX"
    RAC_AUTOMATED = "RAC_AUTOMATED"
    COMMERCIAL_POSTPAY = "COMMERCIAL_POSTPAY"
    COMMERCIAL_PREPAY = "COMMERCIAL_PREPAY"
    TARGETED_PROBE = "TARGETED_PROBE"


class AuditCaseStatus(str, Enum):
    RECEIVED = "RECEIVED"
    RECORDS_SUBMITTED = "RECORDS_SUBMITTED"
    UNDER_PAYER_REVIEW = "UNDER_PAYER_REVIEW"
    DETERMINATION_ISSUED = "DETERMINATION_ISSUED"
    MISSED_DEADLINE = "MISSED_DEADLINE"
    CLOSED = "CLOSED"


class ClaimLineStatus(str, Enum):
    UNDER_AUDIT = "UNDER_AUDIT"
    PAID_AS_BILLED = "PAID_AS_BILLED"
    DENIED = "DENIED"
    PARTIALLY_DENIED = "PARTIALLY_DENIED"
    OVERTURNED = "OVERTURNED"
    FINAL = "FINAL"


class AppealLevel(str, Enum):
    LEVEL_1 = "LEVEL_1"
    LEVEL_2 = "LEVEL_2"
    LEVEL_3 = "LEVEL_3"
    LEVEL_4 = "LEVEL_4"
    LEVEL_5 = "LEVEL_5"


class AppealStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_DECISION = "PENDING_DECISION"
    DECIDED_FAVORABLE = "DECIDED_FAVORABLE"
    DECIDED_PARTIAL = "DECIDED_PARTIAL"
    DECIDED_UNFAVORABLE = "DECIDED_UNFAVORABLE"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"


class DecisionOutcome(str, Enum):
    FAVORABLE = "FAVORABLE"
    PARTIAL = "PARTIAL"
    UNFAVORABLE = "UNFAVORABLE"


class PacketStatus(str, Enum):
    ASSEMBLING = "ASSEMBLING"
    READY = "READY"
    SUBMITTED = "SUBMITTED"


class PacketItemType(str, Enum):
    MEDICAL_RECORD = "MEDICAL_RECORD"
    PHYSICIAN_LETTER = "PHYSICIAN_LETTER"
    POLICY_CITATION = "POLICY_CITATION"
    EXPERT_REVIEW = "EXPERT_REVIEW"
    PRIOR_AUTH_DOC = "PRIOR_AUTH_DOC"


class PacketItemStatus(str, Enum):
    PENDING = "PENDING"
    ATTACHED = "ATTACHED"
    WAIVED = "WAIVED"


class DemandStatus(str, Enum):
    DEMANDED = "DEMANDED"
    ON_HOLD = "ON_HOLD"
    PARTIALLY_RECOUPED = "PARTIALLY_RECOUPED"
    FULLY_RECOUPED = "FULLY_RECOUPED"
    REVERSED = "REVERSED"
    WRITTEN_OFF = "WRITTEN_OFF"


class RemittanceStatus(str, Enum):
    RECEIVED = "RECEIVED"
    PARTIALLY_ALLOCATED = "PARTIALLY_ALLOCATED"
    FULLY_ALLOCATED = "FULLY_ALLOCATED"


class AllocationMode(str, Enum):
    AUTO_WATERFALL = "AUTO_WATERFALL"
    MANUAL = "MANUAL"


class OffsetStatus(str, Enum):
    APPLIED = "APPLIED"
    REVERSED = "REVERSED"


class CapStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACTIVE = "ACTIVE"
    EFFECTIVENESS_CHECK = "EFFECTIVENESS_CHECK"
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"


class CaseEventType(str, Enum):
    CASE_CREATED = "CASE_CREATED"
    RECORDS_SUBMITTED = "RECORDS_SUBMITTED"
    REVIEW_BEGAN = "REVIEW_BEGAN"
    DETERMINATION_ISSUED = "DETERMINATION_ISSUED"
    CASE_MISSED_DEADLINE = "CASE_MISSED_DEADLINE"
    LINES_AUTO_DENIED = "LINES_AUTO_DENIED"
    DEMAND_CREATED = "DEMAND_CREATED"
    OFFSET_APPLIED = "OFFSET_APPLIED"
    OFFSET_REVERSED = "OFFSET_REVERSED"
    CASE_CLOSED = "CASE_CLOSED"


class UserRole(str, Enum):
    REVENUE_CYCLE_ADMIN = "RevenueCycleAdmin"
    HIM_COORDINATOR = "HIMCoordinator"
    APPEALS_SPECIALIST = "AppealsSpecialist"
    DEPARTMENT_DIRECTOR = "DepartmentDirector"
    PFS_ACCOUNTANT = "PFSAccountant"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    INTERNAL_AUDITOR = "InternalAuditor"
    PAYER_AGENT = "PayerAgent"


class Payer(TypedDict, total=False):
    id: str
    name: str
    payer_type: str
    appeal_track: str
    records_submission_days: int
    l1_deadline_days: int
    l2_deadline_days: int
    l3_deadline_days: int
    l4_deadline_days: int
    l5_deadline_days: int
    external_review_deadline_days: int
    concurrent_audit_cap: int
    hold_levels: List[str]
    interest_rate_bps_tier1: int
    interest_rate_bps_tier2: int
    interest_cap_pct: int
    status: str
    created_at: str
    updated_at: str
    version: int


class IssueCode(TypedDict, total=False):
    id: str
    code: str
    category: str
    description: str
    active: bool
    created_at: str
    updated_at: str
    version: int


class AuditCase(TypedDict, total=False):
    id: str
    payer_id: str
    audit_type: str
    received_at: str
    external_audit_ref: Optional[str]
    status: str
    records_due_at: str
    records_submitted_at: Optional[str]
    late_submission: bool
    determination_issued_at: Optional[str]
    total_billed_cents: int
    total_upheld_cents: int
    total_denied_active_cents: int
    total_overturned_cents: int
    total_final_denied_cents: int
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AuditClaimLine(TypedDict, total=False):
    id: str
    audit_case_id: str
    claim_number: str
    patient_account_number: str
    service_start_date: str
    service_end_date: str
    billed_amount_cents: int
    status: str
    denied_amount_cents: int
    denial_category: Optional[str]
    issue_code_id: Optional[str]
    auto_denied: bool
    created_at: str
    updated_at: str
    version: int


class Appeal(TypedDict, total=False):
    id: str
    audit_claim_line_id: str
    audit_case_id: str
    prior_appeal_id: Optional[str]
    level: str
    level_label: str
    filed_deadline_at: str
    appealed_denied_cents: int
    status: str
    filed_at: Optional[str]
    decided_at: Optional[str]
    upheld_cents: Optional[int]
    notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EvidencePacket(TypedDict, total=False):
    id: str
    appeal_id: str
    status: str
    submitted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PacketItem(TypedDict, total=False):
    id: str
    evidence_packet_id: str
    item_type: str
    required: bool
    status: str
    document_ref: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RecoupmentDemand(TypedDict, total=False):
    id: str
    audit_case_id: str
    payer_id: str
    principal_cents: int
    issued_at: str
    status: str
    outstanding_principal_cents: int
    accrued_interest_cents: int
    written_off_cents: int
    hold_started_at: Optional[str]
    accumulated_hold_seconds: int
    rate_bps_tier1_snapshot: int
    rate_bps_tier2_snapshot: int
    interest_cap_pct_snapshot: int
    created_at: str
    updated_at: str
    version: int


class Remittance(TypedDict, total=False):
    id: str
    payer_id: str
    gross_amount_cents: int
    external_ref: Optional[str]
    available_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class OffsetTransaction(TypedDict, total=False):
    id: str
    remittance_id: str
    recoupment_demand_id: str
    amount_cents: int
    interest_portion_cents: int
    principal_portion_cents: int
    allocation_mode: str
    status: str
    applied_at: str
    reversed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CorrectiveActionPlan(TypedDict, total=False):
    id: str
    payer_id: str
    issue_code_id: str
    title: str
    root_cause: str
    status: str
    proposed_by_user_id: str
    verified_by_user_id: Optional[str]
    check_started_at: Optional[str]
    cycle_count: int
    created_at: str
    updated_at: str
    version: int


class AuditCaseEvent(TypedDict, total=False):
    """Append-only event entry: id + created_at only, NO updated_at/version."""
    id: str
    audit_case_id: str
    event_type: str
    actor_role: str
    actor_user_id: str
    payload: dict
    occurred_at: str
    created_at: str
