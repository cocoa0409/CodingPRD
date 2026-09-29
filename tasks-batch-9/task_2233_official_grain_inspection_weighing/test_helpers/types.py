"""Domain types for the Official Grain Inspection API.

Status enums, entity TypedDicts and the role enum, all named exactly as the PRD
names them.
"""

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# --------------------------------------------------------------------------- #
# Roles
# --------------------------------------------------------------------------- #

class UserRole(str, Enum):
    SERVICE_ADMIN = "ServiceAdmin"
    SUPERVISING_INSPECTOR = "SupervisingInspector"
    LICENSED_INSPECTOR = "LicensedInspector"
    APPLICANT_USER = "ApplicantUser"
    AUDITOR = "Auditor"


# --------------------------------------------------------------------------- #
# Enumerations
# --------------------------------------------------------------------------- #

class AuthorityType(str, Enum):
    DELEGATED = "DELEGATED"
    DESIGNATED = "DESIGNATED"


class ServiceAreaStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ServiceClass(str, Enum):
    GRADING = "GRADING"
    WEIGHING = "WEIGHING"
    PROTEIN = "PROTEIN"
    EXPORT_SUPERVISION = "EXPORT_SUPERVISION"
    APPEAL = "APPEAL"


class FeeScheduleStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class Endorsement(str, Enum):
    SAMPLING = "SAMPLING"
    GRADING = "GRADING"
    PROTEIN = "PROTEIN"
    WEIGHING = "WEIGHING"
    SUPERVISION = "SUPERVISION"


class LicenseStatus(str, Enum):
    PROBATIONARY = "PROBATIONARY"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class EquipmentKind(str, Enum):
    SAMPLING_DEVICE = "SAMPLING_DEVICE"
    SCALE = "SCALE"
    PROTEIN_INSTRUMENT = "PROTEIN_INSTRUMENT"


class ApprovalStatus(str, Enum):
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    DRIFT_WATCH = "DRIFT_WATCH"
    OUT_OF_TOLERANCE = "OUT_OF_TOLERANCE"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"


class Commodity(str, Enum):
    CORN = "CORN"
    SOYBEANS = "SOYBEANS"


class PointOfService(str, Enum):
    LOADING = "LOADING"
    UNLOADING = "UNLOADING"


class GradingStatus(str, Enum):
    OPEN = "OPEN"
    SAMPLED = "SAMPLED"
    GRADED = "GRADED"
    GRADE_CERTIFIED = "GRADE_CERTIFIED"
    UNDER_APPEAL = "UNDER_APPEAL"


class WeighingStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING = "PENDING"
    WEIGHED = "WEIGHED"
    SUPERVISED = "SUPERVISED"
    WEIGHT_CERTIFIED = "WEIGHT_CERTIFIED"


class SampleType(str, Enum):
    ORIGINAL = "ORIGINAL"
    FILE = "FILE"
    APPEAL = "APPEAL"


class IntegrityStatus(str, Enum):
    SEALED = "SEALED"
    CONSUMED = "CONSUMED"
    BROKEN = "BROKEN"
    EXPIRED = "EXPIRED"


class Grade(str, Enum):
    US_NO_1 = "US_NO_1"
    US_NO_2 = "US_NO_2"
    US_NO_3 = "US_NO_3"
    US_NO_4 = "US_NO_4"
    US_NO_5 = "US_NO_5"
    SAMPLE_GRADE = "SAMPLE_GRADE"


class LimitingFactor(str, Enum):
    NONE = "NONE"
    TEST_WEIGHT = "TEST_WEIGHT"
    MOISTURE = "MOISTURE"
    DAMAGED_TOTAL = "DAMAGED_TOTAL"
    HEAT_DAMAGED = "HEAT_DAMAGED"
    FOREIGN_MATERIAL = "FOREIGN_MATERIAL"


class GradingResultStatus(str, Enum):
    FINAL = "FINAL"
    SUPERSEDED = "SUPERSEDED"


