"""Domain types for the Driver Recruiting DQ File API.

Entity TypedDicts, status enums and the role enum, named exactly as the PRD
names them.  Every entity in this API carries the full common field set
(``id``, ``created_at``, ``updated_at``, ``version``).
"""
from enum import Enum
from typing import List, Optional, TypedDict


# ─── Role enum ────────────────────────────────────────────────────────────────

class UserRole(str, Enum):
    RECRUITER = "Recruiter"
    DER = "DER"
    SAFETY_DIRECTOR = "SafetyDirector"
    COMPLIANCE_AUDITOR = "ComplianceAuditor"
    SCHOOL_COORDINATOR = "SchoolCoordinator"
    APPLICANT = "Applicant"


ALL_ROLES: List[str] = [r.value for r in UserRole]


# ─── Status / enum vocabularies ───────────────────────────────────────────────

class CarrierSafetyRating(str, Enum):
    SATISFACTORY = "SATISFACTORY"
    CONDITIONAL = "CONDITIONAL"
    UNSATISFACTORY = "UNSATISFACTORY"


class CarrierPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class CdlClass(str, Enum):
    CLASS_A = "CLASS_A"
    CLASS_B = "CLASS_B"
    CLASS_C = "CLASS_C"


class CdlDowngradeRisk(str, Enum):
    NO_CERTIFICATE = "NO_CERTIFICATE"
    NONE = "NONE"
    WATCH = "WATCH"
    IMMINENT = "IMMINENT"
    EXPIRED_GRACE = "EXPIRED_GRACE"
    DOWNGRADED = "DOWNGRADED"


