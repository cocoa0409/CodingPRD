"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    QUALITY_ADMIN = "QualityAdmin"
    QUALITY_ANALYST = "QualityAnalyst"
    ABSTRACTOR = "Abstractor"
    OVER_READER = "OverReader"
    PROVIDER_RELATIONS = "ProviderRelations"
    AUDITOR = "Auditor"
    QUALITY_DIRECTOR = "QualityDirector"


class SeasonStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    SUBMISSION_CLOSED = "SUBMISSION_CLOSED"


class SpecStatus(str, Enum):
    LOADED = "LOADED"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class CollectionMethod(str, Enum):
    ADMINISTRATIVE = "ADMINISTRATIVE"
    HYBRID = "HYBRID"


class HybridPolicy(str, Enum):
    SAMPLE_ONLY = "SAMPLE_ONLY"
    ADMIN_SUPPLEMENTED = "ADMIN_SUPPLEMENTED"


class MatchingPolicy(str, Enum):
    EXACT = "EXACT"
    TOLERANT = "TOLERANT"


class GenderRequirement(str, Enum):
    ANY = "ANY"
    F = "F"
    M = "M"


class Gender(str, Enum):
    F = "F"
    M = "M"


class RunReportingStatus(str, Enum):
    POPULATION_PENDING = "POPULATION_PENDING"
    POPULATED = "POPULATED"
    RATE_COMPUTED = "RATE_COMPUTED"
    SUBMITTED = "SUBMITTED"
    CERTIFIED = "CERTIFIED"
    CERTIFICATION_FAILED = "CERTIFICATION_FAILED"


class RunAuditStatus(str, Enum):
    UNAUDITED = "UNAUDITED"
    IN_REVIEW = "IN_REVIEW"
    AUDIT_PASSED = "AUDIT_PASSED"
    AUDIT_FAILED = "AUDIT_FAILED"


class SampleStatus(str, Enum):
    DRAWN = "DRAWN"
    FINALIZED = "FINALIZED"
    LOCKED = "LOCKED"


class IrrState(str, Enum):
    PENDING = "PENDING"
    PASSED = "PASSED"
    FAILED = "FAILED"


class ChaseStatus(str, Enum):
    REQUESTED = "REQUESTED"
    RECEIVED = "RECEIVED"
    REJECTED_UNREADABLE = "REJECTED_UNREADABLE"
    WITHDRAWN = "WITHDRAWN"
    ABSTRACTED = "ABSTRACTED"
    EXCLUDED_VALID = "EXCLUDED_VALID"


class AbstractionResult(str, Enum):
    HIT = "HIT"
    MISS = "MISS"
    NOT_ABSTRACTABLE = "NOT_ABSTRACTABLE"


class AbstractionStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    CONFIRMED = "CONFIRMED"
    OVERREAD_PASSED = "OVERREAD_PASSED"
    REMEDIATION = "REMEDIATION"


class OverReadOutcome(str, Enum):
    AGREE = "AGREE"
    DISAGREE = "DISAGREE"


class SupplementalSourceType(str, Enum):
    LAB_FEED = "LAB_FEED"
    IMMUNIZATION_REGISTRY = "IMMUNIZATION_REGISTRY"
    PHARMACY = "PHARMACY"
    EHR = "EHR"


class BatchStatus(str, Enum):
    RECEIVED = "RECEIVED"
    SCREENED = "SCREENED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class RecordDisposition(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED_UNKNOWN_MEMBER = "REJECTED_UNKNOWN_MEMBER"
    REJECTED_OUT_OF_WINDOW = "REJECTED_OUT_OF_WINDOW"
    REJECTED_DUPLICATE = "REJECTED_DUPLICATE"


class GapStatus(str, Enum):
    OPEN = "OPEN"
    OUTREACH_DONE = "OUTREACH_DONE"
    CLOSED_COMPLIANT = "CLOSED_COMPLIANT"
    CLOSED_NONCOMPLIANT = "CLOSED_NONCOMPLIANT"


class GapClosureSource(str, Enum):
    MANUAL = "MANUAL"
    AUTO_EVIDENCE = "AUTO_EVIDENCE"


class EngagementStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_REVIEW = "IN_REVIEW"
    COMPLETED = "COMPLETED"


