"""Domain types for the Cancer Program Accreditation & Tumor Registry Abstraction API.

Entity TypedDicts, state enums and the role enum, all named exactly as the PRD
names them.
"""

from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    """The seven roles recognised by the system (PRD 2.1)."""

    PLATFORM_ADMIN = "PlatformAdmin"
    REGISTRY_MANAGER = "RegistryManager"
    REGISTRY_ABSTRACTOR = "RegistryAbstractor"
    QA_REVIEWER = "QaReviewer"
    ACCREDITATION_COORDINATOR = "AccreditationCoordinator"
    STATE_REGISTRY_LIAISON = "StateRegistryLiaison"
    COC_SURVEYOR = "CoCSurveyor"


class AccreditationState(str, Enum):
    ACCREDITED = "ACCREDITED"
    SURVEY_SCHEDULED = "SURVEY_SCHEDULED"
    DEFICIENCY_RESPONSE = "DEFICIENCY_RESPONSE"
    PROBATION = "PROBATION"
    WITHDRAWN = "WITHDRAWN"


class RegistryPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class SourceType(str, Enum):
    PATHOLOGY = "PATHOLOGY"
    DISEASE_INDEX = "DISEASE_INDEX"
    RADIATION_ONCOLOGY = "RADIATION_ONCOLOGY"
    MEDICAL_ONCOLOGY = "MEDICAL_ONCOLOGY"
    AUTOPSY = "AUTOPSY"


class BehaviorCode(str, Enum):
    BENIGN_0 = "BENIGN_0"
    BORDERLINE_1 = "BORDERLINE_1"
    IN_SITU_2 = "IN_SITU_2"
    MALIGNANT_3 = "MALIGNANT_3"


class ClassOfCase(str, Enum):
    CLASS_00 = "CLASS_00"
    CLASS_10 = "CLASS_10"
    CLASS_20 = "CLASS_20"
    CLASS_31 = "CLASS_31"
    CLASS_40 = "CLASS_40"


class Reportability(str, Enum):
    REPORTABLE = "REPORTABLE"
    NON_REPORTABLE = "NON_REPORTABLE"


