"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    FEDERAL_PROGRAMS_DIRECTOR = "FederalProgramsDirector"
    COMPLIANCE_ANALYST = "ComplianceAnalyst"
    SEA_MONITOR = "SEAMonitor"
    PRIVATE_SCHOOL_OMBUDSMAN = "PrivateSchoolOmbudsman"


class PovertyMeasure(str, Enum):
    CENSUS_SAIPE = "CENSUS_SAIPE"
    FREE_REDUCED_LUNCH = "FREE_REDUCED_LUNCH"
    MEDICAID_DIRECT_CERT = "MEDICAID_DIRECT_CERT"
    COMPOSITE = "COMPOSITE"


class EquitableCountMethod(str, Enum):
    CONSULTATION_AGREED = "CONSULTATION_AGREED"
    VERIFIED_COUNT = "VERIFIED_COUNT"


class GrantStatus(str, Enum):
    SETUP = "SETUP"
    RANKING_LOCKED = "RANKING_LOCKED"
    ALLOCATED = "ALLOCATED"
    CLOSED_OUT = "CLOSED_OUT"


class WaiverStatus(str, Enum):
    NONE = "NONE"
    REQUESTED = "REQUESTED"
    GRANTED = "GRANTED"
    DENIED = "DENIED"


class MonitoringClearance(str, Enum):
    NOT_MONITORED = "NOT_MONITORED"
    FINDINGS_OPEN = "FINDINGS_OPEN"
    CLEARED = "CLEARED"


class SnapshotStatus(str, Enum):
    DRAFT = "DRAFT"
    CERTIFIED = "CERTIFIED"
    SUPERSEDED = "SUPERSEDED"


class EligibilityFlag(str, Enum):
    MUST_SERVE = "MUST_SERVE"
    ELIGIBLE = "ELIGIBLE"
    BELOW_THRESHOLD = "BELOW_THRESHOLD"


class ProgramModel(str, Enum):
    SCHOOLWIDE = "SCHOOLWIDE"
    TARGETED_ASSISTANCE = "TARGETED_ASSISTANCE"


class AllocationStatus(str, Enum):
    PENDING = "PENDING"
    CERTIFIED = "CERTIFIED"


class SetAsideCategory(str, Enum):
    PARENT_ENGAGEMENT = "PARENT_ENGAGEMENT"
    HOMELESS_SERVICES = "HOMELESS_SERVICES"
    PROFESSIONAL_DEVELOPMENT = "PROFESSIONAL_DEVELOPMENT"
    EQUITABLE_SERVICES = "EQUITABLE_SERVICES"


class SnsStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    RETURNED = "RETURNED"
    STALE = "STALE"


class SnsMethodology(str, Enum):
    PER_SCHOOL_DISTRIBUTION = "PER_SCHOOL_DISTRIBUTION"
    GRADE_SPAN_GROUPING = "GRADE_SPAN_GROUPING"
    PER_PUPIL_FORMULA = "PER_PUPIL_FORMULA"


class ConsultationStatus(str, Enum):
    INITIATED = "INITIATED"
    CONSULTING = "CONSULTING"
    AFFIRMATION_SIGNED = "AFFIRMATION_SIGNED"
    DISPUTED = "DISPUTED"
    COMPLAINT_FILED = "COMPLAINT_FILED"


class ExpenditureStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    ALLOWED = "ALLOWED"
    DISALLOWED = "DISALLOWED"
    RECLASSIFIED = "RECLASSIFIED"


class FunctionCode(str, Enum):
    INSTRUCTION = "INSTRUCTION"
    PD = "PD"
    PARENT_ENGAGEMENT = "PARENT_ENGAGEMENT"
    HOMELESS_SUPPORT = "HOMELESS_SUPPORT"
    EQUITABLE_SERVICES = "EQUITABLE_SERVICES"


class DisallowReason(str, Enum):
    SUPPLANT_RISK = "SUPPLANT_RISK"
    UNALLOWABLE_COST = "UNALLOWABLE_COST"
    INSUFFICIENT_DOCUMENTATION = "INSUFFICIENT_DOCUMENTATION"
    SNS_STALE_CASCADE = "SNS_STALE_CASCADE"


class FundSource(str, Enum):
    NON_TITLE_I_STATE = "NON_TITLE_I_STATE"
    NON_TITLE_I_LOCAL = "NON_TITLE_I_LOCAL"


class AmendmentStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    VOIDED = "VOIDED"


class VisitStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    REPORT_ISSUED = "REPORT_ISSUED"
    CLOSED = "CLOSED"


