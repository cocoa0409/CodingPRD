"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import Optional, TypedDict


# ─── Roles (PRD §2.1) ────────────────────────────────────────────────
class UserRole(str, Enum):
    FIRM_ADMIN = "FirmAdmin"
    INDUSTRIAL_HYGIENIST = "IndustrialHygienist"
    CIH_DIRECTOR = "CIHDirector"
    FIELD_TECHNICIAN = "FieldTechnician"
    LAB_ANALYST = "LabAnalyst"
    SITE_SAFETY_MANAGER = "SiteSafetyManager"
    EMPLOYEE = "Employee"


# ─── Input enums ─────────────────────────────────────────────────────
class LimitBasis(str, Enum):
    OSHA_PEL = "OSHA_PEL"
    ACGIH_TLV = "ACGIH_TLV"


class LimitType(str, Enum):
    TWA8 = "TWA8"
    CEILING = "CEILING"


class PlanPurpose(str, Enum):
    INITIAL = "INITIAL"
    FOLLOWUP = "FOLLOWUP"
    VERIFICATION = "VERIFICATION"


class UnsampledTimeRule(str, Enum):
    ZERO_FILL = "ZERO_FILL"
    WORST_CASE = "WORST_CASE"


class VolumeBasis(str, Enum):
    MEAN_FLOW = "MEAN_FLOW"
    PRE_FLOW = "PRE_FLOW"


class SampleType(str, Enum):
    PERSONAL = "PERSONAL"
    FIELD_BLANK = "FIELD_BLANK"


class ControlType(str, Enum):
    ENGINEERING = "ENGINEERING"
    ADMINISTRATIVE = "ADMINISTRATIVE"
    PPE_RESPIRATOR = "PPE_RESPIRATOR"


