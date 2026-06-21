"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the PRD's entity model and lifecycle status fields. All money is
expressed in integer cents (PRD §2.5).
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Role enum (PRD §2.1) ---
class UserRole(str, Enum):
    FACILITY_MANAGER = "FacilityManager"
    TENANT = "Tenant"
    LIEN_ADMINISTRATOR = "LienAdministrator"


# --- Status enums ---
class UnitStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    OCCUPIED = "OCCUPIED"
    VACATING = "VACATING"


class LeaseStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    DELINQUENT = "DELINQUENT"
    PRE_LIEN = "PRE_LIEN"
    LIEN = "LIEN"
    AUCTION_SCHEDULED = "AUCTION_SCHEDULED"
    AUCTIONED = "AUCTIONED"
    TRANSFERRED = "TRANSFERRED"
    CLOSED = "CLOSED"


class InvoiceStatus(str, Enum):
    OPEN = "OPEN"
    PARTIAL = "PARTIAL"
    OVERDUE = "OVERDUE"
    PAID = "PAID"
    WAIVED = "WAIVED"


class PaymentStatus(str, Enum):
    APPLIED = "APPLIED"
    REVERSED = "REVERSED"


class LedgerEntryType(str, Enum):
    CHARGE = "CHARGE"
    LATE_FEE = "LATE_FEE"
    PAYMENT = "PAYMENT"
    CREDIT = "CREDIT"
    REVERSAL = "REVERSAL"
    AUCTION_SETTLEMENT = "AUCTION_SETTLEMENT"


class LedgerSourceType(str, Enum):
    INVOICE = "INVOICE"
    PAYMENT = "PAYMENT"
    AUCTION = "AUCTION"
    MANUAL = "MANUAL"


class InsuranceStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"
    CANCELLED = "CANCELLED"


class CoverageTier(str, Enum):
    BASIC = "BASIC"
    STANDARD = "STANDARD"
    PREMIUM = "PREMIUM"


class AuctionStatus(str, Enum):
    NOTICE_SENT = "NOTICE_SENT"
    LIEN_FILED = "LIEN_FILED"
    SCHEDULED = "SCHEDULED"
    SOLD = "SOLD"
    REDEEMED = "REDEEMED"
    CANCELLED = "CANCELLED"


class SizeClass(str, Enum):
    SIZE_5X5 = "SIZE_5X5"
    SIZE_10X10 = "SIZE_10X10"
    SIZE_10X20 = "SIZE_10X20"


class TransferStatus(str, Enum):
    REQUESTED = "REQUESTED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


# --- Entity TypedDicts (common_fields: true carries id/created_at/updated_at/version) ---
class Facility(TypedDict):
    id: str
    name: str
    state_code: str
    climate_premium_pct: float
    lien_default_days: int
    late_fee_grace_days: int
    late_fee_cents: int
    occupied_unit_count: int
    created_at: str
    updated_at: str
    version: int


class Unit(TypedDict):
    id: str
    facility_id: str
    unit_number: str
    size_class: str
    climate_controlled: bool
    monthly_rate_cents: int
    status: str
    current_lease_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Tenant(TypedDict):
    id: str
    email: str
    full_name: str
    state_code: str
    phone: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Lease(TypedDict):
    id: str
    facility_id: str
    unit_id: str
    tenant_id: str
    status: str
    start_date: str
    end_date: Optional[str]
    billing_day: int
    monthly_rate_cents: int
    climate_controlled: bool
    insurance_required: bool
    balance_cents: int
    days_past_due: int
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    lease_id: str
    period_start: str
    period_end: str
    due_date: str
    base_amount_cents: int
    climate_amount_cents: int
    insurance_amount_cents: int
    late_fee_cents: int
    total_amount_cents: int
    amount_paid_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict):
    id: str
    lease_id: str
    amount_cents: int
    status: str
    allocation: List[dict]
    overpay_credit_cents: int
    created_at: str
    updated_at: str
    version: int


# common_fields: false — LedgerEntry is append-only; ONLY id + created_at
class LedgerEntry(TypedDict):
    id: str
    lease_id: str
    entry_type: str
    amount_cents: int
    source_type: str
    source_id: str
    created_at: str


class InsurancePolicy(TypedDict):
    id: str
    lease_id: str
    coverage_tier: str
    coverage_limit_cents: int
    monthly_premium_cents: int
    coverage_start: str
    coverage_end: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AuctionProceeding(TypedDict):
    id: str
    lease_id: str
    status: str
    notice_sent_date: str
    lien_filed_date: Optional[str]
    scheduled_sale_date: Optional[str]
    redemption_amount_cents: int
    sale_proceeds_cents: Optional[int]
    surplus_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class TransferOrder(TypedDict):
    id: str
    lease_id: str
    from_unit_id: str
    to_unit_id: str
    status: str
    prorated_adjustment_cents: int
    created_at: str
    updated_at: str
    version: int
