"""Domain types: entity TypedDicts, status enums, role enum.

All eleven entities carry the four common fields (id, created_at, updated_at,
version) per the PRD's common-resource-properties rule.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    COORDINATOR = "DistrictSafetyCoordinator"
    OFFICER = "SchoolSafetyOfficer"
    PRINCIPAL = "Principal"
    RESPONDER = "FirstResponder"
    AUDITOR = "StateAuditor"


class DrillType(str, Enum):
    FIRE = "FIRE"
    LOCKDOWN = "LOCKDOWN"
    EVACUATION = "EVACUATION"
    SHELTER_IN_PLACE = "SHELTER_IN_PLACE"
    EARTHQUAKE = "EARTHQUAKE"


class CompliancePosture(str, Enum):
    ON_TRACK = "ON_TRACK"
    AT_RISK = "AT_RISK"
    NON_COMPLIANT = "NON_COMPLIANT"


class EopStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    RETURNED = "RETURNED"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"


class SitePlanStatus(str, Enum):
    CURRENT = "CURRENT"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"


class WalkthroughStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    MISSED = "MISSED"


class DrillStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"
    MISSED = "MISSED"


class RosterStatus(str, Enum):
    UNACCOUNTED = "UNACCOUNTED"
    ACCOUNTED = "ACCOUNTED"
    RELEASED = "RELEASED"


class ReviewStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    RETURNED = "RETURNED"
    CLOSED = "CLOSED"


class CorrectiveActionStatus(str, Enum):
    OPEN = "OPEN"
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    REOPENED = "REOPENED"
    VERIFIED = "VERIFIED"


class AccommodationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    STALE = "STALE"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class AnnouncementMode(str, Enum):
    ANNOUNCED = "ANNOUNCED"
    UNANNOUNCED = "UNANNOUNCED"


class Agency(str, Enum):
    FIRE = "FIRE"
    POLICE = "POLICE"
    EMS = "EMS"


class NeedType(str, Enum):
    MOBILITY = "MOBILITY"
    VISUAL = "VISUAL"
    AUDITORY = "AUDITORY"
    SENSORY = "SENSORY"
    COGNITIVE = "COGNITIVE"


class OverallRating(str, Enum):
    EXCEEDS = "EXCEEDS"
    MEETS = "MEETS"
    NEEDS_IMPROVEMENT = "NEEDS_IMPROVEMENT"
    UNSATISFACTORY = "UNSATISFACTORY"


class EvacuationAssessment(str, Enum):
    MET_STANDARD = "MET_STANDARD"
    MET_ADJUSTED = "MET_ADJUSTED"
    NOT_MET = "NOT_MET"


class Priority(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class CoverageTag(str, Enum):
    FLOOR_PLANS = "FLOOR_PLANS"
    ACCESS_POINTS = "ACCESS_POINTS"
    UTILITY_SHUTOFFS = "UTILITY_SHUTOFFS"
    ASSEMBLY_AREAS = "ASSEMBLY_AREAS"


# --- Entity TypedDicts (all carry id, created_at, updated_at, version) ---
# total=False: serializers may omit null-valued optional system fields.

class SchoolSite(TypedDict, total=False):
    id: str
    name: str
    enrollment_count: int
    academic_year_start: str
    academic_year_end: str
    compliance_posture: str
    drills_scheduled_count: int
    drills_completed_count: int
    drills_missed_count: int
    drills_cancelled_count: int
    created_at: str
    updated_at: str
    version: int


class DrillTypeRequirement(TypedDict, total=False):
    id: str
    site_id: str
    drill_type: str
    required_per_year: int
    min_spacing_days: int
    target_evac_seconds: int
    notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EmergencyOperationsPlan(TypedDict, total=False):
    id: str
    site_id: str
    title: str
    plan_version_label: str
    content_summary: str
    review_due_date: str
    status: str
    submitted_by_user_id: Optional[str]
    return_reason: Optional[str]
    activated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SitePlanDocument(TypedDict, total=False):
    id: str
    site_id: str
    document_title: str
    issued_on: str
    review_by_date: str
    coverage_tags: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class FirstResponderWalkthrough(TypedDict, total=False):
    id: str
    site_id: str
    agency: str
    scheduled_date: str
    completed_date: Optional[str]
    findings_summary: Optional[str]
    recommendations_count: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class DrillEvent(TypedDict, total=False):
    id: str
    site_id: str
    drill_type: str
    scheduled_date: str
    scheduled_start_time: str
    duration_minutes: int
    announcement_mode: str
    status: str
    conducted_by_user_id: Optional[str]
    actual_start_at: Optional[str]
    all_clear_at: Optional[str]
    last_accountability_at: Optional[str]
    provisional_evac_seconds: Optional[int]
    official_evac_seconds: Optional[int]
    met_target_standard: Optional[bool]
    met_target_adjusted: Optional[bool]
    roster_total: int
    unaccounted_count: int
    accounted_count: int
    released_count: int
    completion_notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RosterEntry(TypedDict, total=False):
    id: str
    drill_event_id: str
    student_ref: str
    accommodation_required: bool
    status: str
    accounted_at: Optional[str]
    guardian_name: Optional[str]
    released_to_verified: Optional[bool]
    released_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AfterActionReview(TypedDict, total=False):
    id: str
    drill_event_id: str
    findings_summary: str
    overall_rating: str
    evacuation_assessment: str
    status: str
    submitted_by_user_id: Optional[str]
    decided_by_user_id: Optional[str]
    return_reason: Optional[str]
    ca_total_count: int
    ca_verified_count: int
    created_at: str
    updated_at: str
    version: int


class CorrectiveAction(TypedDict, total=False):
    id: str
    aar_id: str
    description: str
    priority: str
    due_date: str
    assignee_name: str
    status: str
    evidence_note: Optional[str]
    is_overdue: bool
    verified_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AccommodationPlan(TypedDict, total=False):
    id: str
    site_id: str
    student_ref: str
    need_type: str
    instructions: str
    review_by_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class TypeAttainment(TypedDict, total=False):
    drill_type: str
    required_count: int
    completed_count: int
    spacing_compliant: bool
    attainment_count_only: bool
    attainment_strict: bool


class ComplianceReport(TypedDict, total=False):
    id: str
    site_id: str
    period_start: str
    period_end: str
    status: str
    snapshot_generated_at: str
    type_attainments: List[TypeAttainment]
    overall_compliant_count_only: bool
    overall_compliant_strict: bool
    overall_score_pct: float
    submitted_at: Optional[str]
    decided_by_user_id: Optional[str]
    auditor_comment: Optional[str]
    created_at: str
    updated_at: str
    version: int


__all__ = [
    "UserRole", "DrillType", "CompliancePosture", "EopStatus", "SitePlanStatus",
    "WalkthroughStatus", "DrillStatus", "RosterStatus", "ReviewStatus",
    "CorrectiveActionStatus", "AccommodationStatus", "ReportStatus",
    "AnnouncementMode", "Agency", "NeedType", "OverallRating",
    "EvacuationAssessment", "Priority", "CoverageTag",
    "SchoolSite", "DrillTypeRequirement", "EmergencyOperationsPlan",
    "SitePlanDocument", "FirstResponderWalkthrough", "DrillEvent",
    "RosterEntry", "AfterActionReview", "CorrectiveAction",
    "AccommodationPlan", "TypeAttainment", "ComplianceReport",
]
