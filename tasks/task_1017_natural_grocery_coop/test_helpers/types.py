"""Domain types: entity TypedDicts, status enums, role enum.

Every entity in this system carries the standard system-managed fields id,
created_at, updated_at, and version (PRD §2.4), so every TypedDict includes them.
"""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    COOP_ADMIN = "CoopAdmin"
    FINANCE_MANAGER = "FinanceManager"
    INVENTORY_MANAGER = "InventoryManager"
    CASHIER = "Cashier"
    BOARD_ADMIN = "BoardAdmin"
    MEMBER = "Member"


class FiscalYearStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class MembershipStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"
    DROPPED = "DROPPED"


class VendorStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    SUSPENDED = "SUSPENDED"


class ProductStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RECALLED = "RECALLED"
    DISCONTINUED = "DISCONTINUED"


class Department(str, Enum):
    GROCERY = "GROCERY"
    PRODUCE = "PRODUCE"
    BULK = "BULK"
    CAFE_DELI = "CAFE_DELI"


class UnitType(str, Enum):
    EACH = "EACH"
    WEIGHT = "WEIGHT"


class LotStatus(str, Enum):
    DRAFT = "DRAFT"
    POSTED = "POSTED"


class RegisterStatus(str, Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"


class CheckoutStatus(str, Enum):
    BUILDING = "BUILDING"
    FINALIZED = "FINALIZED"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PAID = "PAID"
    REFUNDED = "REFUNDED"


class DealType(str, Enum):
    AD = "AD"
    MEMBER_DEAL = "MEMBER_DEAL"


class ShiftStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"


class ProposalType(str, Enum):
    BYLAW = "BYLAW"
    BUDGET = "BUDGET"
    POLICY = "POLICY"


class ProposalStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    VOTING = "VOTING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class AllocationMethod(str, Enum):
    ESTIMATED = "ESTIMATED"
    FINAL = "FINAL"


class AllocationStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    SUPERSEDED = "SUPERSEDED"


class VoteChoice(str, Enum):
    FOR = "FOR"
    AGAINST = "AGAINST"
    ABSTAIN = "ABSTAIN"


class FiscalYear(TypedDict):
    id: str
    year: int
    status: str
    patronage_rate: float
    equity_share_price_cents: int
    total_equity_cents: int
    total_patronage_cents: int
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict):
    id: str
    full_name: str
    email: str
    member_number: int
    is_board_member: bool
    membership_status: str
    equity_paid_in_cents: int
    patronage_cents_ytd: int
    working_hours_balance: float
    is_working_member: bool
    patronage_dividend_cents: int
    created_at: str
    updated_at: str
    version: int


class Vendor(TypedDict):
    id: str
    name: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict):
    id: str
    vendor_id: str
    sku: str
    name: str
    department: str
    unit_type: str
    base_price_cents: int
    tare_grams: int
    is_taxable: bool
    is_prepared_food: bool
    reorder_point: int
    reorder_qty: int
    status: str
    qty_on_hand_total: int
    needs_reorder: bool
    inventory_value_cents: int
    last_shrink_cost_cents: int
    created_at: str
    updated_at: str
    version: int


class InventoryLot(TypedDict):
    id: str
    product_id: str
    vendor_id: str
    received_qty: int
    unit_cost_cents: int
    expiry_date: Optional[str]
    status: str
    qty_on_hand: int
    qty_sold: int
    qty_shrunk: int
    created_at: str
    updated_at: str
    version: int


class Register(TypedDict):
    id: str
    name: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Sale(TypedDict):
    id: str
    register_id: str
    member_id: Optional[str]
    checkout_status: str
    payment_status: str
    lines: List[dict]
    subtotal_cents: int
    tax_total_cents: int
    total_cents: int
    patronage_eligible_cents: int
    created_at: str
    updated_at: str
    version: int


class Promotion(TypedDict):
    id: str
    product_id: str
    deal_type: str
    promo_price_cents: int
    member_only: bool
    start_date: str
    end_date: str
    created_at: str
    updated_at: str
    version: int


class WorkingMemberShift(TypedDict):
    id: str
    member_id: str
    department: str
    start_at: str
    end_at: str
    hours: float
    status: str
    created_at: str
    updated_at: str
    version: int


class BoardProposal(TypedDict):
    id: str
    title: str
    proposal_type: str
    status: str
    eligible_board_member_count: int
    voter_member_ids: List[str]
    for_count: int
    against_count: int
    abstain_count: int
    quorum_met: bool
    outcome: str
    created_at: str
    updated_at: str
    version: int


class PatronageAllocation(TypedDict):
    id: str
    fiscal_year_id: str
    method: str
    declared_rate: Optional[float]
    status: str
    total_dividend_cents: int
    total_retained_cents: int
    member_count: int
    created_at: str
    updated_at: str
    version: int