class ReportabilityState(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    REPORTABLE = "REPORTABLE"
    NON_REPORTABLE = "NON_REPORTABLE"


class SuggestedReasonCode(str, Enum):
    BEFORE_REFERENCE_YEAR = "BEFORE_REFERENCE_YEAR"
    SKIN_SQUAMOUS_BASAL_EXCLUDED = "SKIN_SQUAMOUS_BASAL_EXCLUDED"
    CERVIX_IN_SITU_EXCLUDED = "CERVIX_IN_SITU_EXCLUDED"
    SEER_REPORTABLE_BEHAVIOR = "SEER_REPORTABLE_BEHAVIOR"
    CNS_BENIGN_REPORTABLE = "CNS_BENIGN_REPORTABLE"
    BENIGN_NON_CNS = "BENIGN_NON_CNS"


class CaseState(str, Enum):
    IDENTIFIED = "IDENTIFIED"
    ASSIGNED = "ASSIGNED"
    IN_ABSTRACTION = "IN_ABSTRACTION"
    QA_PENDING = "QA_PENDING"
    REWORK_PENDING = "REWORK_PENDING"
    COMPLETED = "COMPLETED"
    VOIDED = "VOIDED"


class CaseSubmissionState(str, Enum):
    NOT_SUBMITTED = "NOT_SUBMITTED"
    PENDING_SUBMISSION = "PENDING_SUBMISSION"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    EDIT_REJECTED = "EDIT_REJECTED"


class TimelinessStatus(str, Enum):
    ON_TIME = "ON_TIME"
    AT_RISK = "AT_RISK"
    LATE = "LATE"


class FollowUpStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    CURRENT = "CURRENT"
    DELINQUENT = "DELINQUENT"
    LOST = "LOST"
    CLOSED_DECEASED = "CLOSED_DECEASED"


class VitalStatus(str, Enum):
    ALIVE = "ALIVE"
    DEAD = "DEAD"
    UNKNOWN = "UNKNOWN"


class Credential(str, Enum):
    CTR = "CTR"
    NON_CTR = "NON_CTR"
    TRAINEE = "TRAINEE"


class EmploymentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED_FROM_ABSTRACTING = "SUSPENDED_FROM_ABSTRACTING"
    LOA = "LOA"
    TERMINATED = "TERMINATED"


class ProductivityStatus(str, Enum):
    MEETS = "MEETS"
    BELOW = "BELOW"


class AbstractionState(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED_FOR_QA = "SUBMITTED_FOR_QA"
    REWORK_REQUIRED = "REWORK_REQUIRED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class StageSource(str, Enum):
    CLINICAL = "CLINICAL"
    PATHOLOGIC = "PATHOLOGIC"


class StageGroup(str, Enum):
    STAGE_0 = "STAGE_0"
    STAGE_I = "STAGE_I"
    STAGE_II = "STAGE_II"
    STAGE_III = "STAGE_III"
    STAGE_IV = "STAGE_IV"
    OCCULT = "OCCULT"
    UNKNOWN = "UNKNOWN"


class TreatmentModality(str, Enum):
    SURGERY = "SURGERY"
    RADIATION = "RADIATION"
    CHEMOTHERAPY = "CHEMOTHERAPY"
    HORMONE = "HORMONE"
    IMMUNOTHERAPY = "IMMUNOTHERAPY"
    NO_TREATMENT = "NO_TREATMENT"


class OutcomeStatus(str, Enum):
    ALIVE_NO_EVIDENCE = "ALIVE_NO_EVIDENCE"
    ALIVE_WITH_DISEASE = "ALIVE_WITH_DISEASE"
    DEAD_OF_DISEASE = "DEAD_OF_DISEASE"
    DEAD_OTHER_CAUSE = "DEAD_OTHER_CAUSE"
    UNKNOWN = "UNKNOWN"


class QaVerdict(str, Enum):
    APPROVED = "APPROVED"
    REWORK_REQUIRED = "REWORK_REQUIRED"
    REJECTED = "REJECTED"


class AuditState(str, Enum):
    OPEN = "OPEN"
    CLOSED_PASS = "CLOSED_PASS"
    CLOSED_FAIL = "CLOSED_FAIL"
    VOIDED = "VOIDED"


class AuditType(str, Enum):
    ROUTINE_10PCT = "ROUTINE_10PCT"
    TARGETED = "TARGETED"
    PRE_SURVEY = "PRE_SURVEY"


class AuditVerdict(str, Enum):
    PASS = "PASS"
    MINOR_FAIL = "MINOR_FAIL"
    CRITICAL_FAIL = "CRITICAL_FAIL"


class ContactMethod(str, Enum):
    CLINIC_VISIT = "CLINIC_VISIT"
    LETTER = "LETTER"
    PHONE = "PHONE"
    DEATH_CERTIFICATE = "DEATH_CERTIFICATE"
    STATE_LINKAGE = "STATE_LINKAGE"


class ContactOutcome(str, Enum):
    CONTACT_MADE = "CONTACT_MADE"
    NO_RESPONSE = "NO_RESPONSE"
    DECEASED = "DECEASED"
    MOVED_UNKNOWN = "MOVED_UNKNOWN"


class SubmissionState(str, Enum):
    DRAFT = "DRAFT"
    HOLD = "HOLD"
    TRANSMITTED = "TRANSMITTED"
    EDITS_RETURNED = "EDITS_RETURNED"
    ACCEPTED = "ACCEPTED"


class ItemEditStatus(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    EDIT_FAILED = "EDIT_FAILED"
    RESOLVED = "RESOLVED"


class SessionState(str, Enum):
    SCHEDULED = "SCHEDULED"
    HELD = "HELD"
    CREDITED = "CREDITED"
    NOT_CREDITED = "NOT_CREDITED"


class Discipline(str, Enum):
    SURGERY = "SURGERY"
    MEDICAL_ONCOLOGY = "MEDICAL_ONCOLOGY"
    RADIATION_ONCOLOGY = "RADIATION_ONCOLOGY"
    PATHOLOGY = "PATHOLOGY"
    RADIOLOGY = "RADIOLOGY"


class MeasureState(str, Enum):
    DRAFT = "DRAFT"
    MEASURED = "MEASURED"
    PROJECT_REQUIRED = "PROJECT_REQUIRED"
    PROJECT_ACTIVE = "PROJECT_ACTIVE"
    PROJECT_CLOSED_ACHIEVED = "PROJECT_CLOSED_ACHIEVED"
    PROJECT_CLOSED_MISSED = "PROJECT_CLOSED_MISSED"


class PerformanceState(str, Enum):
    NOT_EVALUATED = "NOT_EVALUATED"
    EXCEEDS = "EXCEEDS"
    MEETS = "MEETS"
    UNDER_THRESHOLD = "UNDER_THRESHOLD"


class Severity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class DeficiencyState(str, Enum):
    CITED = "CITED"
    RESPONSE_SUBMITTED = "RESPONSE_SUBMITTED"
    RESPONSE_REJECTED = "RESPONSE_REJECTED"
    RESOLVED = "RESOLVED"
    ESCALATED = "ESCALATED"


class CancerProgram(TypedDict, total=False):
    id: str
    name: str
    coc_program_id: str
    annual_analytic_caseload: int
    reference_year: int
    timeliness_standard_days: int
    accreditation_state: str
    registry_posture: str
    identified_case_count: int
    open_backlog_count: int
    overdue_backlog_count: int
    open_critical_deficiency_count: int
    follow_up_rate_coc_pct: float
    follow_up_rate_state_pct: float
    lost_to_follow_up_pct: float
    required_sessions_12mo: int
    credited_sessions_12mo: int
    conference_frequency_compliant: bool
    coordinator_attendance_compliant: bool
    survey_date: Optional[str]
    survey_year: Optional[int]
    next_survey_due_year: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Abstractor(TypedDict, total=False):
    id: str
    program_id: str
    name: str
    credential: str
    employment_status: str
    productivity_target_cases_per_day: float
    certification_expires_on: str
    assigned_open_case_count: int
    lifetime_discrepancy_points: int
    audit_fail_streak: int
    completed_cases_30d: int
    quality_score_rolling_90d: float
    quality_score_cumulative: float
    productivity_rate_per_day: float
    productivity_status: str
    created_at: str
    updated_at: str
    version: int


class CasefindingSource(TypedDict, total=False):
    id: str
    program_id: str
    source_type: str
    expected_monthly_volume: int
    entries_this_month: int
    casefinding_completeness_pct: float
    last_reconciled_through: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CasefindingEntry(TypedDict, total=False):
    id: str
    source_id: str
    program_id: str
    patient_mrn: str
    accession_date: str
    primary_site_code: str
    histology_code: str
    behavior_code: str
    diagnosis_date: str
    first_contact_date: str
    diagnosed_at_facility: bool
    first_treatment_at_facility: bool
    ambiguous_terminology_flag: bool
    referral_lag_days: int
    class_of_case_code: str
    analytic_flag: bool
    suggested_reportability: str
    suggested_reason_code: str
    reportability_state: str
    decision_reason_code: Optional[str]
    override_reason_code: Optional[str]
    decided_by_user_id: Optional[str]
    created_case_id: Optional[str]
    reopen_count: int
    created_at: str
    updated_at: str
    version: int


class TumorCase(TypedDict, total=False):
    id: str
    entry_id: str
    program_id: str
    patient_mrn: str
    class_of_case_code: str
    analytic_flag: bool
    diagnosis_date: str
    first_contact_date: str
    sequence_number: int
    accession_number: str
    case_state: str
    submission_state: str
    assigned_abstractor_id: Optional[str]
    abstract_due_date: str
    days_to_due: int
    timeliness_status: str
    completed_on: Optional[str]
    vital_status: str
    last_contact_date: Optional[str]
    follow_up_due_date: Optional[str]
    follow_up_status: str
    created_at: str
    updated_at: str
    version: int


class Abstraction(TypedDict, total=False):
    id: str
    case_id: str
    abstractor_id: str
    abstraction_state: str
    supersedes_abstraction_id: Optional[str]
    stage_source: Optional[str]
    t_category: Optional[str]
    n_category: Optional[str]
    m_category: Optional[str]
    stage_group: Optional[str]
    first_treatment_date: Optional[str]
    treatment_modalities: List[str]
    radiation_start_date: Optional[str]
    diagnostic_confirmation_code: Optional[str]
    outcome_status: Optional[str]
    last_contact_date: Optional[str]
    completeness_score: int
    missing_required_fields: List[str]
    rework_round: int
    submitted_at: Optional[str]
    approved_at: Optional[str]
    qa_reviewer_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class QaAudit(TypedDict, total=False):
    id: str
    abstraction_id: str
    auditor_id: str
    audit_type: str
    window_start: str
    window_end: str
    audit_state: str
    audited_field_count: int
    minor_discrepancy_count: int
    major_discrepancy_count: int
    critical_discrepancy_count: int
    weighted_error_score: int
    verdict: Optional[str]
    cascade_applied: bool
    scored_at: Optional[str]
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FollowUpContact(TypedDict, total=False):
    """Immutable event record: carries only id and created_at (PRD 2.4)."""

    id: str
    case_id: str
    contact_date: str
    contact_method: str
    outcome: str
    vital_status_at_contact: str
    counts_for_follow_up: bool
    recorded_by_user_id: str
    created_at: str


class RegistrySubmission(TypedDict, total=False):
    id: str
    program_id: str
    period_start: str
    period_end: str
    deadline_date: str
    submission_state: str
    pre_hold_state: Optional[str]
    total_case_count: int
    accepted_item_count: int
    failed_item_count: int
    resubmission_round: int
    late_case_count: int
    relief_pct: float
    assessment_due_cents: int
    assessment_paid_cents: int
    edit_error_codes: List[str]
    transmitted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SubmissionItem(TypedDict, total=False):
    id: str
    submission_id: str
    case_id: str
    edit_status: str
    edit_codes: List[str]
    resolution_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ConferenceSession(TypedDict, total=False):
    id: str
    program_id: str
    start_at: str
    end_at: str
    required_disciplines: List[str]
    session_state: str
    attendances: List[dict]
    cases_presented_count: int
    prospective_case_count: int
    prospective_case_ratio: float
    quorum_met: bool
    credited_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class QualityMeasure(TypedDict, total=False):
    id: str
    program_id: str
    measure_code: str
    measurement_year: int
    threshold_pct: float
    measure_state: str
    performance_state: str
    strata: List[dict]
    included_strata_count: int
    performance_rate_pct: Optional[float]
    pooled_rate_pct: Optional[float]
    project_title: Optional[str]
    target_rate_pct: Optional[float]
    final_rate_pct: Optional[float]
    created_at: str
    updated_at: str
    version: int


class Deficiency(TypedDict, total=False):
    id: str
    program_id: str
    standard_code: str
    severity: str
    cited_on: str
    response_due_date: str
    deficiency_state: str
    escalation_count: int
    evidence_reference: Optional[str]
    source_measure_id: Optional[str]
    response_narrative: Optional[str]
    reviewer_notes: Optional[str]
    created_at: str
    updated_at: str
    version: int
