"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    RECRUITER = "Recruiter"
    CREDENTIALING_SPECIALIST = "CredentialingSpecialist"
    CLINICIAN = "Clinician"
    FACILITY_MANAGER = "FacilityManager"
    PAYROLL_ADMIN = "PayrollAdmin"


class ClinicianStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    ON_ASSIGNMENT = "ON_ASSIGNMENT"
    INACTIVE = "INACTIVE"


class LicenseStatus(str, Enum):
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    VERIFIED = "VERIFIED"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"


class AssignmentStaffingStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_START = "PENDING_START"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class AssignmentComplianceStatus(str, Enum):
    PENDING_CREDENTIALS = "PENDING_CREDENTIALS"
    CLEARED = "CLEARED"
    SUSPENDED = "SUSPENDED"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    SENT_FOR_SIGNATURE = "SENT_FOR_SIGNATURE"
    COUNTERSIGN_REQUESTED = "COUNTERSIGN_REQUESTED"
    FULLY_EXECUTED = "FULLY_EXECUTED"
    VOIDED = "VOIDED"


class CredentialPacketStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    CLEARED = "CLEARED"
    REJECTED = "REJECTED"


class CredentialItemStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class TimesheetStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DISPUTED = "DISPUTED"
    VOIDED = "VOIDED"


class EarningsStatementStatus(str, Enum):
    FINALIZED = "FINALIZED"
    POSTED = "POSTED"
    REVERSED = "REVERSED"


class PayrollRunStatus(str, Enum):
    OPEN = "OPEN"
    LOCKED = "LOCKED"
    POSTED = "POSTED"


class ExtensionRequestStatus(str, Enum):
    PROPOSED = "PROPOSED"
    COUNTERED = "COUNTERED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    WITHDRAWN = "WITHDRAWN"


# --- Enumerations used in request bodies ---
DISCIPLINES = ["RN", "NP", "PHYSICIAN", "CRNA", "THERAPIST"]
SPECIALTIES = ["ICU", "ER", "MED_SURG", "OR", "L_AND_D", "TELEMETRY", "PSYCH", "HOSPITALIST"]
EMPLOYMENT_TYPES = ["W2_EMPLOYEE", "CONTRACTOR_1099"]
LICENSE_TYPES = ["RN", "NP", "PHYSICIAN", "CRNA", "THERAPIST"]
CREDENTIAL_ITEM_TYPES = [
    "BLS_CERT", "IMMUNIZATION_RECORD", "BACKGROUND_CHECK", "DRUG_SCREEN",
    "LICENSE_VERIFICATION", "TB_TEST", "FIT_TEST",
]
REQUIRED_CREDENTIAL_TYPES = [
    "BLS_CERT", "IMMUNIZATION_RECORD", "BACKGROUND_CHECK", "DRUG_SCREEN", "LICENSE_VERIFICATION",
]


# --- Entity TypedDicts (informational; assertions use dicts directly) ---
# common_fields: true -> id + created_at + updated_at + version
class Clinician(TypedDict, total=False):
    id: str
    full_name: str
    discipline: str
    specialty: str
    employment_type: str
    primary_residence_state: str
    tax_home_verified: bool
    status: str
    active_assignment_count: int
    ytd_taxable_wages_cents: int
    ytd_nontaxable_stipend_cents: int
    created_at: str
    updated_at: str
    version: int


class License(TypedDict, total=False):
    id: str
    clinician_id: str
    state_code: str
    license_type: str
    license_number: str
    is_compact: bool
    expires_on: str
    status: str
    verified_by_user_id: Optional[str]
    verified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Facility(TypedDict, total=False):
    id: str
    name: str
    state_code: str
    is_compact_member: bool
    per_diem_locality_code: str
    max_concurrent_travelers: int
    billing_contact_email: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false -> ONLY id + created_at (no updated_at, no version)
class PerDiemLocality(TypedDict, total=False):
    id: str
    locality_code: str
    state_code: str
    daily_lodging_cents: int
    daily_mie_cents: int
    effective_from: str
    created_at: str


class Assignment(TypedDict, total=False):
    id: str
    clinician_id: str
    facility_id: str
    covering_license_id: Optional[str]
    specialty: str
    required_license_type: str
    shift: str
    start_date: str
    term_weeks: int
    end_date: str
    staffing_status: str
    compliance_status: str
    guaranteed_hours_total: int
    guaranteed_hours_consumed: float
    guaranteed_hours_remaining: float
    guaranteed_hours_waived: float
    realized_gross_bill_cents: int
    realized_pay_cost_cents: int
    realized_margin_cents: int
    realized_margin_pct: float
    projected_gross_bill_cents: int
    projected_pay_cost_cents: int
    projected_margin_cents: int
    projected_margin_pct: float
    extension_round_count: int
    cancellation_effective_date: Optional[str]
    cancellation_notice_days: Optional[int]
    cancellation_penalty_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Contract(TypedDict, total=False):
    id: str
    assignment_id: str
    status: str
    term_weeks: int
    weekly_guaranteed_hours: float
    base_pay_rate_cents_per_hour: int
    bill_rate_cents_per_hour: int
    revision_count: int
    countersign_note: Optional[str]
    clinician_signed_at: Optional[str]
    voided_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CredentialPacket(TypedDict, total=False):
    id: str
    assignment_id: str
    status: str
    readiness_score_start_basis: int
    blocking_item_count_start_basis: int
    readiness_score_full_term_basis: int
    blocking_item_count_full_term_basis: int
    revision_round: int
    submitted_by_user_id: Optional[str]
    cleared_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CredentialItem(TypedDict, total=False):
    id: str
    packet_id: str
    item_type: str
    document_ref: str
    expires_on: Optional[str]
    status: str
    verified_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Timesheet(TypedDict, total=False):
    id: str
    assignment_id: str
    week_start_date: str
    daily_hours: List[float]
    callback_hours: float
    status: str
    total_raw_hours: float
    regular_hours: float
    overtime_hours: float
    days_worked: int
    dispute_reason: Optional[str]
    approved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EarningsStatement(TypedDict, total=False):
    id: str
    timesheet_id: Optional[str]
    assignment_id: str
    clinician_id: str
    payroll_run_id: Optional[str]
    kind: str
    period_key_date: str
    billable_hours: float
    stipend_variant: str
    taxable_wages_cents: int
    non_taxable_stipend_cents: int
    burden_cents: int
    total_pay_cost_cents: int
    contracted_bill_cents: int
    gross_bill_cents: int
    margin_uplift_applied: bool
    gross_margin_cents: int
    margin_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class PayrollRun(TypedDict, total=False):
    id: str
    period_start_date: str
    period_end_date: str
    status: str
    statement_count: int
    total_pay_cost_cents: int
    total_gross_bill_cents: int
    total_margin_cents: int
    opened_by_user_id: str
    posted_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ExtensionRequest(TypedDict, total=False):
    id: str
    assignment_id: str
    status: str
    proposed_additional_weeks: int
    proposed_pay_rate_cents_per_hour: int
    proposed_bill_rate_cents_per_hour: int
    round_count: int
    initiated_by_role: str
    last_actor_role: str
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
