"""Domain types for the Clinical Decision Support Governance API.

Entity TypedDicts, state enums and the committee role enum, all named exactly
as the PRD names them.
"""

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles and taxonomies
# --------------------------------------------------------------------------


class UserRole(str, Enum):
    CLINICAL_SPONSOR = "ClinicalSponsor"
    INFORMATICS_BUILDER = "InformaticsBuilder"
    PEER_REVIEWER = "PeerReviewer"
    SPECIALTY_APPROVER = "SpecialtyApprover"
    COMMITTEE_CHAIR = "CommitteeChair"
    PHARMACY_INFORMATICIST = "PharmacyInformaticist"
    SYSTEM_ADMIN = "SystemAdmin"


class Specialty(str, Enum):
    INTERNAL_MEDICINE = "INTERNAL_MEDICINE"
    HOSPITAL_MEDICINE = "HOSPITAL_MEDICINE"
    CRITICAL_CARE = "CRITICAL_CARE"
    CARDIOLOGY = "CARDIOLOGY"
    NEPHROLOGY = "NEPHROLOGY"
    ENDOCRINOLOGY = "ENDOCRINOLOGY"
    GERIATRICS = "GERIATRICS"
    ONCOLOGY = "ONCOLOGY"
    PEDIATRICS = "PEDIATRICS"
    EMERGENCY = "EMERGENCY"
    ORTHOPEDICS = "ORTHOPEDICS"
    PHARMACY = "PHARMACY"
    NURSING = "NURSING"
    INFORMATICS = "INFORMATICS"


class Credential(str, Enum):
    MD = "MD"
    DO = "DO"
    PHARMD = "PHARMD"
    RN = "RN"
    NP = "NP"


class EmploymentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


# --------------------------------------------------------------------------
# State enums
# --------------------------------------------------------------------------


class ContentRequestStatus(str, Enum):
    INTAKE_SUBMITTED = "INTAKE_SUBMITTED"
    TRIAGE_ACCEPTED = "TRIAGE_ACCEPTED"
    RETURNED_TO_SPONSOR = "RETURNED_TO_SPONSOR"
    DECLINED = "DECLINED"
    BUILD_IN_PROGRESS = "BUILD_IN_PROGRESS"
    CLOSED_IMPLEMENTED = "CLOSED_IMPLEMENTED"


class OrderSetReviewState(str, Enum):
    DRAFT = "DRAFT"
    PEER_REVIEW = "PEER_REVIEW"
    SPECIALTY_APPROVAL = "SPECIALTY_APPROVAL"
    APPROVED = "APPROVED"


class OrderSetPublicationState(str, Enum):
    UNPUBLISHED = "UNPUBLISHED"
    PUBLISHED = "PUBLISHED"
    EXPIRING = "EXPIRING"
    EXPIRED = "EXPIRED"
    ARCHIVED = "ARCHIVED"
    SUPERSEDED = "SUPERSEDED"


class AlertReviewState(str, Enum):
    DRAFT = "DRAFT"
    SPECIALTY_APPROVAL = "SPECIALTY_APPROVAL"
    APPROVED = "APPROVED"


class AlertLifecycleState(str, Enum):
    UNPUBLISHED = "UNPUBLISHED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    RETIRED = "RETIRED"


class ReviewAssignmentState(str, Enum):
    ASSIGNED = "ASSIGNED"
    CAST = "CAST"
    WITHDRAWN = "WITHDRAWN"
    VOIDED = "VOIDED"


class VendorReviewCycleState(str, Enum):
    RECEIVED = "RECEIVED"
    IMPACT_ANALYZED_FAST_TRACK = "IMPACT_ANALYZED_FAST_TRACK"
    IMPACT_ANALYZED_CLINICAL_REVIEW = "IMPACT_ANALYZED_CLINICAL_REVIEW"
    ACTIVATED = "ACTIVATED"
    SUPERSEDED = "SUPERSEDED"


