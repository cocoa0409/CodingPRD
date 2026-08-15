"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.6, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    AIRPORT_ADMIN = "AirportAdmin"
    CONCESSION_ANALYST = "ConcessionAnalyst"
    TENANT = "Tenant"
    AUDITOR = "Auditor"


class LeaseStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    DEFAULTED = "DEFAULTED"
    TERMINATED = "TERMINATED"
    EXPIRED = "EXPIRED"
    REMARKETING = "REMARKETING"


class LeaseDefaultReason(str, Enum):
    NONPAYMENT = "NONPAYMENT"
    HOURS_SHORTFALL = "HOURS_SHORTFALL"
    ACDBE_NONCOMPLIANCE = "ACDBE_NONCOMPLIANCE"
    OTHER = "OTHER"


class LeaseCategory(str, Enum):
    FOOD = "FOOD"
    RETAIL = "RETAIL"
    SERVICES = "SERVICES"


class SalesReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    DISPUTED = "DISPUTED"
    ADJUSTED = "ADJUSTED"


class SettlementStatus(str, Enum):
    ACCRUING = "ACCRUING"
    INVOICED = "INVOICED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    OVERDUE = "OVERDUE"
    PAID = "PAID"


class SettlementVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class PaymentStatus(str, Enum):
    POSTED = "POSTED"
    VOIDED = "VOIDED"


class PaymentMethod(str, Enum):
    ACH = "ACH"
    CHECK = "CHECK"
    WIRE = "WIRE"
    CARD = "CARD"


class AuditStatus(str, Enum):
    OPENED = "OPENED"
    FINDINGS_ISSUED = "FINDINGS_ISSUED"
    CLOSED = "CLOSED"


class ReviewStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLIANT = "COMPLIANT"
    DEFICIENT = "DEFICIENT"
    CURED = "CURED"


class DrawStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    DISBURSED = "DISBURSED"
    CANCELLED = "CANCELLED"


class DrawMilestone(str, Enum):
    DESIGN = "DESIGN"
    CONSTRUCTION = "CONSTRUCTION"
    FIXTURES = "FIXTURES"
    GRAND_OPENING = "GRAND_OPENING"


class ViolationStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


class ViolationKind(str, Enum):
    STREET_PRICING = "STREET_PRICING"
    OPERATING_HOURS = "OPERATING_HOURS"


class WaiverStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ReviewOutcome(str, Enum):
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    UNDERPERFORMING = "UNDERPERFORMING"
    SATISFACTORY = "SATISFACTORY"


# All entities carry the four system-managed properties of PRD §2.6:
# id, created_at, updated_at, version.


class Tenant(TypedDict, total=False):
    id: str
    legal_name: str
    contact_email: str
    acdbe_certified: bool
    created_at: str
    updated_at: str
    version: int


class Lease(TypedDict, total=False):
    id: str
    tenant_id: str
    premises_code: str
    category: str
    term_start_date: str
    term_end_date: str
    mag_annual_cents: int
    pct_rate_below_bp: int
    pct_breakpoint_cents: int
    pct_rate_above_bp: int
    acdbe_goal_bp: int
    ti_allowance_cents: int
    buildout_deadline: str
    min_spe_cents: int
    status: str
    default_reason: Optional[str]
    arrears_cents: int
    ti_remaining_cents: int
    created_at: str
    updated_at: str
    version: int


class SalesReport(TypedDict, total=False):
    id: str
    lease_id: str
    period_month: str
    gross_sales_cents: int
    restated_gross_sales_cents: Optional[int]
    status: str
    submitted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RentSettlement(TypedDict, total=False):
    id: str
    lease_id: str
    period_year: int
    variant_used: str
    mag_due_cents: int
    percentage_due_cents: int
    true_up_due_cents: int
    amount_due_cents: int
    amount_paid_cents: int
    balance_due_cents: int
    due_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict, total=False):
    id: str
    settlement_id: str
    amount_cents: int
    method: str
    status: str
    created_at: str
    updated_at: str
    version: int


class AuditFinding(TypedDict, total=False):
    sales_report_id: str
    restated_gross_sales_cents: int


class AuditCase(TypedDict, total=False):
    id: str
    lease_id: str
    period_start_month: str
    period_end_month: str
    status: str
    understatement_cents: int
    created_at: str
    updated_at: str
    version: int


class ACDBEReview(TypedDict, total=False):
    id: str
    lease_id: str
    period_year: int
    certified_revenue_cents: int
    cure_additional_certified_cents: int
    total_gross_cents: int
    attainment_bp: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TIDraw(TypedDict, total=False):
    id: str
    lease_id: str
    amount_cents: int
    milestone: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PolicyViolation(TypedDict, total=False):
    id: str
    lease_id: str
    kind: str
    observed_date: str
    shortfall_minutes: Optional[int]
    overcharge_cents: Optional[int]
    penalty_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class OperatingHoursWaiver(TypedDict, total=False):
    id: str
    lease_id: str
    closure_start_date: str
    closure_end_date: str
    reason: str
    status: str
    created_at: str
    updated_at: str
    version: int


class EnplanementSnapshot(TypedDict, total=False):
    id: str
    month: str
    enplanements: int
    created_at: str
    updated_at: str
    version: int
