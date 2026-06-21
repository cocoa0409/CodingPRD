"""Domain types: entity TypedDicts, status enums, role enum.

All entities in this system carry the full common-field set
(id, created_at, updated_at, version) per PRD §2.4.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Role enum (PRD §2.1) ──────────────────────────────────────────────
class UserRole(str, Enum):
    CREDIT_ANALYST = "CreditAnalyst"
    FUNDING_OFFICER = "FundingOfficer"
    SERVICER = "Servicer"
    ASSET_MANAGER = "AssetManager"


# ─── Status enums ──────────────────────────────────────────────────────
class VendorStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    SUSPENDED = "SUSPENDED"


class CreditApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    RETURNED_FOR_INFO = "RETURNED_FOR_INFO"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"


class PricingTier(str, Enum):
    PRIME = "PRIME"
    NEAR_PRIME = "NEAR_PRIME"
    SUBPRIME = "SUBPRIME"


class LeaseType(str, Enum):
    FMV = "FMV"
    DOLLAR_OUT = "DOLLAR_OUT"
    TRAC = "TRAC"


class LeaseLifecycleStatus(str, Enum):
    ORIGINATION = "ORIGINATION"
    BOOKED = "BOOKED"
    ACTIVE = "ACTIVE"
    END_OF_TERM = "END_OF_TERM"
    TERMINATED = "TERMINATED"


class LeaseFundingStatus(str, Enum):
    PENDING_FUNDING = "PENDING_FUNDING"
    FUNDED = "FUNDED"


class EquipmentUnitStatus(str, Enum):
    ON_LEASE = "ON_LEASE"
    RETURNED = "RETURNED"
    LISTED = "LISTED"
    SOLD = "SOLD"
    DISPOSED = "DISPOSED"


class ScheduleLineStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    INVOICED = "INVOICED"
    PAID = "PAID"
    WAIVED = "WAIVED"


class InvoiceStatus(str, Enum):
    OPEN = "OPEN"
    PAID = "PAID"
    VOID = "VOID"


class PaymentStatus(str, Enum):
    CLEARED = "CLEARED"
    REVERSED = "REVERSED"


class UccFilingStatus(str, Enum):
    PENDING = "PENDING"
    FILED = "FILED"
    LAPSED = "LAPSED"
    TERMINATED = "TERMINATED"


class TaxType(str, Enum):
    SALES_USE = "SALES_USE"
    PROPERTY = "PROPERTY"


class TaxAssessmentStatus(str, Enum):
    ASSESSED = "ASSESSED"
    REMITTED = "REMITTED"


class AddOnKind(str, Enum):
    ADD_ON = "ADD_ON"
    UPGRADE = "UPGRADE"


class AddOnStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPLIED = "APPLIED"
    REJECTED = "REJECTED"


class ElectionType(str, Enum):
    RENEW = "RENEW"
    RETURN = "RETURN"
    BUYOUT = "BUYOUT"


class ElectionStatus(str, Enum):
    ELECTED = "ELECTED"
    EXERCISED = "EXERCISED"
    CANCELLED = "CANCELLED"


# ─── Entity TypedDicts (all carry id/created_at/updated_at/version) ─────
class Lessor(TypedDict):
    id: str
    legal_name: str
    home_state_code: str
    sales_tax_rate_bps: int
    property_tax_rate_bps: int
    portfolio_value_cents: int
    clock_utc: str
    created_at: str
    updated_at: str
    version: int


class Vendor(TypedDict):
    id: str
    lessor_id: str
    name: str
    remit_account: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CreditApplication(TypedDict):
    id: str
    lessor_id: str
    applicant_legal_name: str
    requested_amount_cents: int
    credit_score: int
    approved_amount_cents: Optional[int]
    pricing_tier: Optional[str]
    submitted_by_user_id: Optional[str]
    revision_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Lessee(TypedDict):
    id: str
    lessor_id: str
    credit_application_id: str
    legal_name: str
    approved_credit_cents: int
    committed_credit_cents: int
    available_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class Lease(TypedDict):
    id: str
    lessee_id: str
    vendor_id: str
    lease_type: str
    equipment_cost_cents: int
    term_months: int
    monthly_rate_factor_bps: int
    trac_residual_pct_bps: Optional[int]
    advance_payment_count: int
    security_deposit_cents: int
    financed_amount_cents: int
    monthly_payment_cents: int
    residual_value_cents: int
    booked_clock_utc: Optional[str]
    lifecycle_status: str
    funding_status: str
    paid_installment_count: int
    created_at: str
    updated_at: str
    version: int


class EquipmentUnit(TypedDict):
    id: str
    lease_id: str
    serial_number: str
    description: str
    original_cost_cents: int
    assessed_value_cents: int
    status: str
    disposed_clock_utc: Optional[str]
    sale_proceeds_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class ScheduleLine(TypedDict):
    id: str
    lease_id: str
    installment_number: int
    due_clock_utc: str
    base_rent_cents: int
    is_advance: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    lease_id: str
    schedule_line_id: str
    base_rent_cents: int
    sales_tax_cents: int
    total_due_cents: int
    amount_paid_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict):
    id: str
    invoice_id: str
    lease_id: str
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class UccFiling(TypedDict):
    id: str
    lease_id: str
    jurisdiction_state_code: str
    filing_number: Optional[str]
    filed_clock_utc: Optional[str]
    coverage_end_clock_utc: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class TaxAssessment(TypedDict):
    id: str
    lease_id: str
    tax_type: str
    assessment_clock_utc: str
    taxable_base_cents: int
    tax_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AddOn(TypedDict):
    id: str
    lease_id: str
    kind: str
    replaces_equipment_unit_id: Optional[str]
    added_cost_cents: int
    incremental_payment_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class EndOfTermElection(TypedDict):
    id: str
    lease_id: str
    election: str
    renewal_months: Optional[int]
    quoted_amount_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int
