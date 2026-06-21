"""Domain types for the Staffing Agency Placement API.

Entity TypedDicts, status enums, and the role enum. Mutable resources carry
id/created_at/updated_at/version; the immutable Skill and InvoiceLineItem carry
only id/created_at.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Role enum ---------------------------------------------------------------

class UserRole(str, Enum):
    RECRUITER = "Recruiter"
    ACCOUNT_MANAGER = "AccountManager"
    CLIENT = "Client"
    CANDIDATE = "Candidate"


# --- Status enums ------------------------------------------------------------

class ClientStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class SkillCategory(str, Enum):
    TECH = "TECH"
    CLINICAL = "CLINICAL"
    INDUSTRIAL = "INDUSTRIAL"
    CLERICAL = "CLERICAL"


class CandidateStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    ON_ASSIGNMENT = "ON_ASSIGNMENT"
    INACTIVE = "INACTIVE"


class EmploymentType(str, Enum):
    TEMP = "TEMP"
    TEMP_TO_PERM = "TEMP_TO_PERM"
    DIRECT = "DIRECT"


class JobOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    ON_HOLD = "ON_HOLD"
    FILLED = "FILLED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class SubmissionStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    CLIENT_REVIEW = "CLIENT_REVIEW"
    INTERVIEWING = "INTERVIEWING"
    OFFER_EXTENDED = "OFFER_EXTENDED"
    PLACED = "PLACED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class InterviewOutcome(str, Enum):
    PENDING = "PENDING"
    PASSED = "PASSED"
    FAILED = "FAILED"


class PlacementType(str, Enum):
    TEMP = "TEMP"
    TEMP_TO_PERM = "TEMP_TO_PERM"
    DIRECT = "DIRECT"


class AssignmentStatus(str, Enum):
    PENDING_START = "PENDING_START"
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"


class ConversionStatus(str, Enum):
    NONE = "NONE"
    CONVERTED = "CONVERTED"


class TimesheetStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    INVOICED = "INVOICED"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PAID = "PAID"
    VOID = "VOID"


class ConversionFeeStatus(str, Enum):
    BILLED = "BILLED"
    WAIVED = "WAIVED"


# --- Entity TypedDicts (mutable: id + created_at + updated_at + version) ------

class Client(TypedDict):
    id: str
    name: str
    credit_limit_cents: int
    conversion_fee_pct: float
    status: str
    outstanding_balance_cents: int
    open_exposure_cents: int
    created_at: str
    updated_at: str
    version: int


class Candidate(TypedDict):
    id: str
    full_name: str
    skill_codes: List[str]
    base_pay_rate_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class JobOrder(TypedDict):
    id: str
    client_id: str
    title: str
    employment_type: str
    required_skill_code: str
    openings: int
    bill_rate_cents: int
    target_pay_rate_cents: int
    annual_salary_cents: int
    filled_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Submission(TypedDict):
    id: str
    job_order_id: str
    candidate_id: str
    submitted_pay_rate_cents: int
    status: str
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Interview(TypedDict):
    id: str
    submission_id: str
    scheduled_start: str
    scheduled_end: str
    outcome: str
    created_at: str
    updated_at: str
    version: int


class Placement(TypedDict):
    id: str
    submission_id: str
    job_order_id: str
    candidate_id: str
    predecessor_placement_id: Optional[str]
    placement_type: str
    bill_rate_cents: int
    pay_rate_cents: int
    standard_weekly_hours: int
    start_date: str
    end_date: str
    projected_weekly_bill_cents: int
    projected_weekly_margin_cents: int
    actual_margin_cents: int
    assignment_status: str
    conversion_status: str
    created_at: str
    updated_at: str
    version: int


class Timesheet(TypedDict):
    id: str
    placement_id: str
    week_start: str
    week_end: str
    hours: float
    pay_cents: int
    bill_cents: int
    margin_cents: int
    status: str
    invoice_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    client_id: str
    subtotal_cents: int
    volume_discount_cents: int
    processing_fee_cents: int
    total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ConversionFee(TypedDict):
    id: str
    placement_id: str
    client_id: str
    annual_salary_cents: int
    fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# --- Immutable entities (id + created_at only; no updated_at, no version) -----

class Skill(TypedDict):
    id: str
    code: str
    category: str
    created_at: str


class InvoiceLineItem(TypedDict):
    id: str
    invoice_id: str
    timesheet_id: str
    line_total_cents: int
    created_at: str