class ControlPriority(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


# ─── Status enums (PRD §3) ───────────────────────────────────────────
class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    FIELD_COMPLETE = "FIELD_COMPLETE"
    LAB_COMPLETE = "LAB_COMPLETE"


class SampleStatus(str, Enum):
    COLLECTED = "COLLECTED"
    SEALED = "SEALED"
    ANALYZED = "ANALYZED"
    INVALIDATED = "INVALIDATED"


class InvalidateReason(str, Enum):
    MANUAL = "MANUAL"
    PUMP_DRIFT = "PUMP_DRIFT"
    BLANK_CONTAMINATION = "BLANK_CONTAMINATION"


class CalibrationResult(str, Enum):
    PENDING = "PENDING"
    VALID = "VALID"
    INVALID = "INVALID"


class ExposureClass(str, Enum):
    NONE = "NONE"
    BELOW_ACTION = "BELOW_ACTION"
    BELOW_PEL_MONITOR = "BELOW_PEL_MONITOR"
    UNCERTAIN = "UNCERTAIN"
    ABOVE_PEL = "ABOVE_PEL"


class SubstitutionRule(str, Enum):
    SQRT2 = "SQRT2"
    HALF = "HALF"


class ReviewStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    SIGNED = "SIGNED"
    SUPERSEDED = "SUPERSEDED"
    VOID = "VOID"
    ARCHIVED = "ARCHIVED"


class ControlStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    IMPLEMENTED = "IMPLEMENTED"
    VERIFIED = "VERIFIED"


class NotificationStatus(str, Enum):
    PENDING = "PENDING"
    SENT = "SENT"
    OVERDUE = "OVERDUE"
    ACKNOWLEDGED = "ACKNOWLEDGED"


class ClearanceStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CLEARED = "CLEARED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"


class FitTestStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PASSED = "PASSED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"


# ─── Entity TypedDicts ───────────────────────────────────────────────
# Every resource carries id/created_at/updated_at/version (PRD §2.4).
class ClientSite(TypedDict, total=False):
    id: str
    name: str
    industry_code: str
    retention_years: int
    created_at: str
    updated_at: str
    version: int


class Employee(TypedDict, total=False):
    id: str
    site_id: str
    full_name: str
    external_ref: str
    job_title: str
    created_at: str
    updated_at: str
    version: int


class ExposureLimit(TypedDict, total=False):
    id: str
    analyte_code: str
    basis: str
    limit_type: str
    limit_mg_m3: float
    action_fraction: float
    created_at: str
    updated_at: str
    version: int


class SimilarExposureGroup(TypedDict, total=False):
    id: str
    site_id: str
    name: str
    analyte_code: str
    exposure_limit_id: str
    task_description: str
    headcount: int
    current_class: str
    next_sample_due_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SEGMembership(TypedDict, total=False):
    id: str
    seg_id: str
    employee_id: str
    is_primary: bool
    created_at: str
    updated_at: str
    version: int


class SamplingPlan(TypedDict, total=False):
    id: str
    seg_id: str
    purpose: str
    planned_start_date: str
    planned_end_date: str
    unsampled_time_rule: str
    volume_basis: str
    required_sample_count: int
    active_sample_count: int
    analyzed_valid_count: int
    created_by_user_id: str
    approved_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Pump(TypedDict, total=False):
    id: str
    site_id: str
    serial_number: str
    created_at: str
    updated_at: str
    version: int


class PumpCalibration(TypedDict, total=False):
    id: str
    pump_id: str
    pre_flow_lpm: float
    post_flow_lpm: Optional[float]
    drift_pct: Optional[float]
    result: str
    performed_by_user_id: str
    linked_sample_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FieldSample(TypedDict, total=False):
    id: str
    sampling_plan_id: str
    sample_type: str
    employee_id: Optional[str]
    pump_id: Optional[str]
    pre_calibration_id: Optional[str]
    collection_date: str
    start_minute: int
    duration_minutes: int
    collected_by_user_id: str
    status: str
    invalidate_reason: Optional[str]
    air_volume_liters: Optional[float]
    concentration_mg_m3: Optional[float]
    sample_twa_mg_m3: Optional[float]
    is_detect: Optional[bool]
    created_at: str
    updated_at: str
    version: int


class LabBatch(TypedDict, total=False):
    id: str
    site_id: str
    analyte_code: str
    lod_ug: float
    loq_ug: float
    window_start_date: str
    window_end_date: str
    max_capacity: int
    intake_count: int
    contaminated: bool
    created_at: str
    updated_at: str
    version: int


class LabResult(TypedDict, total=False):
    id: str
    field_sample_id: str
    lab_batch_id: str
    mass_ug: float
    entered_by_user_id: str
    reported_at: str
    is_detect: bool
    is_quantifiable: bool
    created_at: str
    updated_at: str
    version: int


class ExposureAssessment(TypedDict, total=False):
    id: str
    seg_id: str
    sampling_plan_id: str
    supersedes_assessment_id: Optional[str]
    n_valid: int
    substitution_rule: str
    geo_mean: Optional[float]
    gsd: Optional[float]
    ucl95: Optional[float]
    lcl95: Optional[float]
    exposure_class: str
    adjusted_class: Optional[str]
    review_status: str
    is_current: bool
    prepared_by_user_id: str
    signed_by_user_id: Optional[str]
    signed_at: Optional[str]
    retention_until: Optional[str]
    legal_hold: bool
    created_at: str
    updated_at: str
    version: int


class ControlRecommendation(TypedDict, total=False):
    id: str
    exposure_assessment_id: str
    control_type: str
    description: str
    priority: str
    assigned_protection_factor: Optional[float]
    auto_created: bool
    verification_plan_id: Optional[str]
    implemented_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class EmployeeNotification(TypedDict, total=False):
    id: str
    employee_id: str
    exposure_assessment_id: str
    due_date: str
    status: str
    sent_at: Optional[str]
    sent_by_user_id: Optional[str]
    acknowledged_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MedicalClearance(TypedDict, total=False):
    id: str
    employee_id: str
    status: str
    decided_at: Optional[str]
    expiry_date: Optional[str]
    decided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RespiratorFitTest(TypedDict, total=False):
    id: str
    employee_id: str
    medical_clearance_id: str
    respirator_model: str
    test_date: str
    expiry_date: str
    status: str
    recorded_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int
