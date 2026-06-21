"""Domain types: entity TypedDicts, status enums, role enum.

Field names and statuses mirror the Auto Dealership Management System PRD exactly.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --------------------------------------------------------------------------- #
# Roles
# --------------------------------------------------------------------------- #
class UserRole(str, Enum):
    INVENTORY_CLERK = "InventoryClerk"
    SALES_MANAGER = "SalesManager"
    FINANCE_MANAGER = "FinanceManager"
    SERVICE_ADVISOR = "ServiceAdvisor"
    TITLE_CLERK = "TitleClerk"
    CUSTOMER = "Customer"


# --------------------------------------------------------------------------- #
# Status enums
# --------------------------------------------------------------------------- #
class VehicleStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    ON_DEAL = "ON_DEAL"
    SOLD = "SOLD"
    RECON = "RECON"


class FloorPlanLineStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAID_OFF = "PAID_OFF"
    SUPERSEDED = "SUPERSEDED"
    REINSTATED = "REINSTATED"


class TradeInStatus(str, Enum):
    APPRAISED = "APPRAISED"
    ACCEPTED = "ACCEPTED"
    RELEASED = "RELEASED"


class DealStatus(str, Enum):
    DRAFT = "DRAFT"
    DESKING = "DESKING"
    SUBMITTED_TO_LENDER = "SUBMITTED_TO_LENDER"
    APPROVED = "APPROVED"
    CONTRACTED = "CONTRACTED"
    FUNDED = "FUNDED"
    UNWOUND = "UNWOUND"
    DEAD = "DEAD"


class DealProductStatus(str, Enum):
    ACTIVE = "ACTIVE"
    VOID = "VOID"


class FinanceContractStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    CANCELLED = "CANCELLED"


class TestDriveStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class RepairOrderStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class TitleRegistrationStatus(str, Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class Condition(str, Enum):
    NEW = "NEW"
    USED = "USED"


class CreditTier(str, Enum):
    TIER_A = "TIER_A"
    TIER_B = "TIER_B"
    TIER_C = "TIER_C"
    TIER_D = "TIER_D"


class DealType(str, Enum):
    FINANCE = "FINANCE"
    CASH = "CASH"


# --------------------------------------------------------------------------- #
# Entity TypedDicts — mutable/versioned entities carry id/created_at/updated_at/version
# --------------------------------------------------------------------------- #
class Vehicle(TypedDict, total=False):
    id: str
    vin: str
    condition: str
    make: str
    model: str
    model_year: int
    msrp_cents: int
    list_price_cents: int
    status: str
    acquired_from_trade_in_id: Optional[str]
    active_floor_plan_line_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FloorPlanLine(TypedDict, total=False):
    id: str
    vehicle_id: str
    lender_name: str
    principal_cents: int
    annual_rate_bps: int
    floored_on: str
    principal_outstanding_cents: int
    curtailments_applied: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    monthly_income_cents: int
    credit_tier: str
    drivers_license_valid: bool
    created_at: str
    updated_at: str
    version: int


class TradeIn(TypedDict, total=False):
    id: str
    deal_id: str
    vin: str
    acv_cents: int
    allowance_cents: int
    payoff_cents: int
    gross_equity_cents: int
    status: str
    acquired_vehicle_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Deal(TypedDict, total=False):
    id: str
    vehicle_id: str
    customer_id: str
    deal_type: str
    sale_price_cents: int
    accessories_cents: int
    doc_fee_cents: int
    title_fee_cents: int
    registration_fee_cents: int
    tax_rate_bps: int
    cash_down_cents: int
    applied_incentive_id: Optional[str]
    rebate_cents: int
    trade_allowance_cents: int
    trade_equity_cents: int
    total_tax_cents: int
    fi_products_total_cents: int
    amount_financed_cents: int
    front_gross_cents: int
    back_gross_cents: int
    estimated_payment_cents: int
    status: str
    approved_lender_program_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LenderProgram(TypedDict, total=False):
    id: str
    lender_name: str
    tier: str
    buy_rate_bps: int
    max_markup_bps: int
    max_ltv_bps: int
    max_pti_bps: int
    max_term_months: int
    active: bool
    created_at: str
    updated_at: str
    version: int


class FinanceProduct(TypedDict, total=False):
    id: str
    code: str
    name: str
    cost_cents: int
    max_retail_cents: int
    taxable: bool
    created_at: str
    updated_at: str
    version: int


class DealProduct(TypedDict, total=False):
    id: str
    deal_id: str
    finance_product_id: str
    sold_price_cents: int
    product_cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FinanceContract(TypedDict, total=False):
    id: str
    deal_id: str
    lender_program_id: str
    markup_bps: int
    term_months: int
    sell_rate_bps: int
    amount_financed_snapshot_cents: int
    monthly_payment_cents: int
    finance_reserve_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class OEMIncentive(TypedDict, total=False):
    id: str
    program_code: str
    rebate_cents: int
    eligible_condition: str
    eligible_make: Optional[str]
    min_model_year: Optional[int]
    stackable_with_finance: bool
    active: bool
    created_at: str
    updated_at: str
    version: int


class TestDrive(TypedDict, total=False):
    id: str
    vehicle_id: str
    customer_id: str
    start_at: str
    end_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RepairOrder(TypedDict, total=False):
    id: str
    vehicle_id: str
    deal_id: Optional[str]
    ro_type: str
    bay: str
    scheduled_start_at: str
    scheduled_end_at: str
    parts_cents: int
    labor_cents: int
    total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TitleRegistration(TypedDict, total=False):
    id: str
    deal_id: str
    owner_name: str
    plate_type: str
    rejection_reason: Optional[str]
    resubmit_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only, immutable: carries ONLY id + created_at (no updated_at, no version)
class DealJacketDocument(TypedDict, total=False):
    id: str
    deal_id: str
    doc_type: str
    uri: str
    created_at: str