class BasisSource(str, Enum):
    INSTRUMENT_MOISTURE = "INSTRUMENT_MOISTURE"
    OFFICIAL_MOISTURE = "OFFICIAL_MOISTURE"


class ProteinAnalysisStatus(str, Enum):
    ACCEPTED = "ACCEPTED"
    RECOMPUTED = "RECOMPUTED"
    REJECTED_CALIBRATION = "REJECTED_CALIBRATION"


class WeighingRecordStatus(str, Enum):
    WEIGHED = "WEIGHED"
    SUPERVISED = "SUPERVISED"
    VOIDED = "VOIDED"


class CertificateType(str, Enum):
    GRADE = "GRADE"
    WEIGHT = "WEIGHT"
    COMBINED = "COMBINED"
    EXPORT_CARGO = "EXPORT_CARGO"
    APPEAL_GRADE = "APPEAL_GRADE"


class CertificateStatus(str, Enum):
    ISSUED = "ISSUED"
    UNDER_APPEAL = "UNDER_APPEAL"
    VOIDED = "VOIDED"
    SUPERSEDED = "SUPERSEDED"


class FeeSettlementStatus(str, Enum):
    UNPAID = "UNPAID"
    PAID = "PAID"
    REVERSED = "REVERSED"


class AppealType(str, Enum):
    REINSPECTION = "REINSPECTION"
    APPEAL = "APPEAL"
    BOARD_APPEAL = "BOARD_APPEAL"


class AppealStatus(str, Enum):
    FILED = "FILED"
    SAMPLE_ASSIGNED = "SAMPLE_ASSIGNED"
    UNDER_REVIEW = "UNDER_REVIEW"
    DECIDED_UPHELD = "DECIDED_UPHELD"
    DECIDED_REVISED = "DECIDED_REVISED"
    DISMISSED = "DISMISSED"


class VoteValue(str, Enum):
    UPHOLD = "UPHOLD"
    REVISE = "REVISE"
    ABSTAIN = "ABSTAIN"


class VesselWatchStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    CLOSED = "CLOSED"
    ABORTED = "ABORTED"


# --------------------------------------------------------------------------- #
# Entity shapes — every resource carries id + created_at; every resource except
# an appeal vote also carries updated_at and version.
# --------------------------------------------------------------------------- #

class ServiceArea(TypedDict):
    id: str
    name: str
    state_code: str
    authority_type: str
    status: str
    fee_multiplier_bp: int
    supervision_required: bool
    concurrent_watch_capacity: int
    open_watch_count: int
    created_at: str
    updated_at: str
    version: int


class FeeSchedule(TypedDict):
    id: str
    service_area_id: str
    service_class: str
    base_fee_cents: int
    per_thousand_bushel_rate_cents: int
    overtime_multiplier_bp: int
    minimum_fee_cents: int
    effective_from: str
    effective_to: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Applicant(TypedDict):
    id: str
    name: str
    account_code: str
    contact_email: str
    credit_limit_cents: int
    charges_total_cents: int
    credits_total_cents: int
    open_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Inspector(TypedDict):
    id: str
    service_area_id: str
    license_number: str
    full_name: str
    endorsements: List[str]
    license_expires_at: str
    license_status: str
    performance_score: int
    training_hours_completed: int
    appeal_reversal_count: int
    check_sample_deviation_count: int
    late_certificate_count: int
    suspension_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Equipment(TypedDict):
    id: str
    service_area_id: str
    equipment_kind: str
    asset_code: str
    model: str
    capacity_lbs: Optional[float]
    tolerance_lbs: Optional[float]
    approval_status: str
    certified_until: Optional[str]
    last_certification_error_lbs: Optional[float]
    recent_deviations_pct: List[float]
    rolling_bias_pct: Optional[float]
    last_comparison_deviation_pct: Optional[float]
    comparison_check_count: int
    consecutive_out_of_tolerance_checks: int
    created_at: str
    updated_at: str
    version: int