class RehireEligibility(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    COOLDOWN = "COOLDOWN"
    PERMANENTLY_INELIGIBLE = "PERMANENTLY_INELIGIBLE"


class PositionType(str, Enum):
    OTR = "OTR"
    REGIONAL = "REGIONAL"
    LOCAL = "LOCAL"


class ScreeningStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    SCREENING = "SCREENING"
    INFO_REQUESTED = "INFO_REQUESTED"
    SCREEN_CLEARED = "SCREEN_CLEARED"
    SCREEN_FAILED = "SCREEN_FAILED"


class QualificationStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    ROAD_TEST_PASSED = "ROAD_TEST_PASSED"
    ORIENTATION_COMPLETE = "ORIENTATION_COMPLETE"
    QUALIFIED = "QUALIFIED"
    HIRED = "HIRED"
    DISQUALIFIED = "DISQUALIFIED"


class EmploymentVerificationStatus(str, Enum):
    PENDING = "PENDING"
    REQUESTED = "REQUESTED"
    NO_RESPONSE = "NO_RESPONSE"
    RESPONDED_VERIFIED = "RESPONDED_VERIFIED"
    RESPONDED_DISPUTED = "RESPONDED_DISPUTED"
    GOOD_FAITH_DOCUMENTED = "GOOD_FAITH_DOCUMENTED"


class CheckType(str, Enum):
    MVR = "MVR"
    PSP = "PSP"
    CRIMINAL = "CRIMINAL"


class ScreeningCheckStatus(str, Enum):
    ORDERED = "ORDERED"
    RECEIVED = "RECEIVED"
    PRE_ADVERSE = "PRE_ADVERSE"
    DISPUTED = "DISPUTED"
    ADJUDICATED_PASS = "ADJUDICATED_PASS"
    ADVERSE_FINAL = "ADVERSE_FINAL"


class ClearinghouseQueryType(str, Enum):
    LIMITED = "LIMITED"
    FULL = "FULL"


class ClearinghouseQueryStatus(str, Enum):
    CONSENT_PENDING = "CONSENT_PENDING"
    CONSENT_GRANTED = "CONSENT_GRANTED"
    CONSENT_DENIED = "CONSENT_DENIED"
    RESULT_CLEAR = "RESULT_CLEAR"
    RESULT_INFO_EXISTS = "RESULT_INFO_EXISTS"
    RESULT_PROHIBITED = "RESULT_PROHIBITED"


class DrugTestType(str, Enum):
    PRE_EMPLOYMENT = "PRE_EMPLOYMENT"
    RETURN_TO_DUTY = "RETURN_TO_DUTY"


class DrugTestOrderStatus(str, Enum):
    ORDERED = "ORDERED"
    COLLECTED = "COLLECTED"
    LAB_NEGATIVE = "LAB_NEGATIVE"
    LAB_POSITIVE = "LAB_POSITIVE"
    LAB_DILUTE = "LAB_DILUTE"
    MRO_VERIFIED_NEGATIVE = "MRO_VERIFIED_NEGATIVE"
    MRO_VERIFIED_POSITIVE = "MRO_VERIFIED_POSITIVE"


class RoadTestStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PASSED = "PASSED"
    FAILED = "FAILED"
    NO_SHOW = "NO_SHOW"


class OrientationSessionStatus(str, Enum):
    PLANNED = "PLANNED"
    OPEN = "OPEN"
    COMPLETED = "COMPLETED"


class OrientationEnrollmentStatus(str, Enum):
    RESERVED = "RESERVED"
    ATTENDED = "ATTENDED"
    ABSENT = "ABSENT"
    CANCELLED = "CANCELLED"


class DqFileStatus(str, Enum):
    OPEN = "OPEN"
    COMPLETE = "COMPLETE"
    DEFICIENT = "DEFICIENT"
    ARCHIVED = "ARCHIVED"


class DqReviewState(str, Enum):
    NOT_DUE = "NOT_DUE"
    DUE = "DUE"
    OVERDUE = "OVERDUE"


class DqDocType(str, Enum):
    APPLICATION_FORM = "APPLICATION_FORM"
    CDL_COPY = "CDL_COPY"
    MVR_INITIAL = "MVR_INITIAL"
    PSP_REPORT = "PSP_REPORT"
    CRIMINAL_CHECK = "CRIMINAL_CHECK"
    EMPLOYMENT_VERIFICATION = "EMPLOYMENT_VERIFICATION"
    CLEARINGHOUSE_QUERY = "CLEARINGHOUSE_QUERY"
    DRUG_TEST_RESULT = "DRUG_TEST_RESULT"
    ROAD_TEST_CERT = "ROAD_TEST_CERT"
    MEDICAL_CERT = "MEDICAL_CERT"
    MVR_ANNUAL = "MVR_ANNUAL"
    ANNUAL_REVIEW_CERT = "ANNUAL_REVIEW_CERT"


class DqDocumentStatus(str, Enum):
    MISSING = "MISSING"
    PRESENT = "PRESENT"
    EXPIRED = "EXPIRED"
    WAIVED = "WAIVED"


class TuitionAgreementStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    FULFILLED = "FULFILLED"
    TERMINATED_CLAWBACK = "TERMINATED_CLAWBACK"


class TerminationType(str, Enum):
    NONE = "NONE"
    VOLUNTARY = "VOLUNTARY"
    INVOLUNTARY_PERFORMANCE = "INVOLUNTARY_PERFORMANCE"
    INVOLUNTARY_SAFETY = "INVOLUNTARY_SAFETY"
    ABANDONMENT = "ABANDONMENT"


class RehireFlag(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    NOT_ELIGIBLE = "NOT_ELIGIBLE"
    CONDITIONAL = "CONDITIONAL"


class HireRecordStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"
    RESCINDED = "RESCINDED"


class CompletenessVariant(str, Enum):
    PRE_HIRE_PROVISIONAL = "pre_hire_provisional"
    ANNUAL_REVIEW_FINAL = "annual_review_final"


class CoverageVariant(str, Enum):
    STRICT_VERIFIED = "strict_verified"
    GOOD_FAITH_PROJECTED = "good_faith_projected"


# ─── Entity TypedDicts (every entity carries the full common field set) ───────

class Carrier(TypedDict):
    id: str
    legal_name: str
    dot_number: str
    safety_rating: str
    open_requisitions: int
    filled_requisitions: int
    mvr_validity_days: int
    annual_review_interval_days: int
    annual_review_grace_days: int
    mvr_point_threshold: int
    rehire_cooldown_days: int
    medical_cert_grace_days: int
    deficiency_ratio: float
    posture: str
    created_at: str
    updated_at: str
    version: int


class DriverApplicant(TypedDict):
    id: str
    carrier_id: str
    full_name: str
    date_of_birth: str
    email: str
    cdl_number: str
    cdl_state: str
    cdl_class: str
    experience_months: int
    cdl_downgrade_risk: str
    governing_medical_cert_expires_on: Optional[str]
    rehire_eligibility: str
    outstanding_clawback_cents: int
    created_at: str
    updated_at: str
    version: int


class DriverApplication(TypedDict):
    id: str
    applicant_id: str
    carrier_id: str
    prior_application_id: Optional[str]
    position_type: str
    screening_status: str
    qualification_status: str
    revision_round: int
    submitted_at: Optional[str]
    recruiter_user_id: Optional[str]
    verified_coverage_days: int
    gap_days_unexplained: int
    disqualifying_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EmploymentVerification(TypedDict):
    id: str
    application_id: str
    employer_name: str
    is_dot_regulated: bool
    employed_from: str
    employed_to: str
    status: str
    request_round: int
    last_requested_at: Optional[str]
    safety_performance_history_received: bool
    drug_alcohol_violation_reported: bool
    created_at: str
    updated_at: str
    version: int


class ScreeningCheck(TypedDict):
    id: str
    application_id: str
    check_type: str
    status: str
    issued_on: Optional[str]
    expires_on: Optional[str]
    violation_points: int
    serious_violation_count: int
    crash_preventable_count: int
    adjudication_score: float
    pre_adverse_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ClearinghouseQuery(TypedDict):
    id: str
    application_id: str
    query_type: str
    status: str
    consent_granted_at: Optional[str]
    consent_expires_on: Optional[str]
    result: str
    follow_up_full_query_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DrugTestOrder(TypedDict):
    id: str
    application_id: str
    test_type: str
    status: str
    collected_at: Optional[str]
    dilute_recollect_count: int
    created_at: str
    updated_at: str
    version: int


class RoadTest(TypedDict):
    id: str
    application_id: str
    examiner_user_id: str
    scheduled_at: str
    vehicle_class: str
    status: str
    attempt_number: int
    score_pretrip: Optional[int]
    score_skills: Optional[int]
    score_road: Optional[int]
    composite_score: Optional[float]
    created_at: str
    updated_at: str
    version: int


class OrientationSession(TypedDict):
    id: str
    carrier_id: str
    starts_at: str
    ends_at: str
    capacity: int
    location_code: str
    enrolled_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class OrientationEnrollment(TypedDict):
    id: str
    session_id: str
    application_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DqFile(TypedDict):
    id: str
    application_id: str
    status: str
    review_state: str
    completeness_pct: float
    deficiency_count: int
    total_weight: int
    opened_on: str
    last_annual_review_at: Optional[str]
    next_review_due_on: str
    certified_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DqDocument(TypedDict):
    id: str
    dq_file_id: str
    doc_type: str
    weight: int
    status: str
    effective_on: Optional[str]
    expires_on: Optional[str]
    source_ref: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TuitionAgreement(TypedDict):
    id: str
    applicant_id: str
    school_name: str
    tuition_total_cents: int
    commitment_months: int
    base_monthly_cents: int
    monthly_reimbursement_cents: int
    forgiven_cents: int
    months_served: int
    reimbursed_cents: int
    bonus_paid_cents: int
    clawback_cents: int
    outstanding_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class HireRecord(TypedDict):
    id: str
    application_id: str
    applicant_id: str
    carrier_id: str
    prior_hire_id: Optional[str]
    hired_on: str
    terminated_on: Optional[str]
    termination_type: str
    rehire_flag: str
    tenure_days: int
    status: str
    created_at: str
    updated_at: str
    version: int
