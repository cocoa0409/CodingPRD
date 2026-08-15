"""Domain types: entity TypedDicts, status enums, role enum (PRD sections 2 and 3)."""
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD section 2.1)
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    PROGRAM_DIRECTOR = "ProgramDirector"
    EVALUATION_LEAD = "EvaluationLead"
    FIELD_COLLECTOR = "FieldCollector"
    DATA_STEWARD = "DataSteward"
    PRIVACY_OFFICER = "PrivacyOfficer"
    FUNDER_VIEWER = "FunderViewer"
    VENDOR_ANALYST = "VendorAnalyst"


# ---------------------------------------------------------------------------
# Entity status enums (PRD section 3)
# ---------------------------------------------------------------------------

class ProgramStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    ARCHIVED = "ARCHIVED"


class FunderStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class LogicModelStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class IndicatorStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class IndicatorLevel(str, Enum):
    OUTPUT = "OUTPUT"
    OUTCOME = "OUTCOME"
    IMPACT = "IMPACT"


class IndicatorUnit(str, Enum):
    COUNT = "COUNT"
    PERCENT = "PERCENT"
    SCORE = "SCORE"


class IndicatorDirection(str, Enum):
    HIGHER_IS_BETTER = "HIGHER_IS_BETTER"
    LOWER_IS_BETTER = "LOWER_IS_BETTER"


class MeasurementFrequency(str, Enum):
    PER_EVENT = "PER_EVENT"
    MONTHLY = "MONTHLY"
    END_OF_CYCLE = "END_OF_CYCLE"


class ProgramCycleStatus(str, Enum):
    SETUP = "SETUP"
    ENROLLING = "ENROLLING"
    ACTIVE = "ACTIVE"
    DATA_CLOSED = "DATA_CLOSED"
    UNDER_REVIEW = "UNDER_REVIEW"
    REPORTED = "REPORTED"
    ARCHIVED = "ARCHIVED"


class ParticipantStatus(str, Enum):
    ENROLLED = "ENROLLED"
    ACTIVE = "ACTIVE"
    EXITED = "EXITED"
    COMPLETED = "COMPLETED"
    WITHDRAWN = "WITHDRAWN"


class ConsentStatus(str, Enum):
    NONE = "NONE"
    CURRENT = "CURRENT"
    EXPIRED = "EXPIRED"


class ConsentRecordStatus(str, Enum):
    GRANTED = "GRANTED"
    SUPERSEDED = "SUPERSEDED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class ConsentScope(str, Enum):
    FULL = "FULL"
    AGGREGATE_ONLY = "AGGREGATE_ONLY"


class InstrumentStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    RETIRED = "RETIRED"


class CertificationStatus(str, Enum):
    CERTIFIED = "CERTIFIED"
    SUSPENDED = "SUSPENDED"
    STALE = "STALE"
    EXPIRED = "EXPIRED"


class ReviewStatus(str, Enum):
    PENDING = "PENDING"
    VALIDATED = "VALIDATED"
    FLAGGED = "FLAGGED"
    EXCLUDED = "EXCLUDED"


class MilestoneStatus(str, Enum):
    PENDING = "PENDING"
    MET = "MET"
    MISSED = "MISSED"


class AuditStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class FindingStatus(str, Enum):
    OPEN = "OPEN"
    WAIVED = "WAIVED"
    REMEDIATED = "REMEDIATED"


class FindingType(str, Enum):
    MISSING_DATA = "MISSING_DATA"
    OUTLIER = "OUTLIER"
    UNCERTIFIED_COLLECTOR = "UNCERTIFIED_COLLECTOR"
    CONSENT_LAPSE = "CONSENT_LAPSE"
    LATE_DATA = "LATE_DATA"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    GENERATED = "GENERATED"
    DELIVERED = "DELIVERED"
    ACCEPTED = "ACCEPTED"
    RETURNED = "RETURNED"
    SUPERSEDED = "SUPERSEDED"