class BurdenWindowState(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    FINALIZED = "FINALIZED"


class BurdenClassification(str, Enum):
    NO_SIGNAL = "NO_SIGNAL"
    LOW_VALUE = "LOW_VALUE"
    HIGH_VALUE = "HIGH_VALUE"
    MONITOR = "MONITOR"


class ClosureReason(str, Enum):
    MANUAL_CLOSE = "MANUAL_CLOSE"
    SUPERSEDED_BY_NEW_WINDOW = "SUPERSEDED_BY_NEW_WINDOW"
    SOURCE_SUSPENDED = "SOURCE_SUSPENDED"
    ALERT_RETIRED = "ALERT_RETIRED"


class DowntimeEventState(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class DowntimeScope(str, Enum):
    SYSTEM_WIDE = "SYSTEM_WIDE"
    ORDER_SETS_ONLY = "ORDER_SETS_ONLY"
    ALERTS_ONLY = "ALERTS_ONLY"


class DowntimeMode(str, Enum):
    READ_ONLY = "READ_ONLY"
    FULL_UNAVAILABLE = "FULL_UNAVAILABLE"


class MeasurementState(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINALIZED = "FINALIZED"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class MeasurementVerdict(str, Enum):
    SUSTAIN = "SUSTAIN"
    REVISE = "REVISE"
    RETIRE = "RETIRE"


class AnnualReviewTaskState(str, Enum):
    PENDING = "PENDING"
    OVERDUE = "OVERDUE"
    ATTESTED = "ATTESTED"
    EXPIRED = "EXPIRED"


class ArtifactKind(str, Enum):
    ORDER_SET = "ORDER_SET"
    ALERT = "ALERT"


class RiskClass(str, Enum):
    STANDARD = "STANDARD"
    HIGH = "HIGH"


class RequestType(str, Enum):
    ORDER_SET = "ORDER_SET"
    ALERT = "ALERT"
    BOTH = "BOTH"


class Urgency(str, Enum):
    ROUTINE = "ROUTINE"
    EXPEDITED = "EXPEDITED"
    SAFETY_URGENT = "SAFETY_URGENT"


class EvidenceGrade(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    EXPERT_OPINION = "EXPERT_OPINION"


class PriorityScoreBasis(str, Enum):
    INTAKE_PROVISIONAL = "INTAKE_PROVISIONAL"
    COMMITTEE_CALIBRATED = "COMMITTEE_CALIBRATED"


class TriageDecision(str, Enum):
    ACCEPT = "ACCEPT"
    RETURN = "RETURN"
    DECLINE = "DECLINE"


class SeverityTier(str, Enum):
    TIER_1_HARD_STOP = "TIER_1_HARD_STOP"
    TIER_2_INTERRUPTIVE = "TIER_2_INTERRUPTIVE"
    TIER_3_PASSIVE = "TIER_3_PASSIVE"


class ItemCategory(str, Enum):
    MEDICATION = "MEDICATION"
    LAB = "LAB"
    IMAGING = "IMAGING"
    NURSING = "NURSING"
    CONSULT = "CONSULT"


class ReviewKind(str, Enum):
    PEER_REVIEW = "PEER_REVIEW"
    SPECIALTY_APPROVAL = "SPECIALTY_APPROVAL"


class Vote(str, Enum):
    APPROVE = "APPROVE"
    REVISE = "REVISE"
    REJECT = "REJECT"


class VoidReason(str, Enum):
    ARTIFACT_RETURNED_TO_DRAFT = "ARTIFACT_RETURNED_TO_DRAFT"
    ARTIFACT_SUPERSEDED = "ARTIFACT_SUPERSEDED"


class ContentDomain(str, Enum):
    DRUG_INTERACTION = "DRUG_INTERACTION"
    DOSING = "DOSING"
    ALLERGY = "ALLERGY"
    DUPLICATE_THERAPY = "DUPLICATE_THERAPY"


class ChangeType(str, Enum):
    NEW_INTERACTION = "NEW_INTERACTION"
    SEVERITY_INCREASED = "SEVERITY_INCREASED"
    SEVERITY_DECREASED = "SEVERITY_DECREASED"
    RETIRED_INTERACTION = "RETIRED_INTERACTION"
    DOSING_BOUND_CHANGED = "DOSING_BOUND_CHANGED"


class Severity(str, Enum):
    CONTRAINDICATED = "CONTRAINDICATED"
    MAJOR = "MAJOR"
    MODERATE = "MODERATE"
    MINOR = "MINOR"


class Disposition(str, Enum):
    ACCEPT = "ACCEPT"
    SUPPRESS = "SUPPRESS"
    CUSTOMIZE = "CUSTOMIZE"


class SuspensionReason(str, Enum):
    SOURCE_CONTENT_EXPIRED = "SOURCE_CONTENT_EXPIRED"


# --------------------------------------------------------------------------
# Entity TypedDicts
# --------------------------------------------------------------------------


class Clinician(TypedDict):
    id: str
    full_name: str
    npi: Optional[str]
    specialty: str
    credential: Optional[str]
    authorized_roles: List[str]
    employment_status: str
    review_workload_capacity_minutes: int
    review_workload_assigned_minutes: int
    review_workload_remaining_minutes: int
    open_assignment_count: int
    created_at: str
    updated_at: str
    version: int


class ContentRequest(TypedDict):
    id: str
    title: str
    request_type: str
    clinical_domain: str
    urgency: str
    evidence_grade: str
    clinical_sponsor_id: str
    patient_safety_flag: bool
    requested_go_live_at: Optional[str]
    evidence_citations: List[Dict[str, Any]]
    peer_reviewed_citation_count: int
    priority_score: float
    priority_score_basis: str
    status: str
    return_count: int
    triage_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OrderSet(TypedDict):
    id: str
    content_request_id: str
    name: str
    specialty: str
    pinned_vendor_release_id: str
    built_by_clinician_id: str
    supersedes_order_set_id: Optional[str]
    review_state: str
    publication_state: str
    risk_class: str
    item_count: int
    high_alert_item_count: int
    revision_round: int
    votes_cast_count: int
    votes_voided_count: int
    peer_cast_count: int
    specialty_cast_count: int
    peer_required_votes: Optional[int]
    specialty_required_votes: Optional[int]
    peer_approve_ratio: Optional[float]
    specialty_approve_ratio: Optional[float]
    pharmacy_signoff_at: Optional[str]
    pharmacy_signoff_by_clinician_id: Optional[str]
    go_live_at: Optional[str]
    review_due_date: Optional[str]
    expiration_at: Optional[str]
    archive_eligible_at: Optional[str]
    latest_adherence_pct: Optional[float]
    archived_at: Optional[str]
    pinned_content_stale: bool
    created_at: str
    updated_at: str
    version: int


# Append-only item line: carries ONLY id and created_at, no updated_at, no version.
class OrderSetItem(TypedDict):
    id: str
    order_set_id: str
    orderable_code: str
    display_name: str
    item_category: str
    default_selected: bool
    default_dose: Optional[str]
    route: Optional[str]
    frequency: Optional[str]
    high_alert_medication: bool
    sequence_index: int
    created_at: str


class Alert(TypedDict):
    id: str
    content_request_id: str
    name: str
    firing_criteria: Dict[str, Any]
    designed_by_clinician_id: str
    severity_tier: str
    override_reason_codes: List[str]
    override_reason_required: bool
    hard_stop_justification: Optional[str]
    linked_order_set_id: Optional[str]
    review_state: str
    lifecycle_state: str
    required_approval_votes: Optional[int]
    approval_cast_count: int
    latest_burden_index: Optional[float]
    latest_burden_classification: Optional[str]
    review_due_date: Optional[str]
    expiration_at: Optional[str]
    retired_at: Optional[str]
    suspension_reason: Optional[str]
    suspension_count: int
    restage_count: int
    lifetime_fire_count: int
    windowed_fire_count: int
    unwindowed_fire_count: int
    lifetime_override_count: int
    created_at: str
    updated_at: str
    version: int


class AlertBurdenWindow(TypedDict):
    id: str
    alert_id: str
    window_start: str
    window_end: str
    state: str
    severity_tier_snapshot: str
    fire_count: int
    override_count: int
    accept_count: int
    distinct_fired_clinician_count: int
    distinct_overriding_clinician_count: int
    override_rate: Optional[float]
    volume_factor: Optional[float]
    burden_index: Optional[float]
    burden_index_clinician_weighted: Optional[float]
    burden_classification: Optional[str]
    closure_reason: Optional[str]
    closed_at: Optional[str]
    reopen_count: int
    created_at: str
    updated_at: str
    version: int


# Append-only firing record: carries ONLY id and created_at.
class OverrideEvent(TypedDict):
    id: str
    alert_id: str
    firing_clinician_ref: str
    fired_at: str
    accepted: bool
    override_reason_code: Optional[str]
    severity_tier_snapshot: str
    ingest_batch_seq: int
    created_at: str


class ReviewAssignment(TypedDict):
    id: str
    order_set_id: Optional[str]
    alert_id: Optional[str]
    reviewer_id: str
    review_kind: str
    state: str
    risk_class_snapshot: str
    estimated_minutes: int
    due_at: Optional[str]
    vote: Optional[str]
    comment: Optional[str]
    evidence_concern: bool
    cast_at: Optional[str]
    withdrawal_reason: Optional[str]
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class VendorContentRelease(TypedDict):
    id: str
    vendor_name: str
    release_label: str
    content_domain: str
    received_at: str
    effective_at: Optional[str]
    supersedes_release_id: Optional[str]
    review_cycle_state: str
    delta_count: int
    contraindicated_delta_count: int
    dispositioned_delta_count: int
    restaged_order_set_count: int
    impact_score: Optional[int]
    activated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class VendorRuleDelta(TypedDict):
    id: str
    vendor_release_id: str
    rule_code: str
    change_type: str
    description: str
    drug_pair: Optional[str]
    prior_severity: Optional[str]
    new_severity: Optional[str]
    weight: int
    disposition: Optional[str]
    suppression_justification: Optional[str]
    dispositioned_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DowntimeEvent(TypedDict):
    id: str
    scope: str
    mode: str
    window_start: str
    window_end: str
    planned: bool
    reason: Optional[str]
    state: str
    blocked_mutation_count: int
    activated_at: Optional[str]
    closed_at: Optional[str]
    declared_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class AdherenceMeasurement(TypedDict):
    id: str
    order_set_id: str
    measurement_period_start: str
    measurement_period_end: str
    unit_observations: List[Dict[str, Any]]
    included_unit_count: int
    excluded_unit_count: int
    unintended_event_count: int
    adherence_pct_per_protocol: Optional[float]
    adherence_pct_intention_to_treat: Optional[float]
    unintended_event_rate_per_100: Optional[float]
    measurement_state: str
    verdict: Optional[str]
    finalized_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AnnualReviewTask(TypedDict):
    id: str
    artifact_kind: str
    order_set_id: Optional[str]
    alert_id: Optional[str]
    review_due_date: str
    expiration_at: str
    archive_eligible_at: Optional[str]
    cycle_index: int
    state: str
    stale_content_triggered: bool
    evidence_citations: List[Dict[str, Any]]
    attested_at: Optional[str]
    attestation_note: Optional[str]
    attested_by_clinician_id: Optional[str]
    created_at: str
    updated_at: str
    version: int
