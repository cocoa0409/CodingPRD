"""Domain types for the Staffing Data Reporting & Verification API.

Entity TypedDicts, status enums, and the role enum, all named exactly as the
PRD names them.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    STAFFING_COORDINATOR = "StaffingCoordinator"
    FACILITY_ADMINISTRATOR = "FacilityAdministrator"
    VENDOR_REPRESENTATIVE = "VendorRepresentative"
    STATE_AUDITOR = "StateAuditor"
    CMS_PUBLISHER = "CmsPublisher"
    APPEALS_REVIEWER = "AppealsReviewer"


class AuthorizedRole(str, Enum):
    """Literal strings a Worker's `authorized_roles` array may carry."""

    STAFFING_COORDINATOR = "STAFFING_COORDINATOR"
    FACILITY_ADMINISTRATOR = "FACILITY_ADMINISTRATOR"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------


class FacilityPosture(str, Enum):
    REPORTING_OPEN = "REPORTING_OPEN"
    AUDIT_HOLD = "AUDIT_HOLD"
    SANCTIONED = "SANCTIONED"


class ReportingPeriodStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class DirectCareClass(str, Enum):
    DIRECT_CARE = "DIRECT_CARE"
    DIRECT_CARE_SPLIT = "DIRECT_CARE_SPLIT"
    ADMINISTRATIVE = "ADMINISTRATIVE"
    NON_DIRECT_CARE = "NON_DIRECT_CARE"


class NurseGroup(str, Enum):
    RN = "RN"
    LPN = "LPN"
    NA = "NA"
    NONE = "NONE"


class WorkerType(str, Enum):
    EMPLOYEE = "EMPLOYEE"
    AGENCY_CONTRACTOR = "AGENCY_CONTRACTOR"
    INDIVIDUAL_CONTRACTOR = "INDIVIDUAL_CONTRACTOR"


class WorkerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class VendorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class VendorSubmissionStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    REVOKED = "REVOKED"


class SupportType(str, Enum):
    TIMECARD = "TIMECARD"
    PAYROLL_JOURNAL = "PAYROLL_JOURNAL"
    INVOICE = "INVOICE"


class EntryStatus(str, Enum):
    ACTIVE = "ACTIVE"
    VOID = "VOID"


class VerificationStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    SUPPORTED = "SUPPORTED"
    UNSUPPORTED = "UNSUPPORTED"


class VerificationOutcome(str, Enum):
    SUPPORTED = "SUPPORTED"
    UNSUPPORTED = "UNSUPPORTED"


class HourEntrySource(str, Enum):
    """PRD §3.3 sets an individually captured entry's `source`; §3.5 sets the
    synthesized agency entry's `source`."""

    PAYROLL = "PAYROLL"
    VENDOR_SUBMISSION = "VENDOR_SUBMISSION"


class CensusDayStatus(str, Enum):
    REPORTED = "REPORTED"
    RECONCILED = "RECONCILED"
    DISPUTED = "DISPUTED"


class SubmissionStatus(str, Enum):
    DRAFT = "DRAFT"
    VALIDATED = "VALIDATED"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    FINAL = "FINAL"
    VOID = "VOID"


class FindingCode(str, Enum):
    CENSUS_INCOMPLETE = "CENSUS_INCOMPLETE"
    CENSUS_VARIANCE = "CENSUS_VARIANCE"
    HPRD_IMPLAUSIBLE = "HPRD_IMPLAUSIBLE"
    MISSING_PAYROLL_SUPPORT = "MISSING_PAYROLL_SUPPORT"
    ZERO_DIRECT_CARE_DAY = "ZERO_DIRECT_CARE_DAY"
    UNSUPPORTED_HOURS = "UNSUPPORTED_HOURS"
    FACILITY_SANCTIONED = "FACILITY_SANCTIONED"


class FindingSeverity(str, Enum):
    FATAL = "FATAL"
    WARNING = "WARNING"


class FindingStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    WAIVED = "WAIVED"


class MeasureVariant(str, Enum):
    AS_SUBMITTED = "AS_SUBMITTED"
    AUDIT_ADJUSTED = "AUDIT_ADJUSTED"


class PublicationStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    PUBLISHED = "PUBLISHED"
    SUPPRESSED = "SUPPRESSED"


class AuditStatus(str, Enum):
    NOT_AUDITED = "NOT_AUDITED"
    UNDER_AUDIT = "UNDER_AUDIT"
    AUDIT_CONFIRMED = "AUDIT_CONFIRMED"
    AUDIT_REVISED = "AUDIT_REVISED"


class CaseTriggerReason(str, Enum):
    AUDIT_SCORE_BELOW_FLOOR = "AUDIT_SCORE_BELOW_FLOOR"
    UNSUPPORTED_HOURS = "UNSUPPORTED_HOURS"
    CENSUS_MISMATCH = "CENSUS_MISMATCH"
    VENDOR_DATA_GAP = "VENDOR_DATA_GAP"
    PUBLIC_COMPLAINT = "PUBLIC_COMPLAINT"


class CaseStatus(str, Enum):
    OPEN = "OPEN"
    INFO_REQUESTED = "INFO_REQUESTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    SUBSTANTIATED = "SUBSTANTIATED"
    DISMISSED = "DISMISSED"
    OVERTURNED = "OVERTURNED"


class AppealGrounds(str, Enum):
    DATA_ENTRY_ERROR = "DATA_ENTRY_ERROR"
    CENSUS_ERROR = "CENSUS_ERROR"
    VENDOR_DATA_ERROR = "VENDOR_DATA_ERROR"
    MEASURE_CALCULATION_ERROR = "MEASURE_CALCULATION_ERROR"


class AppealStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    GRANTED = "GRANTED"
    DENIED = "DENIED"


class HprdVariant(str, Enum):
    """`variant` query parameter of the hours-per-resident-day computed read."""

    AS_SUBMITTED = "AS_SUBMITTED"
    AUDIT_ADJUSTED = "AUDIT_ADJUSTED"


class AuditReadinessVariant(str, Enum):
    """`variant` query parameter of the audit-readiness computed read."""

    SAMPLED = "SAMPLED"
    FULL = "FULL"


# ---------------------------------------------------------------------------
# Entity payload shapes
# ---------------------------------------------------------------------------


class Facility(TypedDict):
    id: str
    ccn: str
    name: str
    state_code: str
    certified_bed_count: int
    posture: str
    open_case_count: int
    substantiated_case_count: int
    outstanding_surcharge_cents: int
    latest_staffing_rating: Optional[int]
    created_at: str
    updated_at: str
    version: int


class ReportingPeriod(TypedDict):
    id: str
    period_code: str
    state_code: str
    start_date: str
    end_date: str
    day_count: int
    submission_deadline: str
    correction_window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class JobCategory(TypedDict):
    id: str
    code: str
    cms_job_code: int
    direct_care_class: str
    nurse_group: str
    direct_care_credit_pct: float
    weekend_countable: bool
    created_at: str
    updated_at: str
    version: int


class Worker(TypedDict):
    id: str
    facility_id: str
    full_name: str
    worker_type: str
    primary_job_category_id: str
    hire_date: str
    vendor_id: Optional[str]
    authorized_roles: List[str]
    status: str
    reported_hours_total: float
    created_at: str
    updated_at: str
    version: int


class StaffingVendor(TypedDict):
    id: str
    facility_id: str
    vendor_name: str
    tax_id: str
    attestation_contact: str
    status: str
    accepted_hours_total: float
    created_at: str
    updated_at: str
    version: int


class VendorHourSubmission(TypedDict):
    id: str
    vendor_id: str
    facility_id: str
    reporting_period_id: str
    attested_by: str
    line_count: int
    status: str
    accepted_direct_care_hours: float
    accepted_hour_entry_ids: List[str]
    rejection_reason: Optional[str]
    submitted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PayrollRecord(TypedDict):
    """PRD §2.4: a filed payroll document carries only `id` and `created_at` —
    both `updated_at` and `version` are absent from the payload entirely."""

    id: str
    facility_id: str
    worker_id: str
    pay_period_start: str
    pay_period_end: str
    paid_hours: float
    support_type: str
    document_ref: str
    created_at: str


