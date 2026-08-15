"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.5, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    NURSE = "EmployeeHealthNurse"
    PHYSICIAN = "EmployeeHealthPhysician"
    COMPLIANCE = "ComplianceOfficer"
    SAFETY = "SafetyOfficer"
    STAFF = "StaffEmployee"


class EmployeeStatus(str, Enum):
    PREPLACEMENT = "PREPLACEMENT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class CompliancePosture(str, Enum):
    CLEAR = "CLEAR"
    ON_HOLD = "ON_HOLD"
    WORK_EXCLUDED = "WORK_EXCLUDED"
    RESTRICTED_DUTY = "RESTRICTED_DUTY"


class ScreeningStatus(str, Enum):
    IN_PROGRESS = "IN_PROGRESS"
    CLEARED = "CLEARED"
    FAILED = "FAILED"
    VOID = "VOID"


class ImmunityStatus(str, Enum):
    IMMUNE = "IMMUNE"
    NON_IMMUNE = "NON_IMMUNE"
    EQUIVOCAL = "EQUIVOCAL"


class CycleStatus(str, Enum):
    OPEN = "OPEN"
    OVERDUE = "OVERDUE"
    SATISFIED = "SATISFIED"


class HoldStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class CaseStatus(str, Enum):
    REPORTED = "REPORTED"
    EVALUATION = "EVALUATION"
    MANAGEMENT = "MANAGEMENT"
    CLOSED = "CLOSED"
    SEROCONVERTED = "SEROCONVERTED"


class SourceTestStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    CONSENT_PENDING = "CONSENT_PENDING"
    CONSENT_GRANTED = "CONSENT_GRANTED"
    RESULTED = "RESULTED"
    CONSENT_DECLINED = "CONSENT_DECLINED"
    WAIVED_UNABLE = "WAIVED_UNABLE"


class PepStatus(str, Enum):
    RECOMMENDED = "RECOMMENDED"
    STARTED = "STARTED"
    COMPLETED = "COMPLETED"
    DECLINED = "DECLINED"
    WINDOW_EXPIRED = "WINDOW_EXPIRED"


class FollowUpStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DUE = "DUE"
    OVERDUE = "OVERDUE"
    RESULTED = "RESULTED"
    WAIVED = "WAIVED"


class RestrictionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LIFTED = "LIFTED"
    EXPIRED = "EXPIRED"


class ClearanceStatus(str, Enum):
    PENDING = "PENDING"
    CLEARED = "CLEARED"
    DENIED = "DENIED"


class EventStatus(str, Enum):
    OPEN = "OPEN"
    TRACING = "TRACING"
    MONITORING = "MONITORING"
    ESCALATED = "ESCALATED"
    CLOSED = "CLOSED"


class ContactStatus(str, Enum):
    MONITORING = "MONITORING"
    CLEARED = "CLEARED"
    CONVERTED_TO_CASE = "CONVERTED_TO_CASE"
    LOST_TO_FOLLOWUP = "LOST_TO_FOLLOWUP"


class InjuryStatus(str, Enum):
    FILED = "FILED"
    WC_SUBMITTED = "WC_SUBMITTED"
    WC_ACCEPTED = "WC_ACCEPTED"
    WC_DENIED = "WC_DENIED"
    APPEALED = "APPEALED"


class CampaignStatus(str, Enum):
    PLANNED = "PLANNED"
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class ParticipationStatus(str, Enum):
    PENDING = "PENDING"
    ADMINISTERED = "ADMINISTERED"
    DECLINED = "DECLINED"
    EXEMPTED = "EXEMPTED"
    DELINQUENT = "DELINQUENT"


class Employee(TypedDict, total=False):
    id: str
    employee_ref: str
    full_name: str
    job_category: str
    department: str
    hire_date: str
    requires_respirator: bool
    status: str
    compliance_posture: str
    active_hold_count: int
    open_restriction_count: int
    created_at: str
    updated_at: str
    version: int


class PrePlacementScreening(TypedDict, total=False):
    id: str
    employee_id: str
    status: str
    physical_completed_at: Optional[str]
    tb_baseline_completed_at: Optional[str]
    med_eval_completed_at: Optional[str]
    decided_by_user_id: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Append-only laboratory record (PRD §2.5): carries ONLY id + created_at among
# the common fields — no updated_at, no version.
class TiterResult(TypedDict, total=False):
    id: str
    employee_id: str
    screening_id: Optional[str]
    disease: str
    assay_type: str
    numeric_value: Optional[float]
    qualitative_result: Optional[str]
    resulted_at: str
    immunity_status: str
    created_at: str


class AnnualRequirementCycle(TypedDict, total=False):
    id: str
    employee_id: str
    cycle_year: int
    cycle_mode: str
    tb_due_date: str
    fit_test_due_date: Optional[str]
    tb_completed_at: Optional[str]
    fit_test_completed_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ComplianceHold(TypedDict, total=False):
    id: str
    employee_id: str
    cycle_id: Optional[str]
    participation_id: Optional[str]
    reason: str
    status: str
    applied_at: str
    released_at: Optional[str]
    released_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ExposureCase(TypedDict, total=False):
    id: str
    employee_id: str
    exposure_type: str
    exposure_datetime: str
    reported_at: str
    source_known: bool
    source_patient_ref: Optional[str]
    body_fluid: str
    risk_classification: str
    case_status: str
    source_test_status: str
    pep_required: bool
    hiv_result: str
    hbv_result: str
    hcv_result: str
    source_resulted_at: Optional[str]
    recorded_by_user_id: str
    consent_recorded_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PEPRegimen(TypedDict, total=False):
    id: str
    exposure_case_id: str
    medication: str
    recommended_at: str
    window_deadline: str
    started_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SerologyFollowUp(TypedDict, total=False):
    id: str
    exposure_case_id: str
    milestone: str
    scheduled_date: str
    window_open: str
    window_close: str
    result: str
    resulted_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class WorkRestriction(TypedDict, total=False):
    id: str
    employee_id: str
    exposure_case_id: Optional[str]
    restriction_type: str
    start_date: str
    end_date: Optional[str]
    status: str
    origin: str
    created_at: str
    updated_at: str
    version: int


class ReturnToWorkClearance(TypedDict, total=False):
    id: str
    restriction_id: str
    status: str
    requested_by_user_id: str
    decided_by_user_id: Optional[str]
    decided_at: Optional[str]
    decision_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CommunicableEvent(TypedDict, total=False):
    id: str
    index_employee_id: str
    disease: str
    onset_date: str
    infectious_start: str
    monitoring_window_days: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ExposureContact(TypedDict, total=False):
    id: str
    event_id: str
    contact_employee_id: str
    contact_date: str
    monitoring_start: str
    monitoring_end: str
    symptom_onset_reported: bool
    symptom_onset_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class InjuryReport(TypedDict, total=False):
    id: str
    employee_id: str
    exposure_case_id: Optional[str]
    injury_type: str
    injury_datetime: str
    origin: str
    osha_recordable: bool
    wc_claim_number: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class VaccinationCampaign(TypedDict, total=False):
    id: str
    vaccine_type: str
    window_start: str
    window_end: str
    department_scope: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CampaignParticipation(TypedDict, total=False):
    id: str
    campaign_id: str
    employee_id: str
    status: str
    administered_at: Optional[str]
    declined_at: Optional[str]
    declination_reason: Optional[str]
    exemption_type: Optional[str]
    created_at: str
    updated_at: str
    version: int
