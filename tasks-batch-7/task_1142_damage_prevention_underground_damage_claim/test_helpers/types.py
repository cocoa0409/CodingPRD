"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    INTAKE_COORDINATOR = "IntakeCoordinator"
    DAMAGE_INVESTIGATOR = "DamageInvestigator"
    CLAIMS_ADJUSTER = "ClaimsAdjuster"
    RECOVERY_MANAGER = "RecoveryManager"
    EXCAVATOR = "Excavator"
    LOCATOR = "Locator"


# ---------------------------------------------------------------------------
# Status enums (PRD §3)
# ---------------------------------------------------------------------------
class ProgramStatus(str, Enum):
    GOOD_STANDING = "GOOD_STANDING"
    WATCH = "WATCH"
    PROBATION = "PROBATION"
    SUSPENDED = "SUSPENDED"


class ContractStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class TicketStatus(str, Enum):
    OPEN = "OPEN"
    COMPLETED = "COMPLETED"
    EXPIRED = "EXPIRED"


class ResponseCode(str, Enum):
    MARKED = "MARKED"
    CLEAR = "CLEAR"
    PARTIAL = "PARTIAL"


class AccuracyVerdict(str, Enum):
    UNAUDITED = "UNAUDITED"
    ACCURATE = "ACCURATE"
    INACCURATE = "INACCURATE"


class InvestigationStatus(str, Enum):
    REPORTED = "REPORTED"
    DOCUMENTING = "DOCUMENTING"
    INVESTIGATING = "INVESTIGATING"
    FAULT_PROPOSED = "FAULT_PROPOSED"
    FAULT_FINAL = "FAULT_FINAL"
    CLOSED = "CLOSED"


class RecoveryStatus(str, Enum):
    UNBILLED = "UNBILLED"
    COSTING = "COSTING"
    INVOICED = "INVOICED"
    COLLECTING = "COLLECTING"
    RECOVERED = "RECOVERED"


class FacilityType(str, Enum):
    GAS = "GAS"
    ELECTRIC = "ELECTRIC"
    TELECOM = "TELECOM"
    WATER = "WATER"


class Severity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class EvidenceType(str, Enum):
    PHOTO = "PHOTO"
    MEASUREMENT = "MEASUREMENT"
    WITNESS_STATEMENT = "WITNESS_STATEMENT"
    SKETCH = "SKETCH"


class EventKind(str, Enum):
    TICKET_SUBMITTED = "TICKET_SUBMITTED"
    RESPONSE_SUBMITTED = "RESPONSE_SUBMITTED"
    EVIDENCE_CAPTURED = "EVIDENCE_CAPTURED"
    DAMAGE_OCCURRED = "DAMAGE_OCCURRED"


class EventFlag(str, Enum):
    NONE = "NONE"
    LATE_MARK = "LATE_MARK"
    STALE_MARKS = "STALE_MARKS"
    POST_DAMAGE_MARK = "POST_DAMAGE_MARK"


class RootCauseCode(str, Enum):
    NO_TICKET = "NO_TICKET"
    EXPIRED_TICKET = "EXPIRED_TICKET"
    MISMARK = "MISMARK"
    LOCATE_LATE = "LOCATE_LATE"
    OWNER_ABANDONED = "OWNER_ABANDONED"


class AllocationBasis(str, Enum):
    RULE_DEFAULT = "RULE_DEFAULT"
    ADJUDICATED = "ADJUDICATED"


class AllocationStatus(str, Enum):
    DRAFT = "DRAFT"
    PROPOSED = "PROPOSED"
    CONTESTED = "CONTESTED"
    FINAL = "FINAL"
    SUPERSEDED = "SUPERSEDED"


class PartyType(str, Enum):
    EXCAVATOR = "EXCAVATOR"
    LOCATOR = "LOCATOR"
    FACILITY_OWNER = "FACILITY_OWNER"


class CostCategory(str, Enum):
    LABOR = "LABOR"
    MATERIAL = "MATERIAL"
    EQUIPMENT = "EQUIPMENT"
    RESTORATION = "RESTORATION"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    DISPUTED = "DISPUTED"
    WRITTEN_OFF = "WRITTEN_OFF"


class PaymentStatus(str, Enum):
    APPLIED = "APPLIED"
    REVERSED = "REVERSED"


class DisputeTargetType(str, Enum):
    FAULT_ALLOCATION = "FAULT_ALLOCATION"
    CLAIM_INVOICE = "CLAIM_INVOICE"


class DisputeReason(str, Enum):
    FAULT_SHARE = "FAULT_SHARE"
    AMOUNT = "AMOUNT"
    EVIDENCE = "EVIDENCE"
    OTHER = "OTHER"


class DisputeStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    COUNTERED = "COUNTERED"
    RESOLVED = "RESOLVED"
    ESCALATED = "ESCALATED"
    EXPIRED = "EXPIRED"


class SubrogationStatus(str, Enum):
    DEMANDED = "DEMANDED"
    SETTLED = "SETTLED"
    CLOSED = "CLOSED"


class ReportType(str, Enum):
    INCIDENT = "INCIDENT"
    QUARTERLY_SUMMARY = "QUARTERLY_SUMMARY"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    FILED = "FILED"
    SUPERSEDED = "SUPERSEDED"


class ViolationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    OVERTURNED = "OVERTURNED"


class AssignmentStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    COMPLETED = "COMPLETED"
    EXPIRED = "EXPIRED"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# Entities other than EvidenceItem / TimelineEvent carry id, created_at,
# updated_at, version (PRD §2.4). EvidenceItem and TimelineEvent carry only
# id and created_at.
# ---------------------------------------------------------------------------
class Excavator(TypedDict, total=False):
    id: str
    company_name: str
    contact_email: str
    program_status: str
    offender_points: int
    credit_balance_cents: int
    total_outstanding_cents: int
    created_at: str
    updated_at: str
    version: int


class Locator(TypedDict, total=False):
    id: str
    company_name: str
    contact_email: str
    contract_region: str
    contract_status: str
    performance_score_bp: int
    total_responses: int
    created_at: str
    updated_at: str
    version: int


class LocateTicket(TypedDict, total=False):
    id: str
    excavator_id: str
    dig_site_address: str
    work_start_at: str
    work_end_at: str
    ticket_number: str
    status: str
    renewal_count: int
    created_at: str
    updated_at: str
    version: int


class LocateResponse(TypedDict, total=False):
    id: str
    locate_ticket_id: str
    locator_id: str
    response_code: str
    marks_completed_at: str
    accuracy_verdict: str
    notes: str
    created_at: str
    updated_at: str
    version: int


class DamageCase(TypedDict, total=False):
    id: str
    excavator_id: str
    locate_ticket_id: Optional[str]
    case_number: str
    dig_site_address: str
    facility_type: str
    severity: str
    occurred_at: str
    investigation_status: str
    recovery_status: str
    investigator_user_id: Optional[str]
    subtotal_cents: int
    total_invoiced_cents: int
    total_recovered_cents: int
    evidence_count: int
    reconstruction_flags: List[str]
    created_at: str
    updated_at: str
    version: int


class EvidenceItem(TypedDict, total=False):
    # PRD §2.4: only id + created_at; no updated_at, no version.
    id: str
    damage_case_id: str
    evidence_type: str
    captured_at: str
    description: str
    created_at: str


class TimelineEvent(TypedDict, total=False):
    # PRD §2.4: only id + created_at; no updated_at, no version.
    id: str
    damage_case_id: str
    event_kind: str
    event_at: str
    source_ref_id: str
    flag: str
    created_at: str


class ShareEntry(TypedDict, total=False):
    party_type: str
    party_id: Optional[str]
    share_bp: int


class FaultAllocation(TypedDict, total=False):
    id: str
    damage_case_id: str
    supersedes_allocation_id: Optional[str]
    root_cause_code: str
    basis: str
    shares: List[ShareEntry]
    status: str
    revision_no: int
    proposed_at: Optional[str]
    contest_deadline_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CostLineItem(TypedDict, total=False):
    id: str
    damage_case_id: str
    category: str
    description: str
    quantity: float
    unit_cost_cents: int
    line_total_cents: int
    created_at: str
    updated_at: str
    version: int


class ClaimInvoice(TypedDict, total=False):
    id: str
    damage_case_id: str
    fault_allocation_id: str
    debtor_type: str
    debtor_id: str
    status: str
    invoiced_cents: int
    standard_basis_cents: int
    amount_paid_cents: int
    amount_due_cents: int
    issued_at: Optional[str]
    due_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PaymentAllocationLeg(TypedDict, total=False):
    claim_invoice_id: str
    amount_cents: int


class Payment(TypedDict, total=False):
    id: str
    payer_type: str
    payer_id: str
    amount_cents: int
    claim_invoice_id: Optional[str]
    status: str
    allocations: List[PaymentAllocationLeg]
    applied_at: str
    created_at: str
    updated_at: str
    version: int


class Dispute(TypedDict, total=False):
    id: str
    target_type: str
    target_id: str
    reason: str
    detail: str
    filed_by_type: str
    filed_by_id: str
    status: str
    rounds: int
    response_deadline_at: str
    created_at: str
    updated_at: str
    version: int


class SubrogationCase(TypedDict, total=False):
    id: str
    dispute_id: str
    claim_invoice_id: Optional[str]
    target_party_type: str
    target_party_id: str
    status: str
    demand_amount_cents: int
    recovered_cents: int
    legal_cost_cents: int
    owner_share_cents: int
    created_at: str
    updated_at: str
    version: int


class RegulatoryReport(TypedDict, total=False):
    id: str
    damage_case_id: Optional[str]
    report_type: str
    period_start: Optional[str]
    period_end: Optional[str]
    payload_notes: str
    amends_report_id: Optional[str]
    status: str
    filed_at: Optional[str]
    days_late: int
    penalty_cents: int
    created_at: str
    updated_at: str
    version: int


class ViolationRecord(TypedDict, total=False):
    id: str
    excavator_id: str
    damage_case_id: str
    points: int
    effective_points: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TrainingCourse(TypedDict, total=False):
    id: str
    course_code: str
    title: str
    required_for_status: str
    credit_hours: int
    created_at: str
    updated_at: str
    version: int


class TrainingAssignment(TypedDict, total=False):
    id: str
    excavator_id: str
    course_id: str
    status: str
    due_at: str
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
