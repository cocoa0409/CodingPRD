"""Domain types: entity TypedDicts, status enums, role enum.

All seventeen resource types share the system-managed fields `id`,
`created_at`, `updated_at`, and `version` (PRD §2.4: "No entity in this system
omits `updated_at` or `version`; the audit trail is uniform").
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    AID_DIRECTOR = "AidDirector"
    AID_OFFICER = "AidOfficer"
    STUDENT = "Student"


class AidYearStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    PACKAGING_LOCKED = "PACKAGING_LOCKED"
    RECONCILING = "RECONCILING"
    CLOSED = "CLOSED"


class FundTypeStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"
    CLOSED = "CLOSED"


class FundCategory(str, Enum):
    FEDERAL_TITLE_IV = "FEDERAL_TITLE_IV"
    INSTITUTIONAL = "INSTITUTIONAL"
    STATE = "STATE"
    EXTERNAL = "EXTERNAL"


class SapStatus(str, Enum):
    NOT_EVALUATED = "NOT_EVALUATED"
    GOOD_STANDING = "GOOD_STANDING"
    WARNING = "WARNING"
    SUSPENDED = "SUSPENDED"
    APPEAL_APPROVED = "APPEAL_APPROVED"


class EnrollmentStatus(str, Enum):
    FULL_TIME = "FULL_TIME"
    THREE_QUARTER = "THREE_QUARTER"
    HALF_TIME = "HALF_TIME"
    LESS_THAN_HALF = "LESS_THAN_HALF"


class Residency(str, Enum):
    IN_STATE = "IN_STATE"
    OUT_OF_STATE = "OUT_OF_STATE"


class DependencyStatus(str, Enum):
    DEPENDENT = "DEPENDENT"
    INDEPENDENT = "INDEPENDENT"


class IsirCohort(str, Enum):
    PRIORITY = "PRIORITY"
    STANDARD = "STANDARD"


class VerificationSelection(str, Enum):
    SELECTED = "SELECTED"
    NOT_SELECTED = "NOT_SELECTED"


class VerificationCaseStatus(str, Enum):
    DOCUMENTS_REQUESTED = "DOCUMENTS_REQUESTED"
    DOCUMENTS_RECEIVED = "DOCUMENTS_RECEIVED"
    UNDER_REVIEW = "UNDER_REVIEW"
    COMPLETED_SATISFIED = "COMPLETED_SATISFIED"
    COMPLETED_CORRECTION_SENT = "COMPLETED_CORRECTION_SENT"
    WAIVED = "WAIVED"


class VerificationDocumentStatus(str, Enum):
    REQUESTED = "REQUESTED"
    RECEIVED = "RECEIVED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class DocType(str, Enum):
    TAX_RETURN_TRANSCRIPT = "TAX_RETURN_TRANSCRIPT"
    W2 = "W2"
    HOUSEHOLD_FORM = "HOUSEHOLD_FORM"
    IDENTITY_STATEMENT = "IDENTITY_STATEMENT"
    OTHER = "OTHER"


class ConflictingInfoStatus(str, Enum):
    OPEN = "OPEN"
    SUBSTANTIATED = "SUBSTANTIATED"
    UNSUBSTANTIATED = "UNSUBSTANTIATED"
    RESOLVED_REQUIRES_CORRECTION = "RESOLVED_REQUIRES_CORRECTION"
    RESOLVED = "RESOLVED"


class PjStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class PjAdjustmentType(str, Enum):
    EFC_ADJUSTMENT = "EFC_ADJUSTMENT"
    COA_ADJUSTMENT = "COA_ADJUSTMENT"
    DEPENDENCY_OVERRIDE = "DEPENDENCY_OVERRIDE"


class AwardPackageStatus(str, Enum):
    DRAFT = "DRAFT"
    PACKAGED = "PACKAGED"
    NOTIFIED = "NOTIFIED"
    PARTIALLY_ACCEPTED = "PARTIALLY_ACCEPTED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    LOCKED = "LOCKED"


class AwardLineStatus(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    PARTIALLY_ACCEPTED = "PARTIALLY_ACCEPTED"
    DECLINED = "DECLINED"
    CANCELLED = "CANCELLED"
    DISBURSING = "DISBURSING"
    DISBURSED = "DISBURSED"
    RETURN_REQUESTED = "RETURN_REQUESTED"
    RETURNED = "RETURNED"


class AwardNotificationStatus(str, Enum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    ACKNOWLEDGED = "ACKNOWLEDGED"


class RevisionReason(str, Enum):
    CHANGE_ENROLLMENT = "CHANGE_ENROLLMENT"
    CHANGE_CIRCUMSTANCE = "CHANGE_CIRCUMSTANCE"
    APPEAL_AMOUNT = "APPEAL_AMOUNT"
    DECLINE_LOAN_ONLY = "DECLINE_LOAN_ONLY"


class RevisionRequestStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class DisbursementStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ELIGIBILITY_PASSED = "ELIGIBILITY_PASSED"
    ELIGIBILITY_FAILED = "ELIGIBILITY_FAILED"
    POSTED = "POSTED"
    RETURN_REQUESTED = "RETURN_REQUESTED"
    RETURNED = "RETURNED"


class OverawardCaseStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVING = "RESOLVING"
    RESOLVED = "RESOLVED"
    VERIFIED = "VERIFIED"


class ReconciliationRunStatus(str, Enum):
    DRAFT = "DRAFT"
    IMPORTED = "IMPORTED"
    COMPARED = "COMPARED"
    BALANCED = "BALANCED"
    VARIANCE_FOUND = "VARIANCE_FOUND"
    ADJUSTED = "ADJUSTED"


class AdjustmentReasonCode(str, Enum):
    FEDERAL_UNDERREPORT = "FEDERAL_UNDERREPORT"
    FEDERAL_OVERREPORT = "FEDERAL_OVERREPORT"
    TIMING_DIFFERENCE = "TIMING_DIFFERENCE"
    DATA_ENTRY_ERROR = "DATA_ENTRY_ERROR"


class AidYear(TypedDict, total=False):
    id: str
    year_code: str
    coa_in_state_cents: int
    coa_out_of_state_cents: int
    priority_deadline: str
    pell_schedule: List[dict]
    verification_tracking_flag_rate: float
    status: str
    total_packaged_cents: int
    total_disbursed_cents: int
    created_at: str
    updated_at: str
    version: int


class FundType(TypedDict, total=False):
    id: str
    aid_year_id: str
    fund_code: str
    category: str
    need_based: bool
    annual_cap_cents: int
    pool_budget_cents: int
    pool_reserved_cents: int
    pool_disbursed_cents: int
    priority_cohort_only: bool
    packaging_rank: int
    requires_verification_complete: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Student(TypedDict, total=False):
    id: str
    ssn: str
    full_name: str
    email: str
    residency: str
    dependency_status: str
    enrollment_status: str
    grade_level: int
    sap_status: str
    cumulative_attempted_credits: int
    cumulative_completed_credits: int
    max_timeframe_credits: int
    gpa_hundredths: int
    created_at: str
    updated_at: str
    version: int


class ISIRRecord(TypedDict, total=False):
    id: str
    student_id: str
    aid_year_id: str
    transaction_number: int
    received_at: str
    cohort: str
    household_size: int
    number_in_college: int
    agi_cents: int
    untaxed_income_cents: int
    asset_net_worth_cents: int
    cps_selection_flag: bool
    efc_provisional_cents: int
    efc_verified_cents: Optional[int]
    efc_official_cents: int
    is_current: bool
    verification_selection: str
    created_at: str
    updated_at: str
    version: int


class VerificationCase(TypedDict, total=False):
    id: str
    student_id: str
    aid_year_id: str
    isir_id: str
    tracking_group: str
    status: str
    waived_reason: Optional[str]
    resolution_notes: Optional[str]
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class VerificationDocument(TypedDict, total=False):
    id: str
    verification_case_id: str
    doc_type: str
    status: str
    rejection_reason: Optional[str]
    received_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ConflictingInfoCase(TypedDict, total=False):
    id: str
    student_id: str
    aid_year_id: str
    subject_field: str
    claimed_value_cents: Optional[int]
    status: str
    resolution: Optional[str]
    resolved_by_user_id: Optional[str]
    opened_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class ProfessionalJudgmentCase(TypedDict, total=False):
    id: str
    student_id: str
    aid_year_id: str
    adjustment_type: str
    requested_delta_cents: int
    justification: str
    documentation_complete: bool
    status: str
    reviewed_by_user_id: Optional[str]
    decided_by_user_id: Optional[str]
    applied_efc_delta_cents: int
    applied_coa_delta_cents: int
    created_at: str
    updated_at: str
    version: int


class AwardPackage(TypedDict, total=False):
    id: str
    student_id: str
    aid_year_id: str
    coa_used_cents: int
    efc_used_cents: int
    need_cents: int
    total_offered_cents: int
    total_accepted_cents: int
    gift_aid_cents: int
    status: str
    needs_repack: bool
    version_locked_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AwardLine(TypedDict, total=False):
    id: str
    package_id: str
    fund_type_id: str
    offered_cents: int
    accepted_cents: int
    disbursed_cents: int
    status: str
    sequence_number: int
    created_at: str
    updated_at: str
    version: int


class AwardNotification(TypedDict, total=False):
    id: str
    package_id: str
    notification_seq: int
    status: str
    sent_at: Optional[str]
    snapshot_total_offered_cents: int
    created_at: str
    updated_at: str
    version: int


class RevisionRequest(TypedDict, total=False):
    id: str
    package_id: str
    reason: str
    requested_by_role: str
    status: str
    decision_notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Disbursement(TypedDict, total=False):
    id: str
    award_line_id: str
    scheduled_cents: int
    disbursed_cents: int
    term_code: str
    status: str
    failure_reasons: List[str]
    created_at: str
    updated_at: str
    version: int


class OverawardCase(TypedDict, total=False):
    id: str
    student_id: str
    aid_year_id: str
    detected_total_aid_cents: int
    overage_cents: int
    status: str
    resolution_plan: List[dict]
    created_at: str
    updated_at: str
    version: int


class ExternalAid(TypedDict, total=False):
    id: str
    student_id: str
    aid_year_id: str
    source_name: str
    amount_cents: int
    counts_against_coa: bool
    created_at: str
    updated_at: str
    version: int


class ReconciliationRun(TypedDict, total=False):
    id: str
    aid_year_id: str
    run_seq: int
    status: str
    federal_reported_cents: int
    internal_posted_cents: int
    variance_cents: int
    created_at: str
    updated_at: str
    version: int


class ReconciliationAdjustment(TypedDict, total=False):
    id: str
    reconciliation_run_id: str
    award_line_id: str
    adjust_cents: int
    reason_code: str
    created_at: str
    updated_at: str
    version: int
