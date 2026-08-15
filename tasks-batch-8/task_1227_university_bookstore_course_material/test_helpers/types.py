"""Domain types: entity TypedDicts, status enums, role enum.

The PRD guarantees every persisted resource carries id, created_at,
updated_at, and version — including OrderLine and InclusiveAccessCharge.
"""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    BOOKSTORE_MANAGER = "BookstoreManager"
    FINANCE_ADMIN = "FinanceAdmin"
    FACULTY = "Faculty"
    STUDENT = "Student"


class TermStatus(str, Enum):
    SETUP = "SETUP"
    ADOPTION_OPEN = "ADOPTION_OPEN"
    ADOPTION_CLOSED = "ADOPTION_CLOSED"
    SALES_OPEN = "SALES_OPEN"
    CENSUS_DONE = "CENSUS_DONE"
    BUYBACK_OPEN = "BUYBACK_OPEN"
    TERM_CLOSED = "TERM_CLOSED"


class CompliancePosture(str, Enum):
    CLEAR = "CLEAR"
    RESTRICTED = "RESTRICTED"


class SectionStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    LOCKED = "LOCKED"
    CLOSED = "CLOSED"


class SectionCompliance(str, Enum):
    PENDING = "PENDING"
    COMPLIANT = "COMPLIANT"
    NON_COMPLIANT = "NON_COMPLIANT"


class EnrollmentStatus(str, Enum):
    ENROLLED = "ENROLLED"
    DROPPED = "DROPPED"


class AdoptionStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    RETURNED = "RETURNED"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"


class BuyPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    COMMITTED = "COMMITTED"
    RECEIVED = "RECEIVED"
    CANCELLED = "CANCELLED"


class OrderStatus(str, Enum):
    SETTLED = "SETTLED"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"
    REFUNDED = "REFUNDED"
    CLOSED = "CLOSED"


class OrderLineStatus(str, Enum):
    FULFILLED = "FULFILLED"
    RETURNED = "RETURNED"


class OrderLineFormat(str, Enum):
    NEW = "NEW"
    USED = "USED"
    RENTAL = "RENTAL"
    DIGITAL = "DIGITAL"


class IAChargeStatus(str, Enum):
    PENDING = "PENDING"
    OPTED_OUT = "OPTED_OUT"
    BILLED = "BILLED"
    REFUNDED = "REFUNDED"
    CANCELLED = "CANCELLED"


class ConditionGrade(str, Enum):
    LIKE_NEW = "LIKE_NEW"
    GOOD = "GOOD"
    ACCEPTABLE = "ACCEPTABLE"


class BuybackTicketStatus(str, Enum):
    QUOTED = "QUOTED"
    ACCEPTED = "ACCEPTED"
    PAID = "PAID"
    EXPIRED = "EXPIRED"
    REJECTED = "REJECTED"


class PricingVariant(str, Enum):
    NEEDS_BASED = "NEEDS_BASED"
    WHOLESALE = "WHOLESALE"


class CalculationVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class CommissionStatementStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    SETTLED = "SETTLED"


class AcademicTerm(TypedDict, total=False):
    id: str
    code: str
    length_weeks: int
    registration_open_at: str
    price_posting_deadline_at: str
    adoption_deadline_at: str
    aid_charge_window_start_at: str
    aid_charge_window_end_at: str
    add_drop_return_deadline_at: str
    census_at: str
    ia_opt_out_deadline_at: str
    buyback_window_start_at: str
    buyback_window_end_at: str
    buy_budget_cents: int
    status: str
    noncompliant_section_count: int
    compliance_posture: str
    created_at: str
    updated_at: str
    version: int


class Publisher(TypedDict, total=False):
    id: str
    name: str
    created_at: str
    updated_at: str
    version: int


class PublisherAgreement(TypedDict, total=False):
    id: str
    publisher_id: str
    start_date: str
    end_date: str
    discount_pct: float
    digital_discount_pct: float
    commission_pct: float
    created_at: str
    updated_at: str
    version: int


class Title(TypedDict, total=False):
    id: str
    isbn: str
    publisher_id: str
    list_price_cents: int
    has_new: bool
    has_used: bool
    has_rental: bool
    has_digital: bool
    initial_new_stock_qty: int
    initial_used_stock_qty: int
    initial_rental_stock_qty: int
    new_stock_qty: int
    used_stock_qty: int
    rental_stock_qty: int
    created_at: str
    updated_at: str
    version: int


class Faculty(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    created_at: str
    updated_at: str
    version: int


class Student(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    awarded_aid_cents: int
    aid_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class CourseSection(TypedDict, total=False):
    id: str
    term_id: str
    faculty_id: str
    course_code: str
    section_code: str
    enrollment_capacity: int
    ia_enabled: bool
    ia_material_fee_cents: Optional[int]
    status: str
    compliance_status: str
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict, total=False):
    id: str
    section_id: str
    student_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Adoption(TypedDict, total=False):
    id: str
    section_id: str
    title_id: str
    faculty_id: str
    qty_new_requested: int
    qty_used_requested: int
    qty_rental_requested: int
    qty_digital_requested: int
    posted_price_cents: Optional[int]
    status: str
    submitted_at: Optional[str]
    late_flag: bool
    transparency_late_flag: bool
    review_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BuyPlan(TypedDict, total=False):
    id: str
    adoption_id: str
    qty_new: int
    qty_used: int
    qty_rental: int
    qty_digital: int
    discount_pct_applied: float
    tier_bonus_applied: bool
    landed_cost_cents: int
    status: str
    committed_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict, total=False):
    id: str
    student_id: str
    term_id: str
    aid_only: bool
    total_cents: int
    aid_tendered_cents: int
    card_tendered_cents: int
    refund_total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict, total=False):
    id: str
    order_id: str
    adoption_id: str
    title_id: str
    format: str
    qty: int
    unit_price_cents: int
    line_total_cents: int
    aid_tendered_cents: int
    card_tendered_cents: int
    aid_refunded_cents: int
    card_refunded_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class InclusiveAccessCharge(TypedDict, total=False):
    id: str
    enrollment_id: str
    section_id: str
    student_id: str
    term_id: str
    fee_cents: int
    aid_applied_cents: int
    balance_due_cents: int
    status: str
    opted_out_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WholesaleQuote(TypedDict, total=False):
    id: str
    title_id: str
    condition: str
    price_cents: int
    effective_from: str
    effective_to: str
    created_at: str
    updated_at: str
    version: int


class BuybackTicket(TypedDict, total=False):
    id: str
    student_id: str
    title_id: str
    upcoming_term_id: str
    condition: str
    pricing_variant: str
    quoted_price_cents: int
    quote_valid_until: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CommissionStatement(TypedDict, total=False):
    id: str
    publisher_id: str
    term_id: str
    calculation_variant: str
    gross_sales_cents: int
    returns_cents: int
    net_sales_cents: int
    commission_cents: int
    status: str
    issued_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int
