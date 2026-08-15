"""Domain types: entity TypedDicts, status enums, role enum (PRD §2 and §3).

Every entity in the system shares four system-managed properties per PRD §2.4:
`id` (server-minted UUID), `created_at` / `updated_at` (ISO 8601 timestamps),
and `version` (integer, incremented on every mutation).
"""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    COOP_ADMIN = "CoopAdmin"
    MEMBER_REP = "MemberRep"
    SUPPLIER_REP = "SupplierRep"
    FINANCE_OFFICER = "FinanceOfficer"
    PROGRAM_AUDITOR = "ProgramAuditor"


class MemberStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CHURNED = "CHURNED"


class CommitmentLevel(str, Enum):
    BUILDER = "BUILDER"
    STANDARD = "STANDARD"
    PLATINUM = "PLATINUM"


class SupplierStatus(str, Enum):
    PROSPECT = "PROSPECT"
    ONBOARDED = "ONBOARDED"
    INACTIVE = "INACTIVE"


class SupplierProgramStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    CLOSED_TO_NEW = "CLOSED_TO_NEW"
    REOPENED = "REOPENED"
    TERMINATED = "TERMINATED"


class HoldbackPolicy(str, Enum):
    FLAT = "FLAT"
    RISK_ADJUSTED = "RISK_ADJUSTED"


class EnrollmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXITED = "EXITED"


class ExclusivityStatus(str, Enum):
    COMPLIANT = "COMPLIANT"
    SHORTFALL = "SHORTFALL"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class PurchaseReportStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    FLAGGED = "FLAGGED"
    SUPERSEDED = "SUPERSEDED"
    ADJUDICATED = "ADJUDICATED"


class VolumeAuditStatus(str, Enum):
    OPEN = "OPEN"
    FIELDWORK = "FIELDWORK"
    FINDINGS_ISSUED = "FINDINGS_ISSUED"
    ACCEPTED = "ACCEPTED"
    APPEALED = "APPEALED"
    RESOLVED = "RESOLVED"


class FindingSeverity(str, Enum):
    NONE = "NONE"
    MINOR = "MINOR"
    MATERIAL = "MATERIAL"


class RebateAccrualStatus(str, Enum):
    OPEN = "OPEN"
    FINALIZED = "FINALIZED"
    DISTRIBUTED = "DISTRIBUTED"
    CLAWED_BACK = "CLAWED_BACK"


class DistributionStatus(str, Enum):
    DRAFT = "DRAFT"
    CALCULATED = "CALCULATED"
    APPROVED = "APPROVED"
    DISBURSED = "DISBURSED"
    RECONCILED = "RECONCILED"


class ClawbackTriggerReason(str, Enum):
    CHURN = "CHURN"
    AUDIT_SHORTFALL = "AUDIT_SHORTFALL"
    EXCLUSIVITY_BREACH = "EXCLUSIVITY_BREACH"


class ClawbackCaseStatus(str, Enum):
    OPEN = "OPEN"
    NOTIFIED = "NOTIFIED"
    DISPUTED = "DISPUTED"
    RESOLVED = "RESOLVED"
    WAIVED = "WAIVED"


class HoldbackReleaseStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    RELEASED = "RELEASED"
    FORFEITED = "FORFEITED"


class Tier(TypedDict):
    min_qty: int
    rate_bps: int


class Coop(TypedDict):
    id: str
    name: str
    current_quarter_index: int
    pool_reserve_cents: int
    retained_revenue_cents: int
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict):
    id: str
    legal_name: str
    commitment_level: str
    status: str
    enrolled_quarter_index: int
    churn_quarter_index: Optional[int]
    lifetime_pass_through_cents: int
    lifetime_clawback_cents: int
    prior_audit_findings_count: int
    created_at: str
    updated_at: str
    version: int


class Supplier(TypedDict):
    id: str
    legal_name: str
    onboarding_notes: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SupplierProgram(TypedDict):
    id: str
    supplier_id: str
    program_code: str
    exclusivity_required: bool
    exclusivity_threshold_pct: int
    tier_schedule: List[Tier]
    holdback_policy: str
    negotiation_round: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ProgramEnrollment(TypedDict):
    id: str
    member_id: str
    program_id: str
    enrolled_quarter_index: int
    exit_quarter_index: Optional[int]
    status: str
    exclusivity_share_pct: int
    exclusivity_status: str
    created_at: str
    updated_at: str
    version: int


class PurchaseReport(TypedDict):
    id: str
    enrollment_id: str
    quarter_index: int
    self_report_qty: int
    self_report_cents: int
    audited_qty: Optional[int]
    audited_cents: Optional[int]
    revision_of_id: Optional[str]
    status: str
    submitted_at_quarter: int
    created_at: str
    updated_at: str
    version: int


class VolumeAudit(TypedDict):
    id: str
    enrollment_id: str
    purchase_report_id: str
    opened_quarter_index: int
    resolved_quarter_index: Optional[int]
    finding_severity: Optional[str]
    audited_qty: Optional[int]
    audited_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class RebateAccrual(TypedDict):
    id: str
    enrollment_id: str
    quarter_index: int
    provisional_rebate_cents: int
    final_rebate_cents: int
    tier_applied_min_qty: int
    pass_through_cents: int
    retained_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class QuarterlyDistribution(TypedDict):
    id: str
    coop_id: str
    quarter_index: int
    gross_rebate_cents: int
    total_pass_through_cents: int
    total_retained_cents: int
    holdback_cents: int
    clawback_offset_cents: int
    net_disbursed_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ClawbackCase(TypedDict):
    id: str
    member_id: str
    trigger_reason: str
    trigger_quarter_index: int
    gross_clawback_cents: int
    net_clawback_cents: int
    recovered_cents: int
    dispute_note: str
    status: str
    created_at: str
    updated_at: str
    version: int


class HoldbackRelease(TypedDict):
    id: str
    member_id: str
    source_distribution_id: str
    release_quarter_index: int
    release_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