class HourEntry(TypedDict):
    id: str
    submission_id: str
    facility_id: str
    reporting_period_id: str
    worker_id: str
    job_category_id: str
    work_date: str
    shift_start: str
    shift_end: str
    raw_hours: float
    direct_care_hours: float
    excluded_hours: float
    rn_hours: float
    lpn_hours: float
    na_hours: float
    is_weekend: bool
    source: str
    vendor_submission_id: Optional[str]
    payroll_record_id: Optional[str]
    entry_status: str
    verification_status: str
    verified_by_user_id: Optional[str]
    allocation_revision: int
    submission_version: int
    created_at: str
    updated_at: str
    version: int


class CensusDay(TypedDict):
    id: str
    submission_id: str
    facility_id: str
    reporting_period_id: str
    census_date: str
    resident_count: int
    mds_resident_count: Optional[int]
    variance_pct: Optional[float]
    status: str
    is_weekend: bool
    submission_version: int
    created_at: str
    updated_at: str
    version: int


class QuarterlySubmission(TypedDict):
    id: str
    facility_id: str
    reporting_period_id: str
    status: str
    total_raw_hours: float
    total_direct_care_hours: float
    total_excluded_hours: float
    total_rn_direct_care_hours: float
    weekend_direct_care_hours: float
    vendor_sourced_hours: float
    total_resident_days: int
    hprd_reported: Optional[float]
    weekend_hprd_reported: Optional[float]
    audit_support_score: Optional[float]
    open_fatal_finding_count: int
    open_warning_finding_count: int
    validated_by_worker_id: Optional[str]
    attested_by_worker_id: Optional[str]
    accepted_by_user_id: Optional[str]
    rejection_reason: Optional[str]
    submitted_at: Optional[str]
    accepted_at: Optional[str]
    amendment_index: int
    amendment_surcharge_cents: int
    waived_surcharge_cents: int
    correction_deadline: str
    created_at: str
    updated_at: str
    version: int


class ValidationFinding(TypedDict):
    id: str
    submission_id: str
    code: str
    severity: str
    subject_ref: str
    detail: str
    status: str
    waived_by_user_id: Optional[str]
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StaffingMeasure(TypedDict):
    id: str
    submission_id: str
    facility_id: str
    reporting_period_id: str
    measure_variant: str
    publication_status: str
    audit_status: str
    total_nurse_hprd: Optional[float]
    rn_hprd: Optional[float]
    weekend_total_nurse_hprd: Optional[float]
    total_nurse_points: int
    rn_points: int
    days_with_zero_rn_hours: int
    staffing_rating: int
    published_at: Optional[str]
    appeal_deadline: Optional[str]
    has_open_appeal: bool
    computed_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class DiscrepancyCase(TypedDict):
    id: str
    facility_id: str
    submission_id: str
    staffing_measure_id: Optional[str]
    trigger_reason: str
    detail: str
    status: str
    auto_opened: bool
    opened_by_user_id: str
    info_request_count: int
    facility_response_count: int
    last_request_note: Optional[str]
    last_response_note: Optional[str]
    substantiated_by_user_id: Optional[str]
    resolution_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RatingAppeal(TypedDict):
    id: str
    staffing_measure_id: str
    facility_id: str
    discrepancy_case_id: Optional[str]
    grounds: str
    narrative: str
    status: str
    filed_by_worker_id: str
    decided_by_user_id: Optional[str]
    decision_note: Optional[str]
    decided_at: Optional[str]
    surcharge_waived_cents: int
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Computed-read response shapes (persist nothing)
# ---------------------------------------------------------------------------


class HprdRead(TypedDict):
    submission_id: str
    variant: str
    total_direct_care_hours: float
    total_rn_hours: float
    weekend_direct_care_hours: float
    resident_days: int
    weekend_resident_days: int
    total_nurse_hprd: Optional[float]
    rn_hprd: Optional[float]
    weekend_total_nurse_hprd: Optional[float]
    implausible: bool


class AuditReadinessRead(TypedDict):
    submission_id: str
    variant: str
    considered_entry_count: int
    considered_hours: float
    supported_hours: float
    support_ratio: float
    vendor_attestation_ratio: float
    census_reconciled_ratio: float
    score: float
    at_risk: bool