class ReportType(str, Enum):
    FUNDER_STANDARD = "FUNDER_STANDARD"
    FUNDER_CUSTOM = "FUNDER_CUSTOM"
    INTERNAL_DASHBOARD = "INTERNAL_DASHBOARD"


class VendorEngagementStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    TERMINATED = "TERMINATED"


class ImprovementActionStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    IN_PROGRESS = "IN_PROGRESS"
    IMPLEMENTED = "IMPLEMENTED"
    VERIFIED_EFFECTIVE = "VERIFIED_EFFECTIVE"
    VERIFIED_INEFFECTIVE = "VERIFIED_INEFFECTIVE"


class AttainmentBand(str, Enum):
    GREEN = "GREEN"
    YELLOW = "YELLOW"
    RED = "RED"


class AttainmentVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


# ---------------------------------------------------------------------------
# Entity TypedDicts. Every entity in this system carries the four
# system-managed properties id/created_at/updated_at/version (PRD section 2.4).
# ---------------------------------------------------------------------------

class Program(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    name: str
    code: str
    status: str
    current_logic_model_id: Optional[str]
    current_consent_form_version: int


class Funder(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    name: str
    code: str
    status: str


class LogicModel(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    program_id: str
    title: str
    description: str
    version_no: int
    status: str
    approved_at: Optional[str]


class Indicator(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    logic_model_id: str
    code: str
    level: str
    unit: str
    direction: str
    baseline_value: float
    target_value: float
    weight: float
    measurement_frequency: str
    status: str


class ProgramCycle(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    program_id: str
    label: str
    enrollment_start: str
    enrollment_end: str
    cycle_start: str
    cycle_end: str
    reporting_due_date: str
    status: str
    pinned_logic_model_id: Optional[str]
    consent_form_version_snapshot: Optional[int]
    active_participant_count: int
    total_observation_count: int
    validated_observation_count: int
    data_completeness_pct: Optional[float]
    latest_dq_score: Optional[float]


class Participant(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    program_cycle_id: str
    external_ref: str
    enrolled_at: str
    status: str
    exit_reason: Optional[str]
    consent_status: str


class ConsentRecord(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    participant_id: str
    form_version: int
    scope: str
    granted_at: str
    expires_at: str
    status: str
    revoked_at: Optional[str]


class Instrument(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    program_id: str
    code: str
    title: str
    instrument_version: int
    status: str


class TrainingCertification(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    staff_user_id: str
    instrument_id: str
    certified_instrument_version: int
    certified_at: str
    expires_at: str
    status: str


class Observation(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    participant_id: str
    indicator_id: str
    instrument_id: str
    instrument_version: int
    value: float
    collected_at: str
    recorded_at: str
    collected_by_id: str
    review_status: str
    is_late: bool
    exclusion_reason: Optional[str]


class Milestone(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    program_cycle_id: str
    indicator_id: str
    due_date: str
    milestone_target: float
    status: str
    evaluated_at: Optional[str]


class DataQualityAudit(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    program_cycle_id: str
    status: str
    opened_by_id: str
    completeness_pct: Optional[float]
    validated_pct: Optional[float]
    dq_score: Optional[float]
    open_finding_count: int
    closed_at: Optional[str]


class AuditFinding(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    audit_id: str
    finding_type: str
    participant_id: str
    indicator_id: Optional[str]
    observation_id: Optional[str]
    description: str
    status: str
    resolution_note: Optional[str]


class Report(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    program_cycle_id: str
    funder_id: str
    report_type: str
    status: str
    snapshot_overall_impact_index: Optional[float]
    snapshot_data_completeness_pct: Optional[float]
    snapshot_dq_score: Optional[float]
    generated_at: Optional[str]
    delivered_at: Optional[str]


class VendorEngagement(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    program_id: str
    vendor_name: str
    scope_program_cycle_ids: List[str]
    access_start: str
    access_end: str
    deliverable_due: str
    deliverable_received_at: Optional[str]
    status: str


class ImprovementAction(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    program_id: str
    audit_finding_id: Optional[str]
    report_id: Optional[str]
    title: str
    description: str
    status: str
    effectiveness_reviewed_at: Optional[str]
