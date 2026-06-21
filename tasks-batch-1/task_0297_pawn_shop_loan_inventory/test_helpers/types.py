"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the PRD's entities and lifecycle states. Append-only event records
(FinanceTransaction, LayawayInstallment) carry only id + created_at — no
updated_at, no version (PRD §2.4).
"""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    APPRAISER = "Appraiser"
    LOAN_OFFICER = "LoanOfficer"
    SHOP_MANAGER = "ShopManager"
    CUSTOMER = "Customer"
    LAW_ENFORCEMENT = "LawEnforcement"


class StateCode(str, Enum):
    FL = "FL"
    TX = "TX"
    CA = "CA"


class PawnItemStatus(str, Enum):
    INTAKE = "INTAKE"
    APPRAISED = "APPRAISED"
    PLEDGED = "PLEDGED"
    REDEEMED = "REDEEMED"
    FORFEITED = "FORFEITED"
    RELEASED_TO_POLICE = "RELEASED_TO_POLICE"


class PoliceReportStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING_REPORT = "PENDING_REPORT"
    REPORTED = "REPORTED"


class LoanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    IN_GRACE = "IN_GRACE"
    REDEEMED = "REDEEMED"
    FORFEITED = "FORFEITED"
    VOIDED = "VOIDED"
    POLICE_HELD = "POLICE_HELD"


class FinanceTransactionKind(str, Enum):
    DISBURSEMENT = "DISBURSEMENT"
    EXTENSION_FEE = "EXTENSION_FEE"
    RENEWAL_FEE = "RENEWAL_FEE"
    REDEMPTION_PAYOFF = "REDEMPTION_PAYOFF"
    VOID_REVERSAL = "VOID_REVERSAL"


class InventoryItemStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    ON_LAYAWAY = "ON_LAYAWAY"
    SOLD = "SOLD"
    RECALLED = "RECALLED"


class LayawayPlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DEFAULTED = "DEFAULTED"
    COMPLETED = "COMPLETED"


class PoliceHoldStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"
    EXECUTED = "EXECUTED"


class PoliceHoldSubjectKind(str, Enum):
    PAWN_ITEM = "PAWN_ITEM"
    INVENTORY_ITEM = "INVENTORY_ITEM"


# ─── Entities carrying id + created_at + updated_at + version (PRD §2.4) ───

class PawnShop(TypedDict):
    id: str
    name: str
    state_code: str
    police_reporting_enabled: bool
    cash_drawer_id: str
    created_at: str
    updated_at: str
    version: int


class StorageBin(TypedDict):
    id: str
    shop_id: str
    label: str
    capacity: int
    created_at: str
    updated_at: str
    version: int


class StateRateSchedule(TypedDict):
    id: str
    state_code: str
    monthly_interest_bps: int
    monthly_storage_fee_cents: int
    setup_fee_cents: int
    term_days: int
    grace_days: int
    max_principal_cents: int
    max_periods_total: int
    loan_to_value_bps: int
    layaway_buffer_days: int
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict):
    id: str
    full_name: str
    gov_id_number: str
    is_flagged: bool
    created_at: str
    updated_at: str
    version: int


class PawnItem(TypedDict):
    id: str
    shop_id: str
    customer_id: str
    description: str
    serial_number: Optional[str]
    appraised_value_cents: Optional[int]
    appraised_by_user_id: Optional[str]
    status: str
    police_report_status: str
    created_at: str
    updated_at: str
    version: int


class Loan(TypedDict):
    id: str
    shop_id: str
    pawn_item_id: str
    storage_bin_id: str
    customer_id: str
    state_code: str
    principal_cents: int
    setup_fee_cents: int
    origination_at: str
    term_end_at: str
    grace_end_at: str
    periods_charged: int
    renewal_count: int
    police_hold_flag: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class InventoryItem(TypedDict):
    id: str
    shop_id: str
    source_loan_id: str
    pawn_item_id: str
    cost_basis_cents: int
    appraised_value_cents: int
    list_price_cents: int
    floor_price_cents: int
    sold_price_cents: Optional[int]
    last_layaway_end_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class LayawayPlan(TypedDict):
    id: str
    inventory_item_id: str
    customer_id: str
    total_price_cents: int
    deposit_cents: int
    installment_count: int
    reserved_from_at: str
    reserved_until_at: str
    paid_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PoliceHold(TypedDict):
    id: str
    subject_kind: str
    pawn_item_id: Optional[str]
    inventory_item_id: Optional[str]
    case_number: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CashDrawer(TypedDict):
    id: str
    shop_id: str
    balance_cents: int
    created_at: str
    updated_at: str
    version: int


# ─── Append-only event records: id + created_at ONLY (PRD §2.4) ───

class FinanceTransaction(TypedDict):
    id: str
    loan_id: str
    kind: str
    amount_cents: int
    periods_in_charge: int
    created_at: str


class LayawayInstallment(TypedDict):
    id: str
    layaway_plan_id: str
    sequence: int
    amount_cents: int
    paid: bool
    created_at: str
