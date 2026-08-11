"""Domain types: entity shapes, status enums, and caller roles (PRD §2.1, §3)."""
from enum import Enum
from typing import Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    FARM_MANAGER = "FarmManager"
    LANDLORD = "Landlord"
    TENANT = "Tenant"
    SYSTEM = "System"


# ---------------------------------------------------------------------------
# Status enums (PRD §3)
# ---------------------------------------------------------------------------

class TenantStatus(str, Enum):
    APPLICANT = "APPLICANT"
    APPROVED = "APPROVED"
    SUSPENDED = "SUSPENDED"


class FieldStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    LEASED = "LEASED"


class DrainageStatus(str, Enum):
    POOR = "POOR"
    ADEQUATE = "ADEQUATE"
    TILED = "TILED"


class ReportChannel(str, Enum):
    EMAIL = "EMAIL"
    MAIL = "MAIL"
    PORTAL = "PORTAL"


class OfferingStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    AWARDED = "AWARDED"
    CANCELLED = "CANCELLED"


class LeaseType(str, Enum):
    CASH = "CASH"
    FLEX = "FLEX"
    SHARE = "SHARE"


class BidStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    SHORTLISTED = "SHORTLISTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class LeaseStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    TERMINATION_PENDING = "TERMINATION_PENDING"
    TERMINATED = "TERMINATED"
    CANCELLED = "CANCELLED"


class PaymentPattern(str, Enum):
    MAR_NOV_50_50 = "MAR_NOV_50_50"
    QUARTERLY = "QUARTERLY"
    FULL_MAR = "FULL_MAR"
    NONE = "NONE"


class EscalationType(str, Enum):
    NONE = "NONE"
    FIXED_PCT = "FIXED_PCT"


class InstallmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    LATE = "LATE"
    PAID = "PAID"
    WAIVED = "WAIVED"


class PriceSource(str, Enum):
    ESTIMATED = "ESTIMATED"
    ACTUAL = "ACTUAL"


class SettlementStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINALIZED = "FINALIZED"
    DISPUTED = "DISPUTED"
    COUNTERSIGNED = "COUNTERSIGNED"
    VOID = "VOID"


class ExpenseCategory(str, Enum):
    SEED = "SEED"
    FERTILIZER = "FERTILIZER"
    CHEMICAL = "CHEMICAL"
    FUEL = "FUEL"
    OTHER = "OTHER"


class ExpenseStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class PracticeType(str, Enum):
    COVER_CROP = "COVER_CROP"
    NO_TILL = "NO_TILL"
    BUFFER_STRIP = "BUFFER_STRIP"
    NUTRIENT_PLAN = "NUTRIENT_PLAN"


class ComplianceStatus(str, Enum):
    PENDING = "PENDING"
    EVIDENCE_SUBMITTED = "EVIDENCE_SUBMITTED"
    REJECTED = "REJECTED"
    VERIFIED = "VERIFIED"
    NON_COMPLIANT = "NON_COMPLIANT"
    WAIVED = "WAIVED"


class ProjectType(str, Enum):
    TILE_DRAINAGE = "TILE_DRAINAGE"
    IRRIGATION = "IRRIGATION"
    LIMING = "LIMING"
    FENCING = "FENCING"


class ReimbursementMethod(str, Enum):
    STRAIGHT_LINE = "STRAIGHT_LINE"
    AGREED_VALUE = "AGREED_VALUE"


class ReimbursementStatus(str, Enum):
    NONE = "NONE"
    DUE = "DUE"
    PAID = "PAID"


class ImprovementStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ServedBy(str, Enum):
    LANDLORD = "LANDLORD"
    TENANT = "TENANT"


class NoticeStatus(str, Enum):
    SERVED = "SERVED"
    EFFECTIVE = "EFFECTIVE"
    WITHDRAWN = "WITHDRAWN"


class ReportType(str, Enum):
    QUARTERLY = "QUARTERLY"
    ANNUAL = "ANNUAL"
    SETTLEMENT = "SETTLEMENT"
    TERMINATION = "TERMINATION"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    ACKNOWLEDGED = "ACKNOWLEDGED"


# ---------------------------------------------------------------------------
# Entity shapes (all entities carry id / created_at / updated_at / version)
# ---------------------------------------------------------------------------