class EngagementOutcome(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class FindingSeverity(str, Enum):
    CRITICAL = "CRITICAL"
    MAJOR = "MAJOR"
    MINOR = "MINOR"


class FindingStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


class CertifyDecision(str, Enum):
    CERTIFIED = "CERTIFIED"
    FAILED = "FAILED"


class GapCloseOutcome(str, Enum):
    CLOSED_COMPLIANT = "CLOSED_COMPLIANT"
    CLOSED_NONCOMPLIANT = "CLOSED_NONCOMPLIANT"


# --- Entity TypedDicts ---
# Resources carrying id + created_at + updated_at + version (PRD §2.4 "most resources").


class MeasurementSeason(TypedDict, total=False):
    id: str
    measurement_year: int
    submission_deadline: str
    admin_data_cutoff: str
    approved_supplemental_sources: list
    status: str
    certified_run_count: int
    created_at: str
    updated_at: str
    version: int


class MeasureSpecification(TypedDict, total=False):
    id: str
    season_id: str
    hedis_measure_code: str
    version_label: str
    collection_method: str
    hybrid_policy: str
    matching_policy: str
    sample_size_floor: int
    age_min: int
    age_max: int
    gender_requirement: str
    continuous_enrollment_months: int
    allowable_gap_days: int
    anchor_date: str
    reporting_weight: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict, total=False):
    id: str
    member_ref: str
    birth_date: str
    gender: str
    attributed_provider_ref: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Provider(TypedDict, total=False):
    id: str
    provider_ref: str
    name: str
    specialty: Optional[str]
    open_gap_count: int
    created_at: str
    updated_at: str
    version: int


class MeasureRun(TypedDict, total=False):
    id: str
    season_id: str
    spec_id: str
    spec_version_label: str
    collection_method: str
    reporting_status: str
    audit_status: str
    denominator_count: int
    exclusion_count: int
    admin_numerator_count: int
    sample_exclusion_count: int
    sample_numerator_count: int
    admin_rate: Optional[float]
    hybrid_rate: Optional[float]
    final_rate: Optional[float]
    submitted_by_user_id: Optional[str]
    certified_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PopulationEntry(TypedDict, total=False):
    id: str
    run_id: str
    member_ref: str
    is_excluded: bool
    exclusion_reason: Optional[str]
    is_sampled: bool
    admin_compliant: bool
    sample_compliant: bool
    created_at: str
    updated_at: str
    version: int


class Sample(TypedDict, total=False):
    id: str
    run_id: str
    drawn_size: int
    draw_step: float
    status: str
    irr_state: str
    irr_ratio: Optional[float]
    remediation_count: int
    required_overread_fraction: float
    created_at: str
    updated_at: str
    version: int


class ChartChase(TypedDict, total=False):
    id: str
    sample_id: str
    member_ref: str
    provider_ref: Optional[str]
    status: str
    chase_round: int
    created_at: str
    updated_at: str
    version: int


class Abstraction(TypedDict, total=False):
    id: str
    chase_id: str
    result: str
    abstractor_user_id: str
    requires_overread: bool
    status: str
    resubmission_count: int
    submitted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SupplementalDataBatch(TypedDict, total=False):
    id: str
    run_id: str
    source_type: str
    status: str
    record_count: int
    accepted_record_count: int
    matching_policy_used: Optional[str]
    created_at: str
    updated_at: str
    version: int


class GapItem(TypedDict, total=False):
    id: str
    run_id: str
    member_ref: str
    provider_ref: Optional[str]
    gap_reason: str
    status: str
    closure_source: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AuditEngagement(TypedDict, total=False):
    id: str
    season_id: str
    measure_run_id: str
    auditor_user_id: str
    window_start: str
    window_end: str
    status: str
    outcome: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AuditFinding(TypedDict, total=False):
    id: str
    engagement_id: str
    severity: str
    summary: str
    status: str
    created_at: str
    updated_at: str
    version: int


# --- Light event/log rows (PRD §2.4: only id and created_at; no updated_at/version) ---


class MemberEnrollmentSegment(TypedDict, total=False):
    id: str
    member_id: str
    span_start: str
    span_end: str
    created_at: str


class OverReadReview(TypedDict, total=False):
    id: str
    abstraction_id: str
    reviewer_user_id: str
    outcome: str
    final_result: Optional[str]
    created_at: str


class SupplementalRecord(TypedDict, total=False):
    id: str
    batch_id: str
    member_ref: str
    service_date: str
    evidence_code: str
    disposition: str
    created_at: str
