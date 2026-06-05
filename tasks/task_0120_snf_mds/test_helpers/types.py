"""Domain types for the SNF-MDS API: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional


# ─── Role enum (PRD §2.1) ──────────────────────────────
class UserRole(str, Enum):
    ADMINISTRATOR = "Administrator"
    ADMISSIONS_COORDINATOR = "AdmissionsCoordinator"
    MDS_COORDINATOR = "MdsCoordinator"
    THERAPIST = "Therapist"
    PHYSICIAN = "Physician"
    BILLING_ANALYST = "BillingAnalyst"


# ─── Status enums (PRD §3) ─────────────────────────────
class ResidentStatus(str, Enum):
    PROSPECTIVE = "PROSPECTIVE"
    ADMITTED = "ADMITTED"
    ON_LEAVE = "ON_LEAVE"
    DISCHARGED = "DISCHARGED"


class PasrrStatus(str, Enum):
    PENDING = "PENDING"
    CLEARED = "CLEARED"
    DENIED = "DENIED"
    ESCALATED = "ESCALATED"


class AdmissionStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    NON_COVERED = "NON_COVERED"
    DISCHARGE_PLANNED = "DISCHARGE_PLANNED"
    DISCHARGED = "DISCHARGED"


class AssessmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    SUBMITTED = "SUBMITTED"
    SUPERSEDED = "SUPERSEDED"


class CarePlanStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    UNDER_REVIEW = "UNDER_REVIEW"
    CLOSED = "CLOSED"


class CarePlanGoalStatus(str, Enum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    MET = "MET"
    DISCONTINUED = "DISCONTINUED"


class BedHoldStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    CONVERTED_TO_DISCHARGE = "CONVERTED_TO_DISCHARGE"


class ClaimStatus(str, Enum):
    DRAFT = "DRAFT"
    ESTIMATED = "ESTIMATED"
    FINALIZED = "FINALIZED"
    SUBMITTED = "SUBMITTED"
    PAID = "PAID"
    REJECTED = "REJECTED"


# ─── Entity TypedDicts ─────────────────────────────────
# Entities carrying the full common-field set: id, created_at, updated_at, version.

class Facility(TypedDict):
    id: str
    name: str
    cms_certification_number: str
    certified_bed_count: int
    occupied_bed_count: int
    health_inspection_rating: int
    staffing_rating: int
    quality_measure_rating: int
    overall_star_rating: int
    created_at: str
    updated_at: str
    version: int


class PdpmRate(TypedDict):
    id: str
    component: str
    case_mix_group: str
    case_mix_index: float
    base_rate_cents: int
    effective_from: str
    active: bool
    created_at: str
    updated_at: str
    version: int


class Resident(TypedDict):
    id: str
    full_name: str
    medical_record_number: str
    date_of_birth: str
    primary_facility_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PasrrScreening(TypedDict):
    id: str
    resident_id: str
    level: str
    has_serious_mental_illness_indicator: bool
    status: str
    outcome_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Admission(TypedDict):
    id: str
    resident_id: str
    facility_id: str
    pasrr_screening_id: str
    qualifying_stay_id: Optional[str]
    payer_source: str
    admit_at: str
    medicare_covered: bool
    covered_day_count: int
    status: str
    discharge_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MdsAssessment(TypedDict):
    id: str
    admission_id: str
    assessment_type: str
    target_day: int
    assessment_reference_date: str
    corrects_assessment_id: Optional[str]
    pt_function_score: int
    slp_components_count: int
    nta_comorbidity_points: int
    pt_ot_case_mix_group: Optional[str]
    slp_case_mix_group: Optional[str]
    nta_case_mix_group: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class TherapyLog(TypedDict):
    id: str
    admission_id: str
    discipline: str
    mode: str
    minutes: int
    session_date: str
    individual_equivalent_minutes: int
    created_at: str
    updated_at: str
    version: int


class CarePlan(TypedDict):
    id: str
    admission_id: str
    review_interval_days: int
    last_reviewed_at: Optional[str]
    open_goal_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CarePlanGoal(TypedDict):
    id: str
    care_plan_id: str
    description: str
    target_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class BedHold(TypedDict):
    id: str
    admission_id: str
    leave_reason: str
    leave_start_at: str
    expected_return_at: str
    actual_return_at: Optional[str]
    leave_day_count: int
    paid_day_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict):
    id: str
    admission_id: str
    driving_assessment_id: str
    period_start_at: str
    period_end_at: str
    billed_day_count: int
    estimated_amount_cents: int
    final_amount_cents: int
    variance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class QualityMeasure(TypedDict):
    id: str
    facility_id: str
    measure_code: str
    numerator: int
    denominator: int
    reporting_period: str
    measure_points: int
    created_at: str
    updated_at: str
    version: int


# common_fields:false — QualifyingStay carries ONLY id + created_at
# (PRD §2.4: "A QualifyingStay carries only id and created_at; it has neither
#  an updated_at nor a version field"). No updated_at, no version here.
class QualifyingStay(TypedDict):
    id: str
    resident_id: str
    hospital_admit_at: str
    hospital_discharge_at: str
    midnights_count: int
    qualifies: bool
    created_at: str
