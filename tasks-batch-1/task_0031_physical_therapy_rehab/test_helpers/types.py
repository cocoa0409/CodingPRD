"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §3, §4)."""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Status Enums (PRD §3) ───────────────────────────────────────


class PatientStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCHARGED = "DISCHARGED"
    INACTIVE = "INACTIVE"


class PlanOfCareStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RECERT_DUE = "RECERT_DUE"
    DISCHARGED = "DISCHARGED"
    EXPIRED = "EXPIRED"


class CappedStatus(str, Enum):
    UNDER_CAP = "UNDER_CAP"
    AT_CAP_WARNING = "AT_CAP_WARNING"
    EXCEEDED = "EXCEEDED"


class AuthorizationGrantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class VisitStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    FINALIZED = "FINALIZED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class HomeExerciseProgramStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    DISCONTINUED = "DISCONTINUED"


class VeteranReferralStatus(str, Enum):
    ISSUED = "ISSUED"
    CONSUMED = "CONSUMED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class MIPSStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class EvaluationKind(str, Enum):
    INITIAL = "INITIAL"
    RE_EVALUATION = "RE_EVALUATION"
    DISCHARGE = "DISCHARGE"


class CPTCode(str, Enum):
    CPT_97110_THER_EX = "CPT_97110_THER_EX"
    CPT_97112_NEURO_REED = "CPT_97112_NEURO_REED"
    CPT_97140_MANUAL = "CPT_97140_MANUAL"
    CPT_97530_THER_ACT = "CPT_97530_THER_ACT"


class InsuranceType(str, Enum):
    MEDICARE = "MEDICARE"
    COMMERCIAL = "COMMERCIAL"
    MEDICAID = "MEDICAID"
    VA_TRICARE = "VA_TRICARE"
    SELF_PAY = "SELF_PAY"


class MIPSMeasureCode(str, Enum):
    MIPS128_FALL_RISK = "MIPS128_FALL_RISK"
    MIPS131_PAIN_ASSESSMENT = "MIPS131_PAIN_ASSESSMENT"
    MIPS182_FUNCTIONAL_OUTCOME = "MIPS182_FUNCTIONAL_OUTCOME"


class DischargeOutcome(str, Enum):
    SUCCESSFUL = "SUCCESSFUL"
    PARTIAL = "PARTIAL"
    UNSUCCESSFUL = "UNSUCCESSFUL"


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    CASE_MANAGER = "CaseManager"
    THERAPIST = "Therapist"
    BILLING_CLERK = "BillingClerk"
    VA_REFERRAL_COORDINATOR = "VAReferralCoordinator"


# ─── Entity TypedDicts (PRD §2.4, §3.1–§3.8) ─────────────────────
# Every entity declares common_fields true (PRD §2.4): each carries
# id, created_at, updated_at, and version.


class Patient(TypedDict, total=False):
    id: str
    full_name: str
    date_of_birth: str
    insurance_type: str
    is_veteran: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Therapist(TypedDict, total=False):
    id: str
    full_name: str
    npi_number: str
    license_state: str
    medicare_provider_enrolled: bool
    created_at: str
    updated_at: str
    version: int


class VeteranReferral(TypedDict, total=False):
    id: str
    patient_id: str
    referring_va_facility_code: str
    referral_authorization_number: str
    max_authorized_visits: int
    expires_on: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PlanOfCare(TypedDict, total=False):
    id: str
    patient_id: str
    primary_therapist_id: str
    initial_evaluation_id: Optional[str]
    veteran_referral_id: Optional[str]
    diagnosis_icd10: str
    certified_start_date: str
    certified_end_date: str
    status: str
    capped_dollar_limit_cents: Optional[int]
    cumulative_billed_cents: int
    capped_status: str
    created_at: str
    updated_at: str
    version: int


class Evaluation(TypedDict, total=False):
    id: str
    plan_of_care_id: str
    therapist_id: str
    evaluation_kind: str
    performed_on: str
    functional_score: int
    minutes_spent: int
    billable_units: int
    created_at: str
    updated_at: str
    version: int


class AuthorizationGrant(TypedDict, total=False):
    id: str
    plan_of_care_id: str
    veteran_referral_id: Optional[str]
    total_units_granted: int
    units_consumed: int
    units_finalized: int
    effective_from: str
    effective_to: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Visit(TypedDict, total=False):
    id: str
    authorization_grant_id: str
    therapist_id: str
    scheduled_start_utc: str
    scheduled_end_utc: str
    planned_minutes: int
    actual_minutes: Optional[int]
    planned_units: int
    billable_units: int
    billed_cents: int
    cpt_code: str
    status: str
    created_at: str
    updated_at: str
    version: int


class HomeExerciseProgram(TypedDict, total=False):
    id: str
    plan_of_care_id: str
    prescribed_by_therapist_id: str
    exercise_count: int
    weekly_frequency: int
    prescribed_on: str
    status: str
    created_at: str
    updated_at: str
    version: int


class MIPSQualityMeasure(TypedDict, total=False):
    id: str
    patient_id: str
    plan_of_care_id: str
    reporting_therapist_id: str
    measure_code: str
    performance_period_start: str
    performance_period_end: str
    numerator_met: bool
    composite_score: float
    status: str
    created_at: str
    updated_at: str
    version: int


class DischargeAssessment(TypedDict, total=False):
    id: str
    plan_of_care_id: str
    assessing_therapist_id: str
    final_functional_score: int
    goals_met_count: int
    total_goals_count: int
    discharge_outcome: str
    assessed_on: str
    created_at: str
    updated_at: str
    version: int