class InspectionRequest(TypedDict):
    id: str
    applicant_id: str
    service_area_id: str
    commodity: str
    point_of_service: str
    lot_identifier: str
    declared_quantity_bushels: float
    requested_services: List[str]
    grading_status: str
    weighing_status: str
    grade_revision_count: int
    certified_quantity_bushels: float
    created_at: str
    updated_at: str
    version: int


class Sample(TypedDict):
    id: str
    inspection_request_id: str
    sampling_device_id: str
    inspector_id: str
    sample_type: str
    seal_number: str
    portions_count: int
    portions_consumed: int
    portions_retained: int
    portions_available: int
    integrity_status: str
    collected_at: str
    file_retention_until: str
    created_at: str
    updated_at: str
    version: int


class GradingResult(TypedDict):
    id: str
    inspection_request_id: str
    sample_id: str
    inspector_id: str
    appeal_id: Optional[str]
    test_weight_lbs_per_bushel: float
    moisture_pct: float
    damaged_total_pct: float
    heat_damaged_pct: float
    foreign_material_pct: float
    rounded_factors: Dict[str, float]
    assigned_grade: str
    limiting_factor: str
    status: str
    supersedes_grading_result_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProteinAnalysis(TypedDict):
    id: str
    inspection_request_id: str
    sample_id: str
    instrument_id: str
    inspector_id: str
    protein_pct_as_is: float
    instrument_moisture_pct: float
    basis_source: str
    moisture_source_pct: float
    protein_reported_pct: float
    basis_adjustment_pct: float
    status: str
    sequence_no: int
    created_at: str
    updated_at: str
    version: int


class WeighingRecord(TypedDict):
    id: str
    inspection_request_id: str
    scale_id: str
    weigher_inspector_id: str
    supervisor_inspector_id: Optional[str]
    drafts: List[Dict[str, int]]
    dockage_pct: float
    dockage_lbs: int
    net_lbs: int
    provisional_net_lbs: int
    rounding_variance_lbs: int
    net_bushels: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Certificate(TypedDict):
    id: str
    inspection_request_id: str
    issuing_inspector_id: str
    certificate_type: str
    status: str
    sequence_no: int
    issued_at: str
    grade_snapshot: Optional[str]
    limiting_factor_snapshot: Optional[str]
    net_lbs_snapshot: Optional[int]
    net_bushels_snapshot: Optional[float]
    protein_reported_pct_snapshot: Optional[float]
    certified_quantity_bushels: float
    fee_total_cents: int
    fee_paid_cents: int
    fee_settlement_status: str
    reinspection_deadline_at: str
    appeal_deadline_at: str
    superseded_certificate_id: Optional[str]
    appeal_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Appeal(TypedDict):
    id: str
    certificate_id: str
    applicant_id: str
    appeal_type: str
    round_number: int
    required_panel_size: int
    status: str
    deposit_cents: int
    refund_cents: int
    votes_cast_count: int
    revise_votes_count: int
    uphold_votes_count: int
    abstain_votes_count: int
    effective_votes_count: int
    assigned_sample_id: Optional[str]
    outcome_grade: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AppealVote(TypedDict):
    """A cast vote is an immutable act of a panel member: it carries only `id`
    and `created_at` alongside its own data — no `updated_at`, no `version`."""

    id: str
    appeal_id: str
    inspector_id: str
    vote: str
    rationale: Optional[str]
    created_at: str


class VesselWatch(TypedDict):
    id: str
    inspection_request_id: str
    service_area_id: str
    supervisor_inspector_id: str
    vessel_name: str
    window_start_at: str
    window_end_at: str
    holds_declared: int
    holds_supervised: Optional[int]
    stowage_certified: bool
    status: str
    started_at: Optional[str]
    closed_at: Optional[str]
    supervision_minutes: Optional[int]
    created_at: str
    updated_at: str
    version: int


ANY: Any = None
