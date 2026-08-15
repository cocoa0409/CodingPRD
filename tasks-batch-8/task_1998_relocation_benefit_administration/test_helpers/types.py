"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class JobLevel(str, Enum):
    ASSOCIATE = "ASSOCIATE"
    MANAGER = "MANAGER"
    DIRECTOR = "DIRECTOR"
    EXECUTIVE = "EXECUTIVE"


class HomeOwnership(str, Enum):
    HOMEOWNER = "HOMEOWNER"
    RENTER = "RENTER"


class MoveScope(str, Enum):
    DOMESTIC = "DOMESTIC"
    INTERNATIONAL = "INTERNATIONAL"


class EmploymentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class VendorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class CaseStatus(str, Enum):
    DRAFT = "DRAFT"
    AUTHORIZED = "AUTHORIZED"
    IN_PROGRESS = "IN_PROGRESS"
    CLOSED = "CLOSED"
    CLOSED_EARLY = "CLOSED_EARLY"
    CANCELLED = "CANCELLED"


class AssignmentStatus(str, Enum):
    REQUESTED = "REQUESTED"
    SURVEY_SCHEDULED = "SURVEY_SCHEDULED"
    ESTIMATE_SUBMITTED = "ESTIMATE_SUBMITTED"
    ESTIMATE_APPROVED = "ESTIMATE_APPROVED"
    DELIVERED = "DELIVERED"
    INVOICED = "INVOICED"
    PAID = "PAID"
    CANCELLED = "CANCELLED"


class BookingKind(str, Enum):
    TEMP_HOUSING = "TEMP_HOUSING"
    TRAVEL = "TRAVEL"


class BookingStatus(str, Enum):
    HELD = "HELD"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ClaimCategory(str, Enum):
    MEALS = "MEALS"
    LODGING = "LODGING"
    TRANSPORT = "TRANSPORT"
    MISC = "MISC"


class PaymentMethod(str, Enum):
    REIMBURSEMENT = "REIMBURSEMENT"
    DIRECT_BILL = "DIRECT_BILL"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    PAID = "PAID"


class HomeSaleStatus(str, Enum):
    LISTED = "LISTED"
    SOLD = "SOLD"
    SETTLED = "SETTLED"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SETTLED = "SETTLED"
    DEFAULTED = "DEFAULTED"


class ExceptionComponent(str, Enum):
    HHG = "HHG"
    TEMP_HOUSING = "TEMP_HOUSING"
    TRAVEL = "TRAVEL"
    MISC = "MISC"
    LOSS_ON_SALE = "LOSS_ON_SALE"


class ExceptionStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class GrossUpMethod(str, Enum):
    FLAT_SUPPLEMENTAL = "FLAT_SUPPLEMENTAL"
    MARGINAL_AGGREGATE = "MARGINAL_AGGREGATE"


class LossBasis(str, Enum):
    APPRAISED = "APPRAISED"
    PURCHASE_PRICE = "PURCHASE_PRICE"


class UserRole(str, Enum):
    EMPLOYEE = "Employee"
    MOBILITY_COORDINATOR = "MobilityCoordinator"
    VENDOR = "Vendor"
    FINANCE_SPECIALIST = "FinanceSpecialist"
    PROGRAM_MANAGER = "ProgramManager"


# ---------------------------------------------------------------------------
# Entity TypedDicts — every resource carries id/created_at/updated_at/version
# ---------------------------------------------------------------------------

class Employee(TypedDict, total=False):
    id: str
    full_name: str
    job_level: str
    home_ownership: str
    employment_status: str
    termination_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RelocationPolicy(TypedDict, total=False):
    id: str
    job_level: str
    move_scope: str
    home_ownership: str
    hhg_cap_cents: int
    temp_housing_cap_cents: int
    temp_housing_max_nights: int
    travel_cap_cents: int
    loss_on_sale_cap_cents: int
    misc_cap_cents: int
    home_sale_eligible: bool
    repayment_window_months: int
    gross_up_method: str
    flat_gross_up_rate: float
    marginal_bracket_threshold_cents: int
    marginal_rate_low: float
    marginal_rate_high: float
    loss_basis: str
    created_at: str
    updated_at: str
    version: int


class Vendor(TypedDict, total=False):
    id: str
    name: str
    service_regions: List[str]
    status: str
    rating_count: int
    rating_sum: int
    avg_rating_lifetime: Optional[float]
    avg_rating_rolling_12m: Optional[float]
    completed_moves: int
    created_at: str
    updated_at: str
    version: int


class RelocationCase(TypedDict, total=False):
    id: str
    employee_id: str
    policy_id: str
    move_scope: str
    origin_city: str
    destination_city: str
    expected_move_date: str
    status: str
    authorized_at: Optional[str]
    total_committed_cents: int
    total_paid_cents: int
    total_released_cents: int
    cumulative_taxable_paid_cents: int
    created_at: str
    updated_at: str
    version: int


class MoveAssignment(TypedDict, total=False):
    id: str
    case_id: str
    vendor_id: str
    survey_at: Optional[str]
    estimated_cents: Optional[int]
    final_invoice_cents: Optional[int]
    status: str
    rating: Optional[int]
    rated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ClaimLine(TypedDict):
    description: str
    amount_cents: int


class ServiceBooking(TypedDict, total=False):
    id: str
    case_id: str
    kind: str
    start_date: str
    end_date: str
    amount_cents: int
    nights: int
    total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ExpenseClaim(TypedDict, total=False):
    id: str
    case_id: str
    category: str
    payment_method: str
    lines: List[ClaimLine]
    amount_cents: int
    taxable: bool
    gross_up_cents: int
    total_payment_cents: int
    status: str
    reject_reason: Optional[str]
    paid_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class HomeSaleTransaction(TypedDict, total=False):
    id: str
    case_id: str
    appraised_value_cents: int
    original_purchase_price_cents: int
    list_price_cents: int
    sale_price_cents: Optional[int]
    loss_basis_used: Optional[str]
    gross_loss_cents: Optional[int]
    capped_benefit_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class RepaymentAgreement(TypedDict, total=False):
    id: str
    case_id: str
    total_owed_cents: int
    installments_count: int
    installment_cents: int
    final_installment_cents: int
    signed_at: Optional[str]
    next_due_date: Optional[str]
    paid_to_date_cents: int
    balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ExceptionRequest(TypedDict, total=False):
    id: str
    case_id: str
    component: str
    requested_cap_increase_cents: int
    justification: str
    status: str
    decision_note: Optional[str]
    appeal_count: int
    created_at: str
    updated_at: str
    version: int
