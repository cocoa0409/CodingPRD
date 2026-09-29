"""Domain types for the IRF Admission & Compliance API.

Entity TypedDicts, status enums and the role enum, derived from the PRD's
resource definitions. Every resource in this API carries `id`, `created_at`,
`updated_at` and `version` (PRD §2.4).
"""

from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------- #
# Roles (PRD §2.1)
# --------------------------------------------------------------------------- #
class UserRole(str, Enum):
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    NURSE_CASE_MANAGER = "NurseCaseManager"
    REHAB_PHYSICIAN = "RehabPhysician"
    THERAPY_LEAD = "TherapyLead"
    HIM_CODER = "HimCoder"


# --------------------------------------------------------------------------- #
# Enumerations
# --------------------------------------------------------------------------- #
class FacilityPosture(str, Enum):
    OPEN = "OPEN"
    THRESHOLD_WATCH = "THRESHOLD_WATCH"
    ADMISSION_FREEZE = "ADMISSION_FREEZE"


class ClinicianCredential(str, Enum):
    REHAB_PHYSICIAN = "REHAB_PHYSICIAN"
    NURSE = "NURSE"
    THERAPIST_PT = "THERAPIST_PT"
    THERAPIST_OT = "THERAPIST_OT"
    THERAPIST_SLP = "THERAPIST_SLP"
    CODER = "CODER"


class ClinicianStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class ComorbidityTier(str, Enum):
    NONE = "NONE"
    TIER_3 = "TIER_3"
    TIER_2 = "TIER_2"
    TIER_1 = "TIER_1"


class ScreeningStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    PHYSICIAN_CONCURRED = "PHYSICIAN_CONCURRED"
    ON_HOLD = "ON_HOLD"
    EXPIRED = "EXPIRED"


class ScreeningDecision(str, Enum):
    CONCUR = "CONCUR"
    REQUEST_CHANGES = "REQUEST_CHANGES"


class StayStatus(str, Enum):
    PENDING = "PENDING"
    ADMITTED = "ADMITTED"
    DISCHARGED = "DISCHARGED"
    ADMISSION_DENIED = "ADMISSION_DENIED"


class PaymentStatus(str, Enum):
    NOT_PRICED = "NOT_PRICED"
    PRICED = "PRICED"
    CONSOLIDATED = "CONSOLIDATED"
    REOPENED = "REOPENED"


class DocumentationStatus(str, Enum):
    INCOMPLETE = "INCOMPLETE"
    POC_SIGNED = "POC_SIGNED"
    PAI_TRANSMITTED = "PAI_TRANSMITTED"


class ComplianceClass(str, Enum):
    PENDING_EVALUATION = "PENDING_EVALUATION"
    QUALIFYING = "QUALIFYING"
    NON_QUALIFYING = "NON_QUALIFYING"
    EXCLUDED = "EXCLUDED"


class CmgTier(str, Enum):
    TIER_A = "TIER_A"
    TIER_B = "TIER_B"
    TIER_C = "TIER_C"


class DischargeDestination(str, Enum):
    COMMUNITY = "COMMUNITY"
    SNF = "SNF"
    ACUTE_CARE = "ACUTE_CARE"
    LTCH = "LTCH"
    ANOTHER_IRF = "ANOTHER_IRF"
    EXPIRED = "EXPIRED"
    AGAINST_MEDICAL_ADVICE = "AGAINST_MEDICAL_ADVICE"


class PlanOfCareStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class ThreeHourRuleMode(str, Enum):
    DAILY_3HR = "DAILY_3HR"
    WEEKLY_15HR = "WEEKLY_15HR"


class Discipline(str, Enum):
    PT = "PT"
    OT = "OT"
    SLP = "SLP"


class TherapyWeekStatus(str, Enum):
    OPEN = "OPEN"
    MET = "MET"
    NOT_MET = "NOT_MET"
    EXCEPTION_GRANTED = "EXCEPTION_GRANTED"


class SessionModality(str, Enum):
    INDIVIDUAL = "INDIVIDUAL"
    CONCURRENT = "CONCURRENT"
    GROUP = "GROUP"


class TherapySessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DELIVERED = "DELIVERED"
    VOIDED = "VOIDED"


class TeamConferenceStatus(str, Enum):
    RECORDED = "RECORDED"
    LATE_RECORDED = "LATE_RECORDED"


class AssessmentType(str, Enum):
    ADMISSION = "ADMISSION"
    DISCHARGE = "DISCHARGE"


class AssessmentStatus(str, Enum):
    DRAFT = "DRAFT"
    COMPLETED = "COMPLETED"
    TRANSMITTED = "TRANSMITTED"
    LATE_TRANSMITTED = "LATE_TRANSMITTED"
    MISSED = "MISSED"


class ComplianceReviewMethod(str, Enum):
    PRESUMPTIVE = "PRESUMPTIVE"
    MEDICAL_REVIEW = "MEDICAL_REVIEW"


