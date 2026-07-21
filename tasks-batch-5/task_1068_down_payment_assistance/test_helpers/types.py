"""Domain types: entity TypedDicts, status enums, role enum.

Down-Payment Assistance & Shared-Equity Program.
"""
from enum import Enum
from typing import TypedDict, Optional


# --- Roles ------------------------------------------------------------------
class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    APPLICANT = "Applicant"
    CASE_MANAGER = "CaseManager"
    PROGRAM_ADMIN = "ProgramAdmin"
    CLOSING_COORDINATOR = "ClosingCoordinator"
    SERVICER = "Servicer"


# --- Status enums -----------------------------------------------------------
class ProgramStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    NEEDS_INFO = "NEEDS_INFO"
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"
    WITHDRAWN = "WITHDRAWN"


class EnrollmentStatus(str, Enum):
    ENROLLED = "ENROLLED"
    ATTENDED = "ATTENDED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class CertificateStatus(str, Enum):
    VALID = "VALID"
    EXPIRED = "EXPIRED"


class AwardStatus(str, Enum):
    PENDING_EDUCATION = "PENDING_EDUCATION"
    APPROVED = "APPROVED"
    FUNDED = "FUNDED"
    SERVICING = "SERVICING"
    REPAID = "REPAID"
    RECAPTURED = "RECAPTURED"
    CANCELLED = "CANCELLED"


class FundingSourceStatus(str, Enum):
    ACTIVE = "ACTIVE"
    FULLY_COMMITTED = "FULLY_COMMITTED"


class FundingAllocationStatus(str, Enum):
    RESERVED = "RESERVED"
    DISBURSED = "DISBURSED"
    RELEASED = "RELEASED"


class ClosingStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DOCS_PENDING = "DOCS_PENDING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ServicingLifecycleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    IN_SALE = "IN_SALE"
    CLOSED = "CLOSED"


class ServicingPaymentStatus(str, Enum):
    CURRENT = "CURRENT"
    DELINQUENT = "DELINQUENT"


class RecaptureModel(str, Enum):
    SHARED_APPRECIATION = "SHARED_APPRECIATION"
    DECLINING_BALANCE = "DECLINING_BALANCE"


class AssistanceType(str, Enum):
    GRANT = "GRANT"
    LOAN = "LOAN"
    SHARED_APPRECIATION = "SHARED_APPRECIATION"


class UnitType(str, Enum):
    SINGLE_FAMILY = "SINGLE_FAMILY"
    CONDO = "CONDO"
    TOWNHOME = "TOWNHOME"


# --- Entity TypedDicts ------------------------------------------------------
# common_fields: true carries id, created_at, updated_at, version.
# IncomeLimit is the sole exception (id + created_at only).

class Program(TypedDict):
    id: str
    name: str
    ami_limit_pct: int
    max_assistance_cents: int
    recapture_model: str
    recapture_term_months: int
    appreciation_share_pct: int
    status: str
    created_at: str
    updated_at: str
    version: int


class IncomeLimit(TypedDict):
    id: str
    program_id: str
    household_size: int
    ami_100_income_cents: int
    created_at: str


class Applicant(TypedDict):
    id: str
    full_name: str
    email: str
    household_size: int
    annual_income_cents: int
    first_time_buyer: bool
    created_at: str
    updated_at: str
    version: int


class Property(TypedDict):
    id: str
    address: str
    county_code: str
    unit_type: str
    purchase_price_cents: int
    appraised_value_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Application(TypedDict):
    id: str
    applicant_id: str
    program_id: str
    property_id: str
    first_mortgage_amount_cents: int
    buyer_contribution_cents: int
    ami_pct: Optional[float]
    estimated_assistance_cents: Optional[int]
    reviewed_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class EducationSession(TypedDict):
    id: str
    program_id: str
    title: str
    start_at: str
    end_at: str
    capacity: int
    enrolled_count: int
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict):
    id: str
    session_id: str
    applicant_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Certificate(TypedDict):
    id: str
    applicant_id: str
    source_enrollment_id: str
    issued_at: str
    expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Award(TypedDict):
    id: str
    application_id: str
    assistance_type: str
    recapture_model: str
    assistance_amount_cents: int
    assistance_amount_final_cents: Optional[int]
    allocated_cents: int
    original_disbursed_cents: Optional[int]
    basis_value_cents: Optional[int]
    approved_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class FundingSource(TypedDict):
    id: str
    name: str
    priority: int
    total_appropriation_cents: int
    available_cents: int
    reserved_cents: int
    disbursed_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FundingAllocation(TypedDict):
    id: str
    award_id: str
    funding_source_id: str
    amount_cents: int
    lien_position: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Closing(TypedDict):
    id: str
    award_id: str
    property_id: str
    scheduled_date: str
    window_days: int
    final_purchase_price_cents: Optional[int]
    final_first_mortgage_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class ServicingAccount(TypedDict):
    id: str
    award_id: str
    opened_at: str
    principal_balance_cents: int
    recapture_amount_cents: Optional[int]
    forgiven_amount_cents: Optional[int]
    lifecycle_status: str
    payment_status: str
    created_at: str
    updated_at: str
    version: int


class SaleEvent(TypedDict):
    id: str
    servicing_account_id: str
    sale_price_cents: int
    sale_date: str
    appreciation_cents: int
    recapture_amount_cents: int
    forgiven_amount_cents: int
    created_at: str
    updated_at: str
    version: int
