"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    COOP_ADMIN = "CoopAdmin"
    GIN_OPERATOR = "GinOperator"
    CLASSING_CLERK = "ClassingClerk"
    WAREHOUSE_MANAGER = "WarehouseManager"
    COOP_ACCOUNTANT = "CoopAccountant"
    GROWER = "Grower"


class GinShiftStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    RECONCILED = "RECONCILED"


class ModuleStatus(str, Enum):
    RECEIVED = "RECEIVED"
    CONDITIONING = "CONDITIONING"
    QUEUED = "QUEUED"
    GINNING = "GINNING"
    GINNED = "GINNED"
    REJECTED = "REJECTED"


class BaleClassingStatus(str, Enum):
    UNCLASSED = "UNCLASSED"
    CLASSED = "CLASSED"


class BaleCustodyStatus(str, Enum):
    ON_GIN_FLOOR = "ON_GIN_FLOOR"
    WAREHOUSED = "WAREHOUSED"
    SHIPPED = "SHIPPED"


class ClassingResultStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class ReceiptStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PLEDGED = "PLEDGED"
    RELEASED = "RELEASED"
    SHIPPED = "SHIPPED"
    FORFEITED = "FORFEITED"
    CANCELLED = "CANCELLED"


class PledgeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REPAID = "REPAID"
    FORFEITED = "FORFEITED"


class OrderStatus(str, Enum):
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    SHIPPED = "SHIPPED"
    CANCELLED = "CANCELLED"


class SettlementStatus(str, Enum):
    DRAFT = "DRAFT"
    FINAL = "FINAL"
    PAID = "PAID"
    SUPERSEDED = "SUPERSEDED"


class ComputationVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class LedgerEntryType(str, Enum):
    GINNING_CHARGE = "GINNING_CHARGE"
    SEED_CREDIT = "SEED_CREDIT"
    STORAGE_CHARGE = "STORAGE_CHARGE"
    LOAN_ADVANCE = "LOAN_ADVANCE"
    LOAN_REPAYMENT = "LOAN_REPAYMENT"
    ADJUSTMENT = "ADJUSTMENT"
    PATRONAGE = "PATRONAGE"
    SETTLEMENT_PAYMENT = "SETTLEMENT_PAYMENT"


class Grower(TypedDict, total=False):
    id: str
    membership_number: str
    legal_name: str
    credit_balance_cents: int
    patronage_rate: float
    created_at: str
    updated_at: str
    version: int


class GradeSchedule(TypedDict, total=False):
    id: str
    grade_code: str
    premium_discount_points: int
    loan_rate_points: int
    effective_from: str
    effective_to: str
    created_at: str
    updated_at: str
    version: int


class Warehouse(TypedDict, total=False):
    id: str
    name: str
    capacity_bales: int
    stored_bale_count: int
    dock_count: int
    created_at: str
    updated_at: str
    version: int


class GinShift(TypedDict, total=False):
    id: str
    season: str
    stand_label: str
    status: str
    actual_lint_scale_lbs: int
    actual_seed_scale_lbs: int
    waste_lbs: int
    created_at: str
    updated_at: str
    version: int


class ModuleReceipt(TypedDict, total=False):
    id: str
    grower_id: str
    season: str
    ticket_number: str
    module_tag: str
    gross_weight_lbs: int
    tare_weight_lbs: int
    net_weight_lbs: int
    moisture_pct: float
    foreign_matter_pct: float
    gin_shift_id: Optional[str]
    status: str
    est_lint_lbs: int
    est_seed_lbs: int
    actual_lint_lbs: int
    reconciled_seed_lbs: Optional[int]
    ginned_at: Optional[str]
    ginned_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Bale(TypedDict, total=False):
    id: str
    module_id: str
    bale_tag: str
    net_weight_lbs: int
    classing_status: str
    custody_status: str
    active_grade_code: Optional[str]
    quality_points: Optional[int]
    adjustment_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class ClassingResult(TypedDict, total=False):
    id: str
    bale_id: str
    grade_code: str
    micronaire: float
    strength_gpt: float
    staple_32nds: int
    classing_office: str
    result_date: str
    status: str
    quality_points: int
    adjustment_cents: int
    created_at: str
    updated_at: str
    version: int


class WarehouseReceipt(TypedDict, total=False):
    id: str
    bale_id: str
    warehouse_id: str
    receipt_number: str
    storage_start_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class LoanPledge(TypedDict, total=False):
    id: str
    warehouse_receipt_id: str
    loan_rate_points: int
    principal_cents: int
    interest_cents: int
    pledged_date: str
    redeemed_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SeedSale(TypedDict, total=False):
    id: str
    gin_shift_id: str
    buyer_name: str
    price_cents_per_lb: int
    sold_lbs: int
    net_pool_cents: int
    created_at: str
    updated_at: str
    version: int


class ShippingOrder(TypedDict, total=False):
    id: str
    warehouse_id: str
    grower_id: str
    bale_ids: list
    dock_number: int
    load_start: str
    load_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Settlement(TypedDict, total=False):
    id: str
    grower_id: str
    season: str
    computation_variant: str
    status: str
    lint_value_cents: int
    quality_adjustment_cents: int
    seed_credit_cents: int
    ginning_charge_cents: int
    storage_charge_cents: int
    loan_net_cents: int
    adjustment_net_cents: int
    patronage_cents: int
    net_payable_cents: int
    paid_amount_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


# Append-only event log: carries ONLY id + created_at (no updated_at, no version).
class LedgerEntry(TypedDict, total=False):
    id: str
    grower_id: str
    settlement_id: Optional[str]
    season: str
    entry_type: str
    amount_cents: int
    memo: str
    created_at: str
