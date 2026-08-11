"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.5, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    RESILIENCE_ADMIN = "ResilienceAdmin"
    BIA_ANALYST = "BIAAnalyst"
    PLAN_AUTHOR = "PlanAuthor"
    PLAN_APPROVER = "PlanApprover"
    RISK_COMMITTEE = "RiskCommittee"
    EXERCISE_OFFICER = "ExerciseOfficer"
    SITE_COORDINATOR = "SiteCoordinator"
    VENDOR_MANAGER = "VendorManager"
    CRISIS_OFFICER = "CrisisOfficer"
    ATTESTATION_SIGNER = "AttestationSigner"


class ProcessStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    RETIRED = "RETIRED"


class BiaStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    RETIRED = "RETIRED"


class ThirdPartyStatus(str, Enum):
    ONBOARDING = "ONBOARDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXITED = "EXITED"


class AssessmentStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"


class AlternateSiteStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class SiteReservationStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    RELEASED = "RELEASED"


class ExerciseStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class FindingStatus(str, Enum):
    OPEN = "OPEN"
    REMEDIATING = "REMEDIATING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class CapabilityStatus(str, Enum):
    UNPROVEN = "UNPROVEN"
    VALIDATED = "VALIDATED"
    GAP_IDENTIFIED = "GAP_IDENTIFIED"
    REMEDIATED = "REMEDIATED"


class ValidationRunStatus(str, Enum):
    RECORDED = "RECORDED"
    SUPERSEDED = "SUPERSEDED"


class GapStatus(str, Enum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    CLOSED = "CLOSED"
    ACCEPTED_RISK = "ACCEPTED_RISK"


class ActivationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ALL_NOTIFIED = "ALL_NOTIFIED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    DEACTIVATED = "DEACTIVATED"


class NotificationStatus(str, Enum):
    SENT = "SENT"
    ACKED = "ACKED"


class AttestationStatus(str, Enum):
    DRAFT = "DRAFT"
    SIGNED = "SIGNED"
    REVOKED = "REVOKED"


class ScoreVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class ValidationFreshness(str, Enum):
    CURRENT = "CURRENT"
    STALE = "STALE"
    NEVER = "NEVER"


# --- Entity TypedDicts -------------------------------------------------------
# Standard entities carry id + created_at + updated_at + version (PRD §2.5).


class Contact(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    role_title: str
    active_flag: bool
    created_at: str
    updated_at: str
    version: int


class Process(TypedDict, total=False):
    id: str
    name: str
    business_unit: str
    owner_contact_id: str
    criticality_tier: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Bia(TypedDict, total=False):
    id: str
    process_id: str
    cycle_label: str
    rto_target_hours: int
    rpo_target_hours: int
    mtpd_hours: int
    peak_period_flag: bool
    peak_start_month: Optional[int]
    peak_end_month: Optional[int]
    impact_financial_per_hour: float
    impact_regulatory: str
    impact_reputational: str
    impact_operational: str
    criticality_score: float
    score_variant: str
    decided_by_contact_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Plan(TypedDict, total=False):
    id: str
    process_id: str
    title: str
    version_no: int
    strategy_type: str
    rto_committed_hours: int
    rpo_committed_hours: int
    target_bia_id: Optional[str]
    approved_version_no: Optional[int]
    supersedes_plan_id: Optional[str]
    last_adoption_check_cycle: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PlanSection(TypedDict, total=False):
    id: str
    plan_id: str
    section_type: str
    content: str
    order_index: int
    required_flag: bool
    created_at: str
    updated_at: str
    version: int


class Dependency(TypedDict, total=False):
    # Append-only edge: carries ONLY id + created_at (no updated_at, no version).
    id: str
    from_process_id: str
    to_process_id: str
    dependency_type: str
    criticality: str
    notes: Optional[str]
    created_at: str


class ThirdParty(TypedDict, total=False):
    id: str
    name: str
    service_category: str
    criticality_rating: str
    owner_contact_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Assessment(TypedDict, total=False):
    id: str
    third_party_id: str
    process_id: str
    assessment_type: str
    assessed_rto_hours: int
    assessed_rpo_hours: int
    evidence_doc_ref: Optional[str]
    continuity_score: int
    score_variant: str
    meets_required_rto: bool
    rto_required_hours: int
    rpo_required_hours: int
    finalized_by_contact_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AlternateSite(TypedDict, total=False):
    id: str
    name: str
    site_type: str
    region: str
    capacity_seats: int
    contracted_through: str
    monthly_cost: float
    status: str
    created_at: str
    updated_at: str
    version: int


class SiteReservation(TypedDict, total=False):
    id: str
    site_id: str
    process_id: str
    purpose: str
    seats_reserved: int
    starts_at: str
    ends_at: str
    created_by_contact_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Exercise(TypedDict, total=False):
    id: str
    process_id: str
    plan_id: str
    exercise_type: str
    scheduled_start: str
    scheduled_end: str
    completion_outcome: Optional[str]
    achieved_rto_hours: Optional[int]
    achieved_rpo_hours: Optional[int]
    result: Optional[str]
    requires_capability_check: bool
    validation_run_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Finding(TypedDict, total=False):
    id: str
    exercise_id: str
    process_id: str
    severity: str
    description: str
    due_date: str
    root_cause: Optional[str]
    verified_by_contact_id: Optional[str]
    rejected_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class RecoveryCapability(TypedDict, total=False):
    id: str
    process_id: str
    capability_type: str
    capability_ref_id: str
    proven_rto_hours: Optional[int]
    proven_rpo_hours: Optional[int]
    meets_bia: bool
    last_validation_run_id: Optional[str]
    validation_freshness: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ValidationRun(TypedDict, total=False):
    id: str
    capability_id: str
    exercise_id: Optional[str]
    measured_rto_hours: int
    measured_rpo_hours: int
    method: str
    evidence_ref: str
    result: str
    gap_created_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Gap(TypedDict, total=False):
    id: str
    process_id: str
    capability_id: Optional[str]
    finding_id: Optional[str]
    gap_type: str
    severity: str
    description: str
    due_date: str
    overdue: bool
    closed_by_contact_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CommNode(TypedDict, total=False):
    id: str
    tree_label: str
    contact_name: str
    role_title: str
    parent_node_id: Optional[str]
    order_index: int
    channel: str
    ack_deadline_minutes: int
    active_flag: bool
    created_at: str
    updated_at: str
    version: int


class Activation(TypedDict, total=False):
    id: str
    process_id: str
    plan_id: Optional[str]
    declared_severity: str
    activation_criterion: str
    criterion_justification: str
    expected_notifications: int
    notified_count: int
    acked_count: int
    escalation_level: int
    acknowledged_at: Optional[str]
    deactivated_by_contact_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Attestation(TypedDict, total=False):
    id: str
    process_id: str
    attestation_type: str
    period_start: str
    period_end: str
    readiness_score: int
    snapshot_payload: Optional[dict]
    signed_by_contact_id: Optional[str]
    signer_declaration: Optional[bool]
    revoked_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Notification(TypedDict, total=False):
    # Cascade-created record: carries ONLY id + created_at (no updated_at, no version).
    id: str
    activation_id: str
    comm_node_id: str
    channel: str
    status: str
    sent_at: str
    acked_at: Optional[str]
    ack_token: str
    created_at: str
