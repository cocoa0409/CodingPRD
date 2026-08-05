"""Domain types: entity TypedDicts, status enums, role enum.

All types reflect the Cable-Broadband Franchise & PEG API contract. Every
entity carries the common resource properties id, created_at, updated_at,
and version (see PRD 2.4).
"""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    FRANCHISE_AUTHORITY = "FranchiseAuthority"
    OPERATOR = "Operator"
    RESIDENT = "Resident"


# ----- Franchise status axes -----
class FranchiseLifecycleStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RENEWAL_PENDING = "RENEWAL_PENDING"
    RENEWED = "RENEWED"
    TRANSFERRED = "TRANSFERRED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class FranchiseComplianceStatus(str, Enum):
    COMPLIANT = "COMPLIANT"
    IN_VIOLATION = "IN_VIOLATION"
    CURED = "CURED"


class RowPermitStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class BuildoutMilestoneStatus(str, Enum):
    PENDING = "PENDING"
    MET = "MET"
    MISSED = "MISSED"


class RevenueReportStatus(str, Enum):
    FILED = "FILED"
    ACCEPTED = "ACCEPTED"
    UNDER_AUDIT = "UNDER_AUDIT"
    ADJUSTED = "ADJUSTED"
    PAID = "PAID"


class FeeBasis(str, Enum):
    AS_FILED = "AS_FILED"
    AS_AUDITED = "AS_AUDITED"


class AuditStatus(str, Enum):
    OPEN = "OPEN"
    COMPLETED_CLEAN = "COMPLETED_CLEAN"
    COMPLETED_FINDING = "COMPLETED_FINDING"


class AssessmentStatus(str, Enum):
    ISSUED = "ISSUED"
    DISPUTED = "DISPUTED"
    PAID = "PAID"
    WAIVED = "WAIVED"


class ComplaintCategory(str, Enum):
    SERVICE_INTERRUPTION = "SERVICE_INTERRUPTION"
    BILLING = "BILLING"
    OTHER = "OTHER"


class ComplaintStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    REOPENED = "REOPENED"
    ESCALATED = "ESCALATED"
    CLOSED = "CLOSED"


class PegContributionType(str, Enum):
    CAPITAL_GRANT = "CAPITAL_GRANT"
    INET = "INET"


class PegContributionStatus(str, Enum):
    RECORDED = "RECORDED"
    VOIDED = "VOIDED"


class ApplicationType(str, Enum):
    TRANSFER = "TRANSFER"
    RENEWAL = "RENEWAL"


class ApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    HELD = "HELD"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    DEEMED_APPROVED = "DEEMED_APPROVED"
    WITHDRAWN = "WITHDRAWN"


class ApplicationDecision(str, Enum):
    APPROVE = "APPROVE"
    DENY = "DENY"


# ----- Entity TypedDicts (all entities carry id/created_at/updated_at/version) -----
class Franchise(TypedDict):
    id: str
    operator_name: str
    territory_name: str
    homes_in_territory: int
    road_miles: float
    fee_rate_pct: float
    peg_fee_per_sub_cents: int
    term_start_date: str
    term_end_date: str
    lifecycle_status: str
    compliance_status: str
    unresolved_complaint_count: int
    homes_passed: int
    total_owed_cents: int
    peg_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class RowSegment(TypedDict):
    id: str
    name: str
    length_miles: float
    homes_along: int
    jurisdiction: str
    created_at: str
    updated_at: str
    version: int


class RowPermit(TypedDict):
    id: str
    franchise_id: str
    row_segment_id: str
    window_start: str
    window_end: str
    purpose: str
    status: str
    decided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BuildoutMilestone(TypedDict):
    id: str
    franchise_id: str
    label: str
    deadline_date: str
    required_pct: float
    required_homes: int
    homes_passed_certified: int
    status: str
    provisional_damage_cents: int
    final_damage_cents: int
    last_certified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RevenueReport(TypedDict):
    id: str
    franchise_id: str
    period_start_date: str
    period_end_date: str
    residential_gross_cents: int
    commercial_gross_cents: int
    advertising_gross_cents: int
    fee_due_cents: int
    amount_paid_cents: int
    status: str
    fee_basis: str
    created_at: str
    updated_at: str
    version: int


class Audit(TypedDict):
    id: str
    franchise_id: str
    target_report_id: str
    period_start_date: str
    period_end_date: str
    audited_gross_residential_cents: Optional[int]
    audited_gross_commercial_cents: Optional[int]
    audited_gross_advertising_cents: Optional[int]
    status: str
    finalized_by_user_id: Optional[str]
    finalized_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Assessment(TypedDict):
    id: str
    audit_id: str
    principal_cents: int
    interest_cents: int
    penalty_cents: int
    total_cents: int
    days_late: int
    underpayment_pct: float
    status: str
    issued_by_user_id: str
    amount_paid_cents: int
    created_at: str
    updated_at: str
    version: int


class Complaint(TypedDict):
    id: str
    franchise_id: str
    complainant_id: str
    category: str
    description: str
    filed_at: str
    sla_deadline: str
    status: str
    escalated_at: Optional[str]
    resolution_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PegContribution(TypedDict):
    id: str
    franchise_id: str
    amount_cents: int
    contribution_type: str
    status: str
    voided_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FranchiseApplication(TypedDict):
    id: str
    franchise_id: str
    application_type: str
    transferee_name: Optional[str]
    proposed_term_end_date: Optional[str]
    submitted_at: str
    decision_deadline: str
    status: str
    decided_by_user_id: Optional[str]
    decision: Optional[str]
    created_at: str
    updated_at: str
    version: int
