"""Domain types for the ADA workplace accommodation API.

Status enums, role names and entity shapes exactly as the PRD describes them.
Two entity types are append-only journal rows and therefore carry only ``id``
and ``created_at`` from the common property set.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    EMPLOYEE = "Employee"
    MANAGER = "Manager"
    ACCOMMODATION_COORDINATOR = "AccommodationCoordinator"
    MEDICAL_REVIEW_OFFICER = "MedicalReviewOfficer"
    FINANCE_OFFICER = "FinanceOfficer"
    APPEAL_OFFICER = "AppealOfficer"
    COMPLIANCE_AUDITOR = "ComplianceAuditor"


ALL_ROLES = [r.value for r in UserRole]


# --------------------------------------------------------------------------
# Status / enum vocabularies
# --------------------------------------------------------------------------
class EmploymentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ON_LEAVE = "ON_LEAVE"
    RESTRICTED_DUTY = "RESTRICTED_DUTY"


class JobProfileStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"


class EssentialFunctionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class RequestStage(str, Enum):
    INTAKE = "INTAKE"
    DOC_PENDING = "DOC_PENDING"
    FUNCTION_ANALYSIS = "FUNCTION_ANALYSIS"
    OPTION_EXPLORATION = "OPTION_EXPLORATION"
    HARDSHIP_REVIEW = "HARDSHIP_REVIEW"
    DECISION_PENDING = "DECISION_PENDING"
    TRIAL_SETUP = "TRIAL_SETUP"
    TRIAL_ACTIVE = "TRIAL_ACTIVE"
    GRANTED_PERMANENT = "GRANTED_PERMANENT"
    RENEWAL_DUE = "RENEWAL_DUE"
    DENIED = "DENIED"
    UNDER_APPEAL = "UNDER_APPEAL"
    DENIED_FINAL = "DENIED_FINAL"
    CLOSED = "CLOSED"
    WITHDRAWN = "WITHDRAWN"


class ConfidentialityPosture(str, Enum):
    STANDARD = "STANDARD"
    RESTRICTED = "RESTRICTED"
    SEALED = "SEALED"


class RequestChannel(str, Enum):
    WRITTEN = "WRITTEN"
    VERBAL = "VERBAL"
    MANAGER_OBSERVED = "MANAGER_OBSERVED"
    HR_INITIATED = "HR_INITIATED"


class CaseDecision(str, Enum):
    PENDING = "PENDING"
    GRANT_WITH_TRIAL = "GRANT_WITH_TRIAL"
    GRANT_PERMANENT = "GRANT_PERMANENT"
    DENY = "DENY"


class DocRequestStatus(str, Enum):
    ISSUED = "ISSUED"
    RESPONDED = "RESPONDED"
    ACCEPTED_SUFFICIENT = "ACCEPTED_SUFFICIENT"
    REJECTED_INSUFFICIENT = "REJECTED_INSUFFICIENT"
    EXPIRED = "EXPIRED"
    WITHDRAWN = "WITHDRAWN"


class FunctionAnalysisStatus(str, Enum):
    RECORDED = "RECORDED"
    DISPUTED = "DISPUTED"
    SUPERSEDED = "SUPERSEDED"


class ProposedTreatment(str, Enum):
    NOT_LIMITED = "NOT_LIMITED"
    PERFORM_WITH_AID = "PERFORM_WITH_AID"
    RESTRUCTURE = "RESTRUCTURE"
    REASSIGN_MARGINAL = "REASSIGN_MARGINAL"
    CANNOT_PERFORM = "CANNOT_PERFORM"


class OptionStatus(str, Enum):
    PROPOSED = "PROPOSED"
    CLEARED = "CLEARED"
    HARDSHIP_BLOCKED = "HARDSHIP_BLOCKED"
    SELECTED = "SELECTED"
    IMPLEMENTED = "IMPLEMENTED"
    SHELVED = "SHELVED"
    TRIAL_FAILED = "TRIAL_FAILED"
    WITHDRAWN = "WITHDRAWN"


class OptionCategory(str, Enum):
    EQUIPMENT = "EQUIPMENT"
    SCHEDULE_MODIFICATION = "SCHEDULE_MODIFICATION"
    TELEWORK = "TELEWORK"
    JOB_RESTRUCTURING = "JOB_RESTRUCTURING"
    REASSIGNMENT = "REASSIGNMENT"
    LEAVE_AS_ACCOMMODATION = "LEAVE_AS_ACCOMMODATION"
    POLICY_EXCEPTION = "POLICY_EXCEPTION"


class AssessmentBasis(str, Enum):
    EMPLOYER_WIDE = "EMPLOYER_WIDE"
    SITE_LOCAL = "SITE_LOCAL"


class HardshipVerdict(str, Enum):
    NOT_UNDUE = "NOT_UNDUE"
    BORDERLINE = "BORDERLINE"
    UNDUE = "UNDUE"


class AssessmentStatus(str, Enum):
    CURRENT = "CURRENT"
    SUPERSEDED = "SUPERSEDED"


class TrialStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    UNDER_REVIEW = "UNDER_REVIEW"
    CONCLUDED_EFFECTIVE = "CONCLUDED_EFFECTIVE"
    CONCLUDED_INEFFECTIVE = "CONCLUDED_INEFFECTIVE"
    ABORTED = "ABORTED"


class TrialOutcome(str, Enum):
    PENDING = "PENDING"
    EFFECTIVE = "EFFECTIVE"
    INEFFECTIVE = "INEFFECTIVE"
    ABORTED = "ABORTED"


class ScoringMode(str, Enum):
    CUMULATIVE_MEAN = "CUMULATIVE_MEAN"
    LATEST_WEIGHTED = "LATEST_WEIGHTED"


class DenialBasis(str, Enum):
    UNDUE_HARDSHIP = "UNDUE_HARDSHIP"
    DIRECT_THREAT = "DIRECT_THREAT"
    NOT_QUALIFIED = "NOT_QUALIFIED"
    NO_DISABILITY_NEXUS = "NO_DISABILITY_NEXUS"
    INSUFFICIENT_DOCUMENTATION = "INSUFFICIENT_DOCUMENTATION"
    FAILURE_TO_COOPERATE = "FAILURE_TO_COOPERATE"


class DenialStatus(str, Enum):
    ISSUED = "ISSUED"
    APPEALED = "APPEALED"
    FINAL = "FINAL"
    VACATED = "VACATED"


class AppealStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    SUPPLEMENT_REQUESTED = "SUPPLEMENT_REQUESTED"
    UPHELD = "UPHELD"
    REVERSED = "REVERSED"
    REMANDED = "REMANDED"
    DISMISSED = "DISMISSED"


class AppealOutcome(str, Enum):
    PENDING = "PENDING"
    UPHELD = "UPHELD"
    REVERSED = "REVERSED"
    REMANDED = "REMANDED"
    DISMISSED = "DISMISSED"


class AbsenceRecordType(str, Enum):
    FMLA_CONTINUOUS = "FMLA_CONTINUOUS"
    FMLA_INTERMITTENT = "FMLA_INTERMITTENT"
    STATE_LEAVE = "STATE_LEAVE"
    WC_RESTRICTION = "WC_RESTRICTION"


class AbsenceStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    MODIFIED_DUTY = "MODIFIED_DUTY"
    EXHAUSTED = "EXHAUSTED"
    CLOSED = "CLOSED"


class DisclosurePurpose(str, Enum):
    FUNCTION_ANALYSIS = "FUNCTION_ANALYSIS"
    HARDSHIP_ASSESSMENT = "HARDSHIP_ASSESSMENT"
    APPEAL_REVIEW = "APPEAL_REVIEW"
    AUDIT = "AUDIT"
    SAFETY_EMERGENCY = "SAFETY_EMERGENCY"
    OTHER = "OTHER"


MEDICAL_SCOPE_FIELDS = [
    "functional_limitations",
    "work_restrictions",
    "restriction_duration",
    "prognosis",
    "accommodation_needed",
    "diagnosis",
    "treatment_plan",
]

DISCLOSURE_TARGET_ROLES = [
    "Manager",
    "AccommodationCoordinator",
    "MedicalReviewOfficer",
    "FinanceOfficer",
    "AppealOfficer",
    "ComplianceAuditor",
    "EXTERNAL",
]


# --------------------------------------------------------------------------
# Entity shapes
# --------------------------------------------------------------------------
class Employee(TypedDict):
    id: str
    employee_number: str
    full_name: str
    department_code: str
    job_title: str
    hire_date: str
    job_profile_id: str
    is_people_manager: bool
    annual_salary_cents: int
    employment_status: str
    open_case_count: int
    lifetime_denial_count: int
    created_at: str
    updated_at: str
    version: int


class JobProfile(TypedDict):
    id: str
    job_code: str
    title: str
    department_code: str
    department_annual_budget_cents: int
    employer_annual_budget_cents: int
    status: str
    profile_version_label: Optional[str]
    essential_function_count: int
    total_essential_weight: int
    committed_accommodation_cost_cents: int
    created_at: str
    updated_at: str
    version: int


class EssentialFunction(TypedDict):
    id: str
    job_profile_id: str
    function_code: str
    description: str
    criticality_weight: int
    frequency_per_week: int
    is_essential: bool
    marginal_reassignable: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class AccommodationRequest(TypedDict):
    id: str
    employee_id: str
    job_profile_id: str
    pinned_profile_version_label: Optional[str]
    request_channel: str
    requested_accommodation_text: str
    disability_obvious: bool
    absence_record_id: Optional[str]
    renewal_of_request_id: Optional[str]
    selected_option_id: Optional[str]
    stage: str
    confidentiality_posture: str
    interactive_round_count: int
    medical_doc_request_count: int
    medical_doc_request_limit: int
    documentation_budget_remaining: int
    cleared_option_count: int
    blocked_option_count: int
    interactive_process_integrity_score: int
    review_cadence_days: Optional[int]
    review_due_date: Optional[str]
    review_cycle_index: int
    decision: str
    created_at: str
    updated_at: str
    version: int


class MedicalDocumentationRequest(TypedDict):
    id: str
    request_id: str
    round_index: int
    scope_fields_requested: List[str]
    issued_at: str
    due_date: str
    responded_at: Optional[str]
    response_summary: Optional[str]
    is_second_opinion: bool
    adjudication_note: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class FunctionAnalysis(TypedDict):
    id: str
    request_id: str
    essential_function_id: str
    manager_id: str
    can_perform_unaided: bool
    limitation_severity: int
    proposed_treatment: str
    employee_dispute_note: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AccommodationOption(TypedDict):
    id: str
    request_id: str
    option_code: str
    category: str
    proposed_by_role: str
    one_time_cost_cents: int
    recurring_monthly_cost_cents: int
    implementation_days: int
    coverage_function_ids: List[str]
    option_net_cost_cents: int
    coverage_ratio: float
    committed_cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class UndueHardshipAssessment(TypedDict):
    id: str
    option_id: str
    assessment_basis: str
    assessor_user_id: str
    assessed_net_cost_cents: int
    denominator_cents: int
    budget_ratio: float
    budget_ratio_norm: float
    disruption_index: float
    lag_norm: float
    raw_hardship_score: float
    mitigation_credit_rate: float
    hardship_score: float
    hardship_verdict: str
    status: str
    created_at: str
    updated_at: str
    version: int


class TrialPeriod(TypedDict):
    id: str
    request_id: str
    option_id: str
    employee_id: str
    start_date: str
    end_date: str
    checkin_cadence_days: int
    scoring_mode: str
    review_count: int
    effectiveness_score: Optional[float]
    extension_count: int
    outcome: str
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only journal row: id and created_at only from the common set.
class EffectivenessReview(TypedDict):
    id: str
    trial_period_id: str
    review_index: int
    review_date: str
    employee_rating: int
    manager_rating: int
    objective_metric_pct: int
    reviewer_user_id: str
    review_composite: float
    created_at: str


class DenialRecord(TypedDict):
    id: str
    request_id: str
    denial_basis: str
    rationale_text: str
    alternative_option_id: Optional[str]
    rejected_option_ids: List[str]
    issued_by_user_id: str
    issued_at: str
    appeal_deadline_date: str
    appeal_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Appeal(TypedDict):
    id: str
    denial_record_id: str
    grounds_text: str
    filed_by_user_id: str
    filed_at: str
    appeal_officer_user_id: Optional[str]
    supplement_count: int
    stay_count: int
    outcome: str
    status: str
    created_at: str
    updated_at: str
    version: int


class AbsenceRecord(TypedDict):
    id: str
    employee_id: str
    record_type: str
    start_date: str
    end_date: str
    weekly_intermittent_days: int
    restriction_severity: int
    modified_duty_available: bool
    claim_reference: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only journal row: id and created_at only from the common set.
class MedicalDisclosure(TypedDict):
    id: str
    request_id: str
    disclosed_to_role: str
    disclosed_to_user_id: str
    disclosure_purpose: str
    fields_disclosed: List[str]
    authorized: bool
    logged_by_user_id: str
    created_at: str