class VisitScope(str, Enum):
    PROGRAMMATIC = "PROGRAMMATIC"
    FISCAL = "FISCAL"
    COMPREHENSIVE = "COMPREHENSIVE"


class FindingStatus(str, Enum):
    OPEN = "OPEN"
    ESCALATED = "ESCALATED"
    CAP_SUBMITTED = "CAP_SUBMITTED"
    CAP_RETURNED = "CAP_RETURNED"
    VERIFIED = "VERIFIED"
    CLOSED_NO_ACTION = "CLOSED_NO_ACTION"


class FindingSeverity(str, Enum):
    OBSERVATION = "OBSERVATION"
    FINDING = "FINDING"
    SYSTEMIC = "SYSTEMIC"


# --- Entity TypedDicts -------------------------------------------------------
# Every resource is a primary resource under PRD §2.4 and therefore carries
# id, created_at, updated_at, and version.


class DistrictGrant(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    fiscal_year: int
    total_allocation_cents: int
    carryover_in_cents: int
    admin_reserve_cents: int
    poverty_measure: str
    equitable_count_method: str
    status: str
    carryover_waiver_status: str
    carryover_waiver_justification: Optional[str]
    carryover_waiver_decided_at: Optional[str]
    net_allocable_cents: int
    ranking_version: int
    liquidated_cents: int
    pending_cents: int
    provisional_carryover_cents: int
    provisional_carryover_pct_bp: int
    final_carryover_cents: Optional[int]
    final_carryover_pct_bp: Optional[int]
    monitoring_clearance: str


class School(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    name: str
    nces_id: str
    grade_span_low: int
    grade_span_high: int
    is_active: bool


class PrivateSchool(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    name: str
    nonprofit_verified: bool
    low_income_resident_count: int
    contact_email: str


class SnapshotEntry(TypedDict):
    school_id: str
    low_income_student_count: int
    total_student_count: int


class PovertyDataSnapshot(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    grant_id: str
    measure: str
    entries: List[SnapshotEntry]
    status: str
    certified_at: Optional[str]


class SchoolAllocation(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    grant_id: str
    school_id: str
    snapshot_id: str
    low_income_student_count: int
    total_student_count: int
    poverty_pct_bp: int
    rank_position: int
    eligibility_flag: str
    program_model: str
    serve_elected: bool
    served: bool
    per_pupil_cents: int
    allocation_amount_cents: int
    liquidated_cents: int
    pending_cents: int
    supplement_ok: bool
    status: str


class SetAside(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    grant_id: str
    category: str
    minimum_cents: int
    reserved_cents: int
    school_distributed_minimum_cents: int
    liquidated_cents: int


class SupplementDocumentation(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    school_allocation_id: str
    methodology: str
    coverage_start_date: str
    coverage_end_date: str
    narrative: str
    status: str
    submitted_by_user_id: Optional[str]
    reviewed_by_user_id: Optional[str]
    review_note: Optional[str]
    attempt_count: int


class EquitableServicesConsultation(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    grant_id: str
    private_school_id: str
    status: str
    sessions: List[dict]
    sessions_count: int
    agreed_low_income_count: Optional[int]
    affirmation_signed_at: Optional[str]
    affirmation_signer_id: Optional[str]
    dispute_reason: Optional[str]
    complaint_determination: Optional[str]


class Expenditure(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    grant_id: str
    school_allocation_id: Optional[str]
    set_aside_id: Optional[str]
    amount_cents: int
    function_code: str
    description: str
    incurred_date: str
    supplant_screen: bool
    status: str
    submitted_by_user_id: str
    reviewed_by_user_id: Optional[str]
    review_note: Optional[str]
    disallow_reason: Optional[str]
    reclassified_to_fund_source: Optional[str]


class AmendmentLine(TypedDict):
    target_type: str
    target_id: str
    new_amount_cents: int


class BudgetAmendment(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    grant_id: str
    lines: List[AmendmentLine]
    prior_amounts: List[dict]
    status: str
    submitted_by_user_id: Optional[str]
    decided_by_user_id: Optional[str]
    decision_note: Optional[str]


class MonitoringVisit(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    grant_id: str
    visit_start_date: str
    visit_end_date: str
    scope: str
    lead_monitor_id: str
    status: str
    report_issued_at: Optional[str]


class MonitoringFinding(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    visit_id: str
    citation: str
    severity: str
    description: str
    cap_due_date: str
    status: str
    cap_narrative: Optional[str]
    cap_attempt_count: int
    cap_submitted_by_user_id: Optional[str]
    decided_by_user_id: Optional[str]
    return_note: Optional[str]
