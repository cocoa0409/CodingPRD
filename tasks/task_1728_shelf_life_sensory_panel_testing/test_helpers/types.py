"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.5, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    LAB_DIRECTOR = "LabDirector"
    SENSORY_SCIENTIST = "SensoryScientist"
    PANEL_COORDINATOR = "PanelCoordinator"
    PANELIST = "Panelist"
    LAB_ANALYST = "LabAnalyst"
    QA_OFFICER = "QAOfficer"
    CLIENT = "Client"


class StudyStatus(str, Enum):
    DRAFT = "DRAFT"
    DESIGN_REVIEW = "DESIGN_REVIEW"
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    ANALYSIS = "ANALYSIS"
    REPORTING = "REPORTING"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"


class TimePointStatus(str, Enum):
    PENDING = "PENDING"
    PULLED = "PULLED"
    EVALUATED = "EVALUATED"
    CLOSED = "CLOSED"
    SKIPPED = "SKIPPED"


class SampleUnitStatus(str, Enum):
    STORED = "STORED"
    CHECKED_OUT = "CHECKED_OUT"
    CONSUMED = "CONSUMED"
    DISCARDED = "DISCARDED"
    EXPIRED = "EXPIRED"


class PanelistStatus(str, Enum):
    APPLIED = "APPLIED"
    TRAINING = "TRAINING"
    QUALIFIED = "QUALIFIED"
    INACTIVE = "INACTIVE"
    SUSPENDED = "SUSPENDED"
    SCREENED_OUT = "SCREENED_OUT"


class SessionStatus(str, Enum):
    PLANNED = "PLANNED"
    OPEN = "OPEN"
    LOCKED = "LOCKED"
    ANALYZED = "ANALYZED"
    CANCELLED = "CANCELLED"


class AssignmentStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    SUBMITTED = "SUBMITTED"
    NO_SHOW = "NO_SHOW"
    EXCUSED = "EXCUSED"


class RecommendationStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    INTERNAL_REVIEW = "INTERNAL_REVIEW"
    CLIENT_REVIEW = "CLIENT_REVIEW"
    RELEASED = "RELEASED"
    REJECTED = "REJECTED"


class ClaimVerdict(str, Enum):
    PENDING = "PENDING"
    SUPPORTED = "SUPPORTED"
    NOT_SUPPORTED = "NOT_SUPPORTED"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class Attribute(str, Enum):
    APPEARANCE = "APPEARANCE"
    AROMA = "AROMA"
    FLAVOR = "FLAVOR"
    TEXTURE = "TEXTURE"
    OFF_FLAVOR = "OFF_FLAVOR"
    OVERALL = "OVERALL"


class PackagingVariant(str, Enum):
    STANDARD_FILM = "STANDARD_FILM"
    HIGH_BARRIER = "HIGH_BARRIER"
    MAP = "MAP"
    VACUUM = "VACUUM"


class TestType(str, Enum):
    APC = "APC"
    YEAST_MOLD = "YEAST_MOLD"
    LACTIC = "LACTIC"
    PEROXIDE_VALUE = "PEROXIDE_VALUE"
    PH = "PH"
    WATER_ACTIVITY = "WATER_ACTIVITY"


# --- Entity TypedDicts -------------------------------------------------------
# Primary resources carry id + created_at + updated_at + version (PRD §2.5).

class ClientAccount(TypedDict, total=False):
    id: str
    name: str
    contact_email: str
    tier: str
    retainer_hours_balance: float
    active_study_count: int
    created_at: str
    updated_at: str
    version: int


class Study(TypedDict, total=False):
    id: str
    client_id: str
    product_name: str
    study_type: str
    storage_temp_c: float
    reference_temp_c: float
    q10_factor: float
    target_shelf_life_days: int
    sensory_fail_threshold: float
    min_detectable_difference: float
    planned_start_utc: str
    actual_start_utc: Optional[str]
    reserved_hours_escrow: float
    consumed_hours: float
    earliest_failure_day_equiv: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class StudyArm(TypedDict, total=False):
    id: str
    study_id: str
    packaging_variant: str
    is_control: bool
    computed_failure_day_equiv: Optional[float]
    created_at: str
    updated_at: str
    version: int


class SamplingTimePoint(TypedDict, total=False):
    id: str
    study_id: str
    day_index: int
    status: str
    created_at: str
    updated_at: str
    version: int


class StorageChamber(TypedDict, total=False):
    id: str
    chamber_code: str
    temp_c: float
    capacity_units: int
    reserved_units: int
    created_at: str
    updated_at: str
    version: int


class SampleUnit(TypedDict, total=False):
    id: str
    study_id: str
    arm_id: str
    chamber_id: str
    time_point_id: str
    unit_purpose: str
    session_id: Optional[str]
    retention_until_utc: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Panelist(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    qualified_attributes: List[str]
    screening_acuity_score: Optional[float]
    training_sessions_completed: int
    consecutive_no_shows: int
    consistency_index_provisional: Optional[float]
    consistency_index_final: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class EvaluationSession(TypedDict, total=False):
    id: str
    study_id: str
    time_point_id: str
    arm_id: str
    scheduled_start_utc: str
    scheduled_end_utc: str
    makeup_of_id: Optional[str]
    required_panelist_count: int
    overall_mean: Optional[float]
    significance_delta: Optional[float]
    sensory_failed: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class PanelAssignment(TypedDict, total=False):
    id: str
    session_id: str
    panelist_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


# Immutable event records (PRD §2.5): only id + created_at — NO updated_at,
# NO version.

class AttributeScore(TypedDict, total=False):
    id: str
    assignment_id: str
    attribute: str
    score: int
    created_at: str


class LabTestResult(TypedDict, total=False):
    id: str
    study_id: str
    arm_id: str
    time_point_id: str
    test_type: str
    measured_value: float
    tripped: bool
    created_at: str


class DateCodeRecommendation(TypedDict, total=False):
    id: str
    study_id: str
    arm_id: str
    basis: str
    computed_days: int
    status: str
    created_at: str
    updated_at: str
    version: int


class StudyReport(TypedDict, total=False):
    id: str
    study_id: str
    title: str
    author_user_id: str
    pinned_recommendation_id: Optional[str]
    snapshot_days: Optional[int]
    requires_revision: bool
    revision_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ClaimSubstantiation(TypedDict, total=False):
    id: str
    report_id: str
    claim_type: str
    claim_text: str
    claimed_value: float
    arm_id: Optional[str]
    verdict: str
    verified_by: Optional[str]
    created_at: str
    updated_at: str
    version: int
