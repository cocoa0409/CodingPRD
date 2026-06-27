"""Domain types: entity TypedDicts, status enums, role enum (Kids Allowance & Chore Card)."""
from enum import Enum
from typing import TypedDict, Optional, List, Dict


# ─── Status enums ─────────────────────────────────────
class FamilyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ChildAccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class JarType(str, Enum):
    SPEND = "SPEND"
    SAVE = "SAVE"
    GIVE = "GIVE"


class ChoreStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    ARCHIVED = "ARCHIVED"


class ChoreCompletionStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    NEEDS_REVISION = "NEEDS_REVISION"
    PAID = "PAID"
    DENIED = "DENIED"


class CardLockState(str, Enum):
    UNLOCKED = "UNLOCKED"
    LOCKED = "LOCKED"


class CardFundingState(str, Enum):
    FUNDED = "FUNDED"
    DRAINED = "DRAINED"


class ControlKind(str, Enum):
    STORE = "STORE"
    CATEGORY = "CATEGORY"


class ControlRule(str, Enum):
    BLOCK = "BLOCK"
    LIMIT = "LIMIT"


class TransactionStatus(str, Enum):
    PENDING = "PENDING"
    SETTLED = "SETTLED"
    DECLINED = "DECLINED"
    REVERSED = "REVERSED"


class AllowanceScheduleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"


class AllowanceRunOutcome(str, Enum):
    EXECUTED = "EXECUTED"
    SKIPPED_INSUFFICIENT_FUNDS = "SKIPPED_INSUFFICIENT_FUNDS"


class InterestAccrualMethod(str, Enum):
    WHOLE_PERIOD = "WHOLE_PERIOD"
    DAILY_AVERAGE = "DAILY_AVERAGE"


class InterestConfigStatus(str, Enum):
    ENABLED = "ENABLED"
    DISABLED = "DISABLED"


class InvestmentAccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(str, Enum):
    FILLED = "FILLED"
    REJECTED = "REJECTED"


class SpendAlertKind(str, Enum):
    LARGE_SPEND = "LARGE_SPEND"
    LOW_BALANCE = "LOW_BALANCE"


class UserRole(str, Enum):
    PARENT = "Parent"
    CHILD = "Child"
    PLATFORM_ADMIN = "PlatformAdmin"


# ─── Entity TypedDicts ────────────────────────────────
# All non-SpendAlert entities carry id + created_at + updated_at + version.
class Family(TypedDict):
    id: str
    family_name: str
    primary_parent_id: str
    funding_balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ChildAccount(TypedDict):
    id: str
    family_id: str
    display_name: str
    birthdate: str
    is_teen: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Jar(TypedDict):
    id: str
    child_account_id: str
    jar_type: str
    balance_cents: int
    lifetime_credited_cents: int
    created_at: str
    updated_at: str
    version: int


class Chore(TypedDict):
    id: str
    child_account_id: str
    title: str
    reward_cents: int
    payout_jar_type: str
    is_recurring: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class ChoreCompletion(TypedDict):
    id: str
    chore_id: str
    child_account_id: str
    reward_cents_snapshot: int
    payout_jar_type_snapshot: str
    revision_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DebitCard(TypedDict):
    id: str
    child_account_id: str
    lock_state: str
    funding_state: str
    held_cents: int
    available_cents: int
    created_at: str
    updated_at: str
    version: int


class CardControl(TypedDict):
    id: str
    debit_card_id: str
    control_kind: str
    match_value: str
    rule: str
    per_period_cap_cents: int
    is_active: bool
    created_at: str
    updated_at: str
    version: int


class Transaction(TypedDict):
    id: str
    debit_card_id: str
    child_account_id: str
    merchant_id: str
    category: str
    amount_cents: int
    settled_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AllowanceSchedule(TypedDict):
    id: str
    child_account_id: str
    amount_cents: int
    payout_jar_type: str
    cadence_days: int
    next_run_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class AllowanceRun(TypedDict):
    id: str
    allowance_schedule_id: str
    amount_cents: int
    ran_at: str
    outcome: str
    created_at: str
    updated_at: str
    version: int


class InterestMatchConfig(TypedDict):
    id: str
    child_account_id: str
    annual_rate_bps: int
    monthly_cap_cents: int
    accrual_method: str
    status: str
    created_at: str
    updated_at: str
    version: int


class InterestAccrual(TypedDict):
    id: str
    interest_match_config_id: str
    child_account_id: str
    period_days: int
    period_start_at: str
    matched_cents: int
    accrued_at: str
    created_at: str
    updated_at: str
    version: int


class InvestmentAccount(TypedDict):
    id: str
    child_account_id: str
    cash_cents: int
    holdings: Dict[str, dict]
    status: str
    created_at: str
    updated_at: str
    version: int


class InvestmentOrder(TypedDict):
    id: str
    investment_account_id: str
    side: str
    symbol: str
    shares_milli: int
    price_cents_per_share: int
    gross_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# SpendAlert: common_fields=false — carries ONLY id + created_at (no updated_at, no version).
class SpendAlert(TypedDict):
    id: str
    transaction_id: str
    child_account_id: str
    created_at: str
    alert_kind: str
    amount_cents: int
