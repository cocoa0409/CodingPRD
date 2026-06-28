"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Role enum ---
class UserRole(str, Enum):
    HOUSEHOLD_OWNER = "HouseholdOwner"
    HOUSEHOLD_MEMBER = "HouseholdMember"
    PLATFORM_ADMIN = "PlatformAdmin"


# --- Status / enum types ---
class HouseholdPosture(str, Enum):
    HEALTHY = "HEALTHY"
    OVERSPENT = "OVERSPENT"
    FROZEN = "FROZEN"


class BaseCurrency(str, Enum):
    USD = "USD"
    EUR = "EUR"
    GBP = "GBP"


class MemberRole(str, Enum):
    OWNER = "OWNER"
    MEMBER = "MEMBER"


class AccountType(str, Enum):
    DEPOSITORY = "DEPOSITORY"
    CREDIT = "CREDIT"
    LOAN = "LOAN"
    INVESTMENT = "INVESTMENT"


class AccountStatus(str, Enum):
    LINKED = "LINKED"
    ARCHIVED = "ARCHIVED"


class TransactionStatus(str, Enum):
    PENDING = "PENDING"
    POSTED = "POSTED"
    RECATEGORIZED = "RECATEGORIZED"
    REMOVED = "REMOVED"


class BudgetPeriodStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class EnvelopeState(str, Enum):
    FUNDED = "FUNDED"
    DRAWN = "DRAWN"
    OVER = "OVER"


class GoalStatus(str, Enum):
    ACTIVE = "ACTIVE"
    FUNDED = "FUNDED"
    ABANDONED = "ABANDONED"


class RecurringBillStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PAUSED = "PAUSED"


# --- Entity TypedDicts ---
# common_fields: true -> id, created_at, updated_at, version present.

class Household(TypedDict):
    id: str
    name: str
    base_currency: str
    owner_member_id: str
    current_period_id: Optional[str]
    posture: str
    net_worth_cents: int
    projected_net_worth_cents: int
    frozen_by_owner: bool
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict):
    id: str
    household_id: str
    email: str
    display_name: str
    role: str
    created_at: str
    updated_at: str
    version: int


class Account(TypedDict):
    id: str
    household_id: str
    institution_name: str
    account_type: str
    cleared_balance_cents: int
    available_balance_cents: int
    opening_balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Transaction(TypedDict):
    id: str
    account_id: str
    budget_category_id: Optional[str]
    amount_cents: int
    merchant_name: str
    posted_period_id: Optional[str]
    status: str
    state: str
    created_at: str
    updated_at: str
    version: int


class CategoryRule(TypedDict):
    id: str
    household_id: str
    match_substring: str
    budget_category_id: str
    priority: int
    enabled: bool
    created_at: str
    updated_at: str
    version: int


class BudgetPeriod(TypedDict):
    id: str
    household_id: str
    month: str
    status: str
    income_expected_cents: int
    total_allocated_cents: int
    created_at: str
    updated_at: str
    version: int


class BudgetCategory(TypedDict):
    id: str
    budget_period_id: str
    household_id: str
    name: str
    allocated_cents: int
    rollover_in_cents: int
    spent_cents: int
    available_cents: int
    envelope_state: str
    rollover_enabled: bool
    created_at: str
    updated_at: str
    version: int


class Goal(TypedDict):
    id: str
    household_id: str
    name: str
    target_cents: int
    funded_cents: int
    funding_category_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false -> append-only event: id + created_at only.
class GoalContribution(TypedDict):
    id: str
    goal_id: str
    amount_cents: int
    reversed: bool
    created_at: str


class RecurringBill(TypedDict):
    id: str
    household_id: str
    payee: str
    amount_cents: int
    day_of_month: int
    funding_category_id: str
    status: str
    created_at: str
    updated_at: str
    version: int
