"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3).

Fill and AuditEvent are append-only kinds: per PRD §2.4 they carry only
``id`` and ``created_at`` — their TypedDicts deliberately omit ``updated_at``
and ``version``.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class AccountType(str, Enum):
    DISCRETIONARY = "DISCRETIONARY"
    PROPRIETARY = "PROPRIETARY"
    ERROR = "ERROR"


class SecurityStatus(str, Enum):
    ACTIVE = "ACTIVE"
    HALTED = "HALTED"


class AssetClass(str, Enum):
    EQUITY = "EQUITY"
    FIXED_INCOME = "FIXED_INCOME"


class BrokerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class BudgetStatus(str, Enum):
    OPEN = "OPEN"
    EXHAUSTED = "EXHAUSTED"


class RestrictionStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    RETIRED = "RETIRED"


class RuleType(str, Enum):
    PROHIBITED = "PROHIBITED"
    MAX_POSITION_UNITS = "MAX_POSITION_UNITS"


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    BOTH = "BOTH"


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


class OrderStatus(str, Enum):
    PENDING_COMPLIANCE = "PENDING_COMPLIANCE"
    COMPLIANCE_REJECTED = "COMPLIANCE_REJECTED"
    APPROVED = "APPROVED"
    BLOCKED = "BLOCKED"
    ALLOCATED = "ALLOCATED"
    UNDER_CORRECTION = "UNDER_CORRECTION"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"


class BlockStatus(str, Enum):
    OPEN = "OPEN"
    WORKING = "WORKING"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"


class AllocationStatus(str, Enum):
    UNALLOCATED = "UNALLOCATED"
    PARTIAL = "PARTIAL"
    FULL = "FULL"


class PlanMethod(str, Enum):
    PRO_RATA = "PRO_RATA"
    EQUAL_SPLIT = "EQUAL_SPLIT"


class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    POSTED = "POSTED"
    SUPERSEDED = "SUPERSEDED"


class AllocationLineStatus(str, Enum):
    PROPOSED = "PROPOSED"
    POSTED = "POSTED"
    SETTLED = "SETTLED"
    ERROR_FLAGGED = "ERROR_FLAGGED"
    REVERSED = "REVERSED"


class ErrorType(str, Enum):
    WRONG_ACCOUNT = "WRONG_ACCOUNT"
    WRONG_QTY = "WRONG_QTY"
    WRONG_PRICE = "WRONG_PRICE"


class TradeErrorStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    DISMISSED = "DISMISSED"


class InstructionStatus(str, Enum):
    PENDING = "PENDING"
    INSTRUCTED = "INSTRUCTED"
    SETTLED = "SETTLED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class FailReason(str, Enum):
    BROKER_NON_DELIVERY = "BROKER_NON_DELIVERY"
    CUSTODIAN_MISMATCH = "CUSTODIAN_MISMATCH"
    INSUFFICIENT_POSITION = "INSUFFICIENT_POSITION"
    OTHER = "OTHER"


class UserRole(str, Enum):
    TRADER = "Trader"
    EXECUTION_DESK = "ExecutionDesk"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    SETTLEMENT_OPS = "SettlementOps"
    DESK_ADMIN = "DeskAdmin"
    AUDITOR = "Auditor"


class Account(TypedDict, total=False):
    id: str
    account_code: str
    display_name: str
    account_type: str
    custodian_name: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Security(TypedDict, total=False):
    id: str
    ticker: str
    asset_class: str
    currency: str
    lot_size: int
    reference_price_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Broker(TypedDict, total=False):
    id: str
    broker_code: str
    display_name: str
    commission_rate_bp: float
    supported_asset_classes: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CommissionBudget(TypedDict, total=False):
    id: str
    account_id: str
    period_start: str
    period_end: str
    budget_amount_cents: int
    accrued_commission_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Restriction(TypedDict, total=False):
    id: str
    account_id: Optional[str]
    security_id: Optional[str]
    rule_type: str
    side: str
    threshold_units: Optional[int]
    effective_from: str
    effective_to: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict, total=False):
    id: str
    account_id: str
    security_id: str
    side: str
    order_qty: int
    order_type: str
    limit_price_cents: Optional[int]
    block_id: Optional[str]
    status: str
    allocated_qty: int
    avg_executed_price_cents: Optional[int]
    compliance_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BlockOrder(TypedDict, total=False):
    id: str
    security_id: str
    side: str
    broker_id: Optional[str]
    total_qty: int
    filled_qty: int
    avg_fill_price_cents: Optional[int]
    routed_at: Optional[str]
    allocated_through_seq: int
    status: str
    allocation_status: str
    created_at: str
    updated_at: str
    version: int


# Append-only (PRD §2.4): carries ONLY id + created_at — no updated_at, no version.
class Fill(TypedDict, total=False):
    id: str
    block_id: str
    fill_qty: int
    fill_price_cents: int
    executed_at: str
    fill_seq: int
    gross_amount_cents: int
    created_at: str


class AllocationPlan(TypedDict, total=False):
    id: str
    block_id: str
    method: str
    status: str
    covered_from_seq: int
    covered_to_seq: Optional[int]
    batch_qty: Optional[int]
    batch_avg_price_cents: Optional[int]
    max_deviation_bp: Optional[int]
    created_by_user_id: str
    approved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Allocation(TypedDict, total=False):
    id: str
    plan_id: str
    account_id: str
    order_id: str
    alloc_qty: int
    alloc_price_cents: int
    commission_cents: int
    status: str
    corrects_allocation_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TradeError(TypedDict, total=False):
    id: str
    allocation_id: str
    error_type: str
    note: Optional[str]
    status: str
    flagged_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class SettlementInstruction(TypedDict, total=False):
    id: str
    allocation_id: str
    custodian_name: str
    trade_date: str
    settle_date: str
    instruction_status: str
    fail_reason: Optional[str]
    fail_count: int
    created_at: str
    updated_at: str
    version: int


class Position(TypedDict, total=False):
    id: str
    account_id: str
    security_id: str
    net_qty: int
    created_at: str
    updated_at: str
    version: int


# Append-only (PRD §2.4): carries ONLY id + created_at — no updated_at, no version.
class AuditEvent(TypedDict, total=False):
    id: str
    entity_type: str
    entity_id: str
    action: str
    actor_role: str
    actor_user_id: str
    detail: str
    created_at: str