class Landlord(TypedDict, total=False):
    id: str
    name: str
    contact_email: str
    absentee: bool
    report_channel: str
    ack_required_days: int
    total_received_cents: int
    pending_receivable_cents: int
    created_at: str
    updated_at: str
    version: int


class Tenant(TypedDict, total=False):
    id: str
    name: str
    years_experience: int
    status: str
    compliance_score: int
    created_at: str
    updated_at: str
    version: int


class Field(TypedDict, total=False):
    id: str
    landlord_id: str
    name: str
    acres: int
    soil_csr2: float
    drainage_status: str
    status: str
    created_at: str
    updated_at: str
    version: int


class LeaseOffering(TypedDict, total=False):
    id: str
    field_id: str
    term_years: int
    term_start_date: str
    min_bid_per_acre_cents: int
    reference_yield_bu_per_acre: int
    reference_price_cents_per_bu: int
    bid_deadline: str
    status: str
    eligible_bid_count: int
    created_at: str
    updated_at: str
    version: int


class Bid(TypedDict, total=False):
    id: str
    offering_id: str
    tenant_id: str
    lease_type: str
    cash_bid_per_acre_cents: Optional[int]
    flex_base_per_acre_cents: Optional[int]
    flex_bonus_pct: Optional[float]
    flex_cap_cents: Optional[int]
    revenue_trigger_cents: Optional[int]
    landlord_share_pct: Optional[float]
    input_share_pct: Optional[float]
    cash_equivalent_bid_cents_per_acre: int
    evaluation_score: float
    accepted_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Lease(TypedDict, total=False):
    id: str
    bid_id: str
    field_id: str
    landlord_id: str
    tenant_id: str
    lease_type: str
    term_start_date: str
    term_end_date: str
    term_index: int
    base_rent_cents_per_acre: int
    revenue_trigger_cents: Optional[int]
    landlord_bonus_pct: Optional[float]
    flex_cap_cents: Optional[int]
    landlord_share_pct: Optional[float]
    input_share_pct: Optional[float]
    escalation_type: str
    escalation_pct: Optional[float]
    payment_pattern: str
    notice_lead_days: int
    conservation_practices: list
    current_notice_deadline: str
    landlord_credit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PaymentInstallment(TypedDict, total=False):
    id: str
    lease_id: str
    term_index: int
    due_date: str
    amount_cents: int
    late_fee_cents: int
    paid_cents: int
    last_payment_at: Optional[str]
    paid_recorded_by: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class HarvestSettlement(TypedDict, total=False):
    id: str
    lease_id: str
    crop_year: int
    price_source: str
    yield_bu_per_acre: int
    harvest_price_cents_per_bu: int
    gross_revenue_cents: int
    landlord_amount_cents: int
    input_share_total_cents: int
    net_settlement_cents: int
    billed_amount_cents: Optional[int]
    true_up_cents: Optional[int]
    finalized_by: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ExpenseRecord(TypedDict, total=False):
    id: str
    lease_id: str
    category: str
    total_cost_cents: int
    incurred_date: str
    crop_year: int
    landlord_share_pct: float
    landlord_share_cents: int
    approved_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ComplianceRecord(TypedDict, total=False):
    id: str
    lease_id: str
    practice_type: str
    due_date: str
    cure_deadline: str
    evidence_note: Optional[str]
    noncompliant_at: Optional[str]
    verified_by: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ImprovementProject(TypedDict, total=False):
    id: str
    field_id: str
    lease_id: Optional[str]
    project_type: str
    total_cost_cents: int
    landlord_share_pct: float
    tenant_share_pct: float
    reimbursement_method: str
    amortization_years: int
    tenant_paid_cents: int
    completed_at: Optional[str]
    reimbursement_due_cents: Optional[int]
    reimbursement_status: str
    status: str
    created_at: str
    updated_at: str
    version: int


class TerminationNotice(TypedDict, total=False):
    id: str
    lease_id: str
    served_by: str
    served_date: str
    statutory_deadline: str
    effective_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class OwnerReport(TypedDict, total=False):
    id: str
    landlord_id: str
    report_type: str
    period_start: str
    period_end: str
    rent_collected_cents: int
    expenses_approved_cents: int
    noncompliant_count: int
    sent_at: Optional[str]
    ack_due_date: Optional[str]
    acknowledged_at: Optional[str]
    escalation_required: bool
    status: str
    created_at: str
    updated_at: str
    version: int
