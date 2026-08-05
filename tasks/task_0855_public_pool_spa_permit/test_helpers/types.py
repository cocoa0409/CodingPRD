"""Domain types: entity TypedDicts, status enums and the role enum.

Mirrors the resource shapes described in the Public Pool & Spa Health Permit PRD.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------


class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    OPERATOR = "Operator"
    INSPECTOR = "Inspector"
    PLAN_REVIEWER = "PlanReviewer"
    HEALTH_AUTHORITY_ADMIN = "HealthAuthorityAdmin"


# --------------------------------------------------------------------------
# Enumerations
# --------------------------------------------------------------------------


class FacilityClass(str, Enum):
    CLASS_A_COMPETITION = "CLASS_A_COMPETITION"
    CLASS_B_PUBLIC = "CLASS_B_PUBLIC"
    CLASS_C_SEMI_PUBLIC = "CLASS_C_SEMI_PUBLIC"
    SPA = "SPA"


class WaterType(str, Enum):
    POOL = "POOL"
    SPA = "SPA"


class FacilityFeature(str, Enum):
    SLIDE = "SLIDE"
    DIVING_BOARD = "DIVING_BOARD"
    WAVE_GENERATOR = "WAVE_GENERATOR"
    SPA_JETS = "SPA_JETS"
    SPLASH_PAD = "SPLASH_PAD"


class SignageType(str, Enum):
    DEPTH_MARKERS = "DEPTH_MARKERS"
    EMERGENCY_PHONE = "EMERGENCY_PHONE"
    DIARRHEA_NOTICE = "DIARRHEA_NOTICE"
    NO_LIFEGUARD_WARNING = "NO_LIFEGUARD_WARNING"
    SPA_TEMP_WARNING = "SPA_TEMP_WARNING"


class VgbComplianceStatus(str, Enum):
    COMPLIANT = "COMPLIANT"
    EXPIRED = "EXPIRED"
    NONCOMPLIANT = "NONCOMPLIANT"


class OperatingPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    CLOSED = "CLOSED"


class PostureReason(str, Enum):
    CLOSURE_ORDER_OPEN = "CLOSURE_ORDER_OPEN"
    PERMIT_MISSING = "PERMIT_MISSING"
    PERMIT_NOT_ACTIVE = "PERMIT_NOT_ACTIVE"
    OUT_OF_SEASON = "OUT_OF_SEASON"
    VGB_NONCOMPLIANT = "VGB_NONCOMPLIANT"
    CRITICAL_VIOLATION_OPEN = "CRITICAL_VIOLATION_OPEN"
    SIGNAGE_INCOMPLETE = "SIGNAGE_INCOMPLETE"
    LIFEGUARD_COVERAGE_MISSING = "LIFEGUARD_COVERAGE_MISSING"
    NONE = "NONE"


class PlanReviewStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    CORRECTIONS_REQUIRED = "CORRECTIONS_REQUIRED"
    APPROVED = "APPROVED"
    DISAPPROVED = "DISAPPROVED"
    SUPERSEDED = "SUPERSEDED"


class ProjectType(str, Enum):
    NEW_CONSTRUCTION = "NEW_CONSTRUCTION"
    ALTERATION = "ALTERATION"
    EQUIPMENT_REPLACEMENT = "EQUIPMENT_REPLACEMENT"


class PermitStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    ISSUED = "ISSUED"
    DENIED = "DENIED"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class PermitType(str, Enum):
    ANNUAL = "ANNUAL"
    SEASONAL = "SEASONAL"


class FeeVariant(str, Enum):
    FULL_TERM = "FULL_TERM"
    SEASONAL_PRORATED = "SEASONAL_PRORATED"


class SuspensionReason(str, Enum):
    IMMINENT_HEALTH_HAZARD = "IMMINENT_HEALTH_HAZARD"
    ADMINISTRATIVE = "ADMINISTRATIVE"


class InspectionType(str, Enum):
    ROUTINE = "ROUTINE"
    REINSPECTION = "REINSPECTION"
    COMPLAINT = "COMPLAINT"
    PREOPERATIONAL = "PREOPERATIONAL"


class WorkflowStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    SUBMITTED = "SUBMITTED"
    FINALIZED = "FINALIZED"
    VOIDED = "VOIDED"


class EnforcementStatus(str, Enum):
    NONE = "NONE"
    NOTICE_ISSUED = "NOTICE_ISSUED"
    ESCALATED = "ESCALATED"
    CLEARED = "CLEARED"


class InspectionResult(str, Enum):
    PASS = "PASS"
    CONDITIONAL = "CONDITIONAL"
    FAIL = "FAIL"


class Severity(str, Enum):
    IMMINENT_HEALTH_HAZARD = "IMMINENT_HEALTH_HAZARD"
    CRITICAL = "CRITICAL"
    NONCRITICAL = "NONCRITICAL"


class ViolationStatus(str, Enum):
    OPEN = "OPEN"
    CORRECTED = "CORRECTED"
    VERIFIED = "VERIFIED"
    VOIDED = "VOIDED"


class ReadingSource(str, Enum):
    OPERATOR_LOG = "OPERATOR_LOG"
    INSPECTOR_FIELD = "INSPECTOR_FIELD"
    REOPEN_VERIFICATION = "REOPEN_VERIFICATION"


class ComplianceStatus(str, Enum):
    IN_RANGE = "IN_RANGE"
    OUT_OF_RANGE = "OUT_OF_RANGE"
    IMMINENT_HAZARD = "IMMINENT_HAZARD"


class OutOfRangeParameter(str, Enum):
    FREE_CHLORINE_LOW = "FREE_CHLORINE_LOW"
    FREE_CHLORINE_HIGH = "FREE_CHLORINE_HIGH"
    COMBINED_CHLORAMINE_HIGH = "COMBINED_CHLORAMINE_HIGH"
    PH_LOW = "PH_LOW"
    PH_HIGH = "PH_HIGH"
    CYANURIC_ACID_HIGH = "CYANURIC_ACID_HIGH"
    TEMP_HIGH = "TEMP_HIGH"


class ClosureReason(str, Enum):
    FECAL_FORMED = "FECAL_FORMED"
    FECAL_DIARRHEAL = "FECAL_DIARRHEAL"
    VOMIT = "VOMIT"
    BLOOD = "BLOOD"
    CHEMICAL = "CHEMICAL"
    WATER_CHEMISTRY = "WATER_CHEMISTRY"
    EQUIPMENT = "EQUIPMENT"
    RWI_OUTBREAK = "RWI_OUTBREAK"
    PERMIT_ACTION = "PERMIT_ACTION"


class ClosureStatus(str, Enum):
    OPEN = "OPEN"
    REOPEN_REQUESTED = "REOPEN_REQUESTED"
    CLEARED = "CLEARED"
    VOIDED = "VOIDED"


class RemediationVariant(str, Enum):
    FIXED_TABLE = "FIXED_TABLE"
    CT_COMPUTED = "CT_COMPUTED"


class ReopenDenialReason(str, Enum):
    REMEDIATION_INCOMPLETE = "REMEDIATION_INCOMPLETE"
    WATER_NOT_IN_RANGE = "WATER_NOT_IN_RANGE"
    VIOLATIONS_OPEN = "VIOLATIONS_OPEN"


class StaffRoleType(str, Enum):
    LIFEGUARD = "LIFEGUARD"
    ATTENDANT = "ATTENDANT"


class AssignmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CANCELLED = "CANCELLED"


class CancelReason(str, Enum):
    OPERATOR_REQUEST = "OPERATOR_REQUEST"
    FACILITY_CLOSED = "FACILITY_CLOSED"


class ArtifactType(str, Enum):
    SIGNAGE = "SIGNAGE"
    DRAIN_CERTIFICATION = "DRAIN_CERTIFICATION"


class SvaSystemType(str, Enum):
    SVRS = "SVRS"
    GRAVITY_DRAIN_SYSTEM = "GRAVITY_DRAIN_SYSTEM"
    UNBLOCKABLE_DRAIN = "UNBLOCKABLE_DRAIN"
    MULTIPLE_MAIN_DRAINS = "MULTIPLE_MAIN_DRAINS"
    NONE = "NONE"


class ArtifactStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"


class ComplaintType(str, Enum):
    RWI_ILLNESS = "RWI_ILLNESS"
    INJURY = "INJURY"
    WATER_QUALITY = "WATER_QUALITY"
    SANITATION = "SANITATION"
    SAFETY_EQUIPMENT = "SAFETY_EQUIPMENT"


class Pathogen(str, Enum):
    CRYPTOSPORIDIUM = "CRYPTOSPORIDIUM"
    GIARDIA = "GIARDIA"
    LEGIONELLA = "LEGIONELLA"
    PSEUDOMONAS = "PSEUDOMONAS"
    NOROVIRUS = "NOROVIRUS"
    ECOLI = "ECOLI"
    UNKNOWN = "UNKNOWN"


class RiskVariant(str, Enum):
    SINGLE_REPORT = "SINGLE_REPORT"
    CLUSTER_AGGREGATE = "CLUSTER_AGGREGATE"


class ComplaintStatus(str, Enum):
    RECEIVED = "RECEIVED"
    TRIAGED = "TRIAGED"
    INVESTIGATING = "INVESTIGATING"
    SUBSTANTIATED = "SUBSTANTIATED"
    UNSUBSTANTIATED = "UNSUBSTANTIATED"
    CLOSED = "CLOSED"


class LedgerEntryType(str, Enum):
    PERMIT_FEE = "PERMIT_FEE"
    LATE_PENALTY = "LATE_PENALTY"
    PLAN_REVIEW_FEE = "PLAN_REVIEW_FEE"
    REINSPECTION_FEE = "REINSPECTION_FEE"
    PAYMENT = "PAYMENT"
    REFUND = "REFUND"


# --------------------------------------------------------------------------
# Entity shapes
# --------------------------------------------------------------------------


class Operator(TypedDict):
    id: str
    legal_name: str
    contact_email: str
    phone: Optional[str]
    fee_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Facility(TypedDict):
    id: str
    operator_id: str
    name: str
    facility_class: str
    water_type: str
    surface_area_sqft: float
    water_volume_gallons: int
    max_depth_feet: float
    features: List[str]
    drain_count: int
    is_seasonal: bool
    season_start_date: Optional[str]
    season_end_date: Optional[str]
    requires_plan_review: bool
    max_bather_load: int
    lifeguard_required: bool
    required_signage_types: List[str]
    vgb_compliance_status: str
    open_demerit_points: int
    operating_posture: str
    posture_reason: str
    active_permit_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PlanReview(TypedDict):
    id: str
    facility_id: str
    supersedes_plan_review_id: Optional[str]
    project_type: str
    drawing_reference: Optional[str]
    revision_round: int
    status: str
    submitted_on: str
    reviewer_user_id: Optional[str]
    decided_at: Optional[str]
    decided_by_user_id: Optional[str]
    correction_notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Permit(TypedDict):
    id: str
    facility_id: str
    plan_review_id: Optional[str]
    permit_type: str
    term_start_date: str
    term_end_date: str
    term_days: int
    applied_on: str
    is_late_application: bool
    assessed_fee_cents: int
    fee_variant: Optional[str]
    classification_at_issue: Optional[str]
    status: str
    issued_at: Optional[str]
    issued_by_user_id: Optional[str]
    suspension_reason: Optional[str]
    refunded: bool
    created_at: str
    updated_at: str
    version: int


class Inspection(TypedDict):
    id: str
    facility_id: str
    prior_inspection_id: Optional[str]
    inspection_type: str
    inspector_user_id: str
    scheduled_start_at: str
    scheduled_end_at: str
    workflow_status: str
    enforcement_status: str
    started_at: Optional[str]
    submitted_at: Optional[str]
    finalized_at: Optional[str]
    critical_demerits: Optional[int]
    noncritical_demerits: Optional[int]
    score: Optional[int]
    result: Optional[str]
    reinspection_due_on: Optional[str]
    voided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Violation(TypedDict):
    id: str
    inspection_id: str
    code: str
    severity: str
    description: str
    corrected_on_site: bool
    points_assessed: int
    status: str
    corrected_at: Optional[str]
    verified_at: Optional[str]
    rejection_count: int
    created_at: str
    updated_at: str
    version: int


# Append-only observation: carries only id and created_at (no updated_at, no version).
class WaterChemistryReading(TypedDict):
    id: str
    facility_id: str
    sampled_at: str
    source: str
    free_chlorine_ppm: float
    combined_chloramine_ppm: float
    ph: float
    cyanuric_acid_ppm: float
    water_temp_f: float
    compliance_status: str
    out_of_range_parameters: List[str]
    triggered_closure_order_id: Optional[str]
    created_at: str


class ClosureOrder(TypedDict):
    id: str
    facility_id: str
    triggering_reading_id: Optional[str]
    closure_reason: str
    note: Optional[str]
    ordered_by_user_id: str
    ordered_by_role: str
    ordered_at: str
    status: str
    remediation_variant: str
    required_remediation_minutes: int
    earliest_reopen_at: str
    treatment_free_chlorine_ppm: Optional[float]
    treatment_ph: Optional[float]
    verification_reading_id: Optional[str]
    reopen_requested_at: Optional[str]
    reopen_decided_at: Optional[str]
    reopen_decided_by_user_id: Optional[str]
    reopen_denial_reason: Optional[str]
    denial_count: int
    cleared_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StaffAssignment(TypedDict):
    id: str
    facility_id: str
    staff_ref: str
    staff_name: str
    role_type: str
    certification_expires_on: str
    shift_start_at: str
    shift_end_at: str
    status: str
    cancel_reason: Optional[str]
    cancelled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ComplianceArtifact(TypedDict):
    id: str
    facility_id: str
    artifact_type: str
    signage_type: Optional[str]
    drain_cover_model: Optional[str]
    sva_system_type: Optional[str]
    effective_on: str
    expires_on: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Complaint(TypedDict):
    id: str
    facility_id: str
    linked_inspection_id: Optional[str]
    complaint_type: str
    reporter_contact: Optional[str]
    narrative: str
    symptom_onset_date: Optional[str]
    illness_case_count: int
    pathogen_suspected: Optional[str]
    reported_at: str
    risk_variant: Optional[str]
    cluster_case_count: int
    risk_score: int
    escalated: bool
    status: str
    finding: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Append-only posting: carries only id and created_at (no updated_at, no version).
class FeeLedgerEntry(TypedDict):
    id: str
    operator_id: str
    permit_id: Optional[str]
    entry_type: str
    amount_cents: int
    posted_at: str
    reference_note: Optional[str]
    created_at: str
