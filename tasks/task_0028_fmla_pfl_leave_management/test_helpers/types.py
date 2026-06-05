"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §3.1–§3.7)."""
from enum import Enum
from typing import List, Optional, TypedDict


# ─── Roles (PRD §2.1) ────────────────────────────────────────────────────────


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    HR_ADMIN = "HRAdmin"
    EMPLOYEE = "Employee"
    HEALTHCARE_PROVIDER = "HealthcareProvider"


# ─── Status enums ────────────────────────────────────────────────────────────


class StateCode(str, Enum):
    CA = "CA"
    NY = "NY"
    NJ = "NJ"
    MA = "MA"
    WA = "WA"
    CT = "CT"
    RI = "RI"
    CO = "CO"
    OR = "OR"
    FED = "FED"


class FmlaMethod(str, Enum):
    ROLLING_BACKWARD = "ROLLING_BACKWARD"
    CALENDAR_YEAR = "CALENDAR_YEAR"


class EmploymentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ON_LEAVE = "ON_LEAVE"
    TERMINATED = "TERMINATED"


class QualifyingReason(str, Enum):
    OWN_SERIOUS_HEALTH_CONDITION = "OWN_SERIOUS_HEALTH_CONDITION"
    FAMILY_SERIOUS_HEALTH_CONDITION = "FAMILY_SERIOUS_HEALTH_CONDITION"
    NEW_CHILD_BONDING = "NEW_CHILD_BONDING"
    MILITARY_CAREGIVER = "MILITARY_CAREGIVER"
    QUALIFYING_EXIGENCY = "QUALIFYING_EXIGENCY"


class LeaveType(str, Enum):
    CONTINUOUS = "CONTINUOUS"
    INTERMITTENT = "INTERMITTENT"
    REDUCED_SCHEDULE = "REDUCED_SCHEDULE"


class LeaveCaseStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ELIGIBILITY_PENDING = "ELIGIBILITY_PENDING"
    CERTIFICATION_PENDING = "CERTIFICATION_PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    JOB_RESTORED = "JOB_RESTORED"
    JOB_FORFEITED = "JOB_FORFEITED"


class CertificationStatus(str, Enum):
    PENDING = "PENDING"
    RECEIVED = "RECEIVED"
    INSUFFICIENT = "INSUFFICIENT"
    COMPLETE = "COMPLETE"
    RECERTIFICATION_REQUESTED = "RECERTIFICATION_REQUESTED"


class LeaveIntervalStatus(str, Enum):
    RECORDED = "RECORDED"
    REVERSED = "REVERSED"


class PaymentStatus(str, Enum):
    PENDING = "PENDING"
    PARTIAL = "PARTIAL"
    PAID = "PAID"
    DELINQUENT = "DELINQUENT"


class NoticeType(str, Enum):
    ELIGIBILITY_NOTICE = "ELIGIBILITY_NOTICE"
    RIGHTS_RESPONSIBILITIES_NOTICE = "RIGHTS_RESPONSIBILITIES_NOTICE"
    DESIGNATION_NOTICE = "DESIGNATION_NOTICE"
    CERTIFICATION_DEMAND = "CERTIFICATION_DEMAND"
    RECERTIFICATION_REQUEST = "RECERTIFICATION_REQUEST"


# ─── Entity TypedDicts (common_fields: true → id+created_at+updated_at+version) ──


class Employer(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    legal_name: str
    state_code: str
    fmla_method: str
    pfl_enabled: bool
    employer_premium_share_pct: float
    monthly_premium_total_cents: int


class Employee(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    employer_id: str
    email: str
    full_name: str
    hire_date: str
    hours_worked_trailing_12mo: int
    home_state_code: str
    health_plan_enrolled: bool
    employment_status: str
    job_restoration_deadline: Optional[str]


class HealthcareProvider(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    license_id: str
    full_name: str
    specialty: str


class LeaveCase(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    employee_id: str
    qualifying_reason: str
    leave_type: str
    requested_start_at: str
    requested_end_at: str
    status: str
    eligibility_evaluated: bool
    tenure_months_at_request: Optional[int]
    hours_at_request: Optional[int]
    pfl_concurrent: bool
    fmla_hours_charged: float
    pfl_hours_charged: float
    job_restoration_protected: bool


class CertificationRecord(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    leave_case_id: str
    provider_id: str
    certification_status: str
    expected_duration_weeks: float
    intermittent_frequency_per_month: Optional[int]
    intermittent_hours_per_episode: Optional[float]
    provider_attestation_signed_at: str
    received_at: Optional[str]
    insufficient_reason: Optional[str]


class LeaveInterval(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    leave_case_id: str
    start_datetime: str
    end_datetime: str
    hours_taken: float
    fmla_hours_charged: float
    pfl_hours_charged: float
    status: str


class BenefitContinuationLedger(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    employee_id: str
    leave_case_id: str
    period_start: str
    period_end: str
    employer_premium_share_cents: int
    employee_premium_share_cents: int
    employee_owes_cents: int
    payments_received_cents: int
    payment_status: str


class Notice(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    leave_case_id: str
    notice_type: str
    sent_at: str
    response_due_at: Optional[str]
    response_received: bool