class ComplianceReviewStatus(str, Enum):
    DRAFT = "DRAFT"
    COMPUTED = "COMPUTED"
    STALE = "STALE"
    CERTIFIED = "CERTIFIED"


class ComplianceReviewOutcome(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class QrpAssessmentStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"


# --------------------------------------------------------------------------- #
# Entities — every one carries id/created_at/updated_at/version (PRD §2.4)
# --------------------------------------------------------------------------- #
class Facility(TypedDict):
    id: str
    name: str
    cms_ccn: str
    review_period_start: str
    review_period_end: str
    compliance_threshold_pct: float
    daily_therapy_cap_minutes: int
    cohort_total_count: int
    cohort_qualifying_count: int
    provisional_compliance_pct: float
    certified_compliance_pct: Optional[float]
    settled_payment_cents: int
    posture: str
    active_qrp_penalty_pct: float
    qrp_penalty_effective_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Clinician(TypedDict):
    id: str
    facility_id: str
    full_name: str
    credential: str
    npi: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Patient(TypedDict):
    id: str
    facility_id: str
    mrn: str
    full_name: str
    birth_date: str
    impairment_group_code: str
    etiologic_diagnosis_code: str
    comorbidity_tier: str
    created_at: str
    updated_at: str
    version: int


class PreadmissionScreening(TypedDict):
    id: str
    patient_id: str
    conducted_by_clinician_id: str
    reviewed_by_clinician_id: Optional[str]
    conducted_at: str
    expected_admission_at: str
    intensive_therapy_documented: bool
    expected_functional_improvement_documented: bool
    prior_functional_level_documented: bool
    medical_supervision_documented: bool
    reviewed_at: Optional[str]
    reviewer_note: Optional[str]
    revision_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Admission(TypedDict):
    id: str
    facility_id: str
    patient_id: str
    screening_id: str
    predecessor_admission_id: Optional[str]
    payment_consolidated_into_admission_id: Optional[str]
    stay_status: str
    payment_status: str
    documentation_status: str
    admitted_at: Optional[str]
    discharged_at: Optional[str]
    discharge_destination: Optional[str]
    discharge_planned: Optional[bool]
    denial_reason: Optional[str]
    interrupted_stay_flag: bool
    interruption_gap_days: Optional[int]
    cmg_tier: Optional[str]
    effective_los_days: Optional[int]
    total_payment_cents: int
    qrp_penalty_pct_snapshot: float
    screening_window_hours: Optional[float]
    screening_compliant: bool
    poc_signed_within_deadline: bool
    therapy_weeks_satisfied: bool
    conference_compliant: bool
    total_credited_minutes: int
    compliance_class: str
    created_at: str
    updated_at: str
    version: int


class OverallPlanOfCare(TypedDict):
    id: str
    admission_id: str
    authored_by_clinician_id: str
    target_los_days: int
    weekly_minutes_target: int
    disciplines: List[str]
    three_hour_rule_mode: str
    signed_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class TherapyWeek(TypedDict):
    id: str
    admission_id: str
    exception_granted_by_clinician_id: Optional[str]
    week_index: int
    week_start_date: str
    week_end_date: str
    evaluation_mode: str
    delivered_credited_minutes: int
    qualifying_days_count: int
    exception_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class TherapySession(TypedDict):
    id: str
    admission_id: str
    therapy_week_id: str
    clinician_id: str
    discipline: str
    modality: str
    group_size: int
    start_at: str
    end_at: str
    session_date: str
    raw_minutes: int
    credited_minutes: int
    documented_at: Optional[str]
    void_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class TeamConference(TypedDict):
    id: str
    admission_id: str
    therapy_week_id: str
    led_by_clinician_id: str
    participant_clinician_ids: List[str]
    held_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PatientAssessmentInstrument(TypedDict):
    id: str
    admission_id: str
    coder_clinician_id: str
    transmitted_by_clinician_id: Optional[str]
    assessment_type: str
    assessment_reference_date: str
    completion_deadline_at: str
    transmission_deadline_at: str
    item_set_complete: Optional[bool]
    completed_at: Optional[str]
    completion_late: bool
    transmitted_at: Optional[str]
    late_days: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ComplianceReview(TypedDict):
    id: str
    facility_id: str
    method: str
    period_start: str
    period_end: str
    created_by_user_id: str
    certified_by_user_id: Optional[str]
    total_cases: int
    qualifying_cases: int
    compliance_pct: Optional[float]
    outcome: Optional[str]
    computed_at: Optional[str]
    certified_at: Optional[str]
    stale_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class QrpAssessment(TypedDict):
    id: str
    facility_id: str
    fiscal_year: int
    reporting_period_start: str
    reporting_period_end: str
    cohort_count: int
    timely_count: int
    data_completeness_pct: float
    penalty_pct: float
    finalized_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ClockState(TypedDict):
    current_utc: str
    expired_screening_count: int
    missed_assessment_count: int
