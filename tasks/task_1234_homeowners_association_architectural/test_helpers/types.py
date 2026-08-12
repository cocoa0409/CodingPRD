"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    MANAGER = "Manager"
    HOMEOWNER = "Homeowner"
    COMMITTEE_MEMBER = "CommitteeMember"
    BOARD_MEMBER = "BoardMember"
    INSPECTOR = "Inspector"


class CountingMode(str, Enum):
    CALENDAR = "CALENDAR"
    BUSINESS = "BUSINESS"


class FineMode(str, Enum):
    SIMPLE_DAILY = "SIMPLE_DAILY"
    TIERED_ESCALATION = "TIERED_ESCALATION"


class ProjectType(str, Enum):
    ADDITION = "ADDITION"
    FENCE = "FENCE"
    PAINT = "PAINT"
    ROOF = "ROOF"
    SOLAR = "SOLAR"
    OTHER = "OTHER"


class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    APPROVED_WITH_CONDITIONS = "APPROVED_WITH_CONDITIONS"
    DENIED = "DENIED"
    DEEMED_APPROVED = "DEEMED_APPROVED"
    UNDER_APPEAL = "UNDER_APPEAL"
    APPEAL_DENIED = "APPEAL_DENIED"


class DecisionOutcome(str, Enum):
    NONE = "NONE"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class AttachmentKind(str, Enum):
    DRAWING = "DRAWING"
    MATERIAL_SAMPLE = "MATERIAL_SAMPLE"


class Ballot(str, Enum):
    APPROVE = "APPROVE"
    DENY = "DENY"
    ABSTAIN = "ABSTAIN"


class AppealStatus(str, Enum):
    PENDING = "PENDING"
    UPHELD = "UPHELD"
    OVERRULED = "OVERRULED"


class AppealOutcome(str, Enum):
    UPHELD = "UPHELD"
    OVERRULED = "OVERRULED"


class PermitStatus(str, Enum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    EXPIRED = "EXPIRED"


class InspectionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PASSED = "PASSED"
    FAILED_REMEDIATION = "FAILED_REMEDIATION"


class InspectionResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class ViolationKind(str, Enum):
    UNAPPROVED_WORK = "UNAPPROVED_WORK"
    CONDITION_BREACH = "CONDITION_BREACH"
    INCOMPLETE_CONSTRUCTION = "INCOMPLETE_CONSTRUCTION"


class ViolationStatus(str, Enum):
    OPEN = "OPEN"
    ESCALATED = "ESCALATED"
    REMEDIATED = "REMEDIATED"


class FineStatus(str, Enum):
    ACCRUING = "ACCRUING"
    STOPPED = "STOPPED"
    SETTLED = "SETTLED"


class LienStatus(str, Enum):
    FILED = "FILED"
    SATISFIED = "SATISFIED"


class CompliancePosture(str, Enum):
    CLEAR = "CLEAR"
    FINES_OUTSTANDING = "FINES_OUTSTANDING"
    LIENED = "LIENED"


# All entities carry the common system fields of PRD §2.4:
# id, created_at, updated_at, version. TypedDicts are total=False so that
# system-stamped fields absent before their stamping event (submitted_at,
# decided_at, ...) do not make the type lie.


class Association(TypedDict, total=False):
    id: str
    name: str
    statutory_response_days: int
    counting_mode: str
    fine_mode: str
    base_fine_cents: int
    daily_fine_cents: int
    grace_days: int
    escalation_multiplier_bp: int
    lien_threshold_cents: int
    lien_min_age_days: int
    committee_size: int
    quorum_min: int
    supermajority_required: bool
    max_window_days: int
    default_window_days: int
    remediation_days: int
    appeal_window_days: int
    created_at: str
    updated_at: str
    version: int


class Owner(TypedDict, total=False):
    id: str
    association_id: str
    full_name: str
    email: str
    created_at: str
    updated_at: str
    version: int


class Property(TypedDict, total=False):
    id: str
    association_id: str
    primary_owner_id: str
    lot_number: str
    address: str
    outstanding_fine_balance_cents: int
    open_permit_count: int
    compliance_posture: str
    created_at: str
    updated_at: str
    version: int


class Application(TypedDict, total=False):
    id: str
    property_id: str
    owner_id: str
    project_type: str
    guideline_section: str
    description: str
    requested_window_start: str
    requested_window_end: str
    status: str
    submitted_at: str
    review_started_at: str
    applicant_hold_days: int
    decision_outcome: str
    decision_reason: str
    conditions: List[str]
    decided_at: str
    created_at: str
    updated_at: str
    version: int


class Attachment(TypedDict, total=False):
    id: str
    application_id: str
    kind: str
    label: str
    uri: str
    created_at: str
    updated_at: str
    version: int


class CommitteeVote(TypedDict, total=False):
    id: str
    application_id: str
    voter_owner_id: str
    ballot: str
    cast_at: str
    recast_count: int
    created_at: str
    updated_at: str
    version: int


class Appeal(TypedDict, total=False):
    id: str
    application_id: str
    grounds: str
    status: str
    board_note: str
    decided_by_owner_id: str
    filed_at: str
    decided_at: str
    created_at: str
    updated_at: str
    version: int


class ConstructionPermit(TypedDict, total=False):
    id: str
    application_id: str
    window_start: str
    window_end: str
    contractor_name: str
    contractor_license: str
    status: str
    completed_at: str
    created_at: str
    updated_at: str
    version: int


class BlackoutPeriod(TypedDict, total=False):
    id: str
    association_id: str
    start_date: str
    end_date: str
    reason: str
    created_at: str
    updated_at: str
    version: int


class Inspection(TypedDict, total=False):
    id: str
    permit_id: str
    attempt_no: int
    status: str
    result_notes: str
    scheduled_at: str
    recorded_at: str
    created_at: str
    updated_at: str
    version: int


class Violation(TypedDict, total=False):
    id: str
    property_id: str
    application_id: str
    source_inspection_id: str
    source_permit_id: str
    kind: str
    description: str
    status: str
    remediation_deadline: str
    escalated_at: str
    remediated_at: str
    created_at: str
    updated_at: str
    version: int


class Fine(TypedDict, total=False):
    id: str
    violation_id: str
    mode_snapshot: str
    base_cents: int
    daily_rate_cents: int
    grace_days_snapshot: int
    escalation_multiplier_bp_snapshot: int
    accrued_cents: int
    accrued_through_date: str
    settled_cents: int
    waived_cents: int
    outstanding_cents: int
    status: str
    started_at: str
    stopped_at: str
    settled_at: str
    created_at: str
    updated_at: str
    version: int


class Lien(TypedDict, total=False):
    id: str
    property_id: str
    amount_at_filing_cents: int
    filed_at: str
    status: str
    satisfied_at: str
    created_at: str
    updated_at: str
    version: int


class Variance(TypedDict, total=False):
    id: str
    association_id: str
    application_id: str
    guideline_section: str
    deviation_description: str
    recorded_at: str
    created_at: str
    updated_at: str
    version: int
