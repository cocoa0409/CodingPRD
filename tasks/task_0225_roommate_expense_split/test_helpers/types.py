"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Role enum ────────────────────────────────────────
class UserRole(str, Enum):
    ROOMMATE = "Roommate"
    DISPUTE_MEDIATOR = "DisputeMediator"
    PLATFORM_OPERATOR = "PlatformOperator"


# ─── Status / enum value sets ─────────────────────────
class SleepSchedule(str, Enum):
    EARLY_BIRD = "EARLY_BIRD"
    NIGHT_OWL = "NIGHT_OWL"
    FLEXIBLE = "FLEXIBLE"


class SplitPolicy(str, Enum):
    EQUAL = "EQUAL"
    BY_ROOM_SIZE = "BY_ROOM_SIZE"
    BY_INCOME = "BY_INCOME"


class ScoringMode(str, Enum):
    STRICT = "STRICT"
    LENIENT = "LENIENT"


class ListingStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class MatchRequestStatus(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class HouseholdStatus(str, Enum):
    FORMING = "FORMING"
    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"
    DISSOLVED = "DISSOLVED"


class MembershipStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    MOVED_OUT = "MOVED_OUT"


class BillType(str, Enum):
    RENT = "RENT"
    UTILITIES = "UTILITIES"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"


class ReminderDimension(str, Enum):
    NONE = "NONE"
    SCHEDULED = "SCHEDULED"
    SENT = "SENT"


class ExpenseStatus(str, Enum):
    POSTED = "POSTED"
    VOIDED = "VOIDED"


class SplitMode(str, Enum):
    EQUAL = "EQUAL"
    CUSTOM = "CUSTOM"


class SettlementStatus(str, Enum):
    PROPOSED = "PROPOSED"
    CONFIRMED = "CONFIRMED"
    DISPUTED = "DISPUTED"
    CANCELLED = "CANCELLED"


class PaymentReminderStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    SENT = "SENT"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    CANCELLED = "CANCELLED"


class DisputeStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    RESOLVED = "RESOLVED"
    REJECTED = "REJECTED"


# ─── Entity TypedDicts ────────────────────────────────
# Top-level resources carry id + created_at + updated_at + version.

class RoommateProfile(TypedDict):
    id: str
    email: str
    full_name: str
    monthly_income_cents: int
    cleanliness: int
    sleep_schedule: str
    smoker: bool
    pets: bool
    net_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class RoomListing(TypedDict):
    id: str
    lister_id: str
    title: str
    monthly_rent_cents: int
    capacity: int
    room_size_sqft: int
    wants_cleanliness: int
    wants_sleep_schedule: str
    no_smokers: bool
    no_pets: bool
    split_policy: str
    status: str
    created_at: str
    updated_at: str
    version: int


class MatchRequest(TypedDict):
    id: str
    listing_id: str
    applicant_id: str
    scoring_mode: str
    compatibility_score: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Household(TypedDict):
    id: str
    listing_id: str
    manager_id: str
    split_policy: str
    status: str
    active_member_count: int
    ledger_sum_cents: int
    created_at: str
    updated_at: str
    version: int


class Membership(TypedDict):
    id: str
    household_id: str
    profile_id: str
    move_in_date: str
    planned_move_out_date: str
    actual_move_out_date: Optional[str]
    occupied_days_estimate: int
    occupied_days_actual: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Bill(TypedDict):
    id: str
    household_id: str
    bill_type: str
    total_amount_cents: int
    period_start: str
    period_end: str
    split_policy_used: str
    payment_status: str
    reminder_status: str
    created_at: str
    updated_at: str
    version: int


class Expense(TypedDict):
    id: str
    household_id: str
    payer_id: str
    description: str
    total_amount_cents: int
    split_mode: str
    participant_ids: List[str]
    share_overrides: Optional[dict]
    status: str
    created_at: str
    updated_at: str
    version: int


class Settlement(TypedDict):
    id: str
    household_id: str
    from_profile_id: str
    to_profile_id: str
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PaymentReminder(TypedDict):
    id: str
    household_id: str
    bill_id: Optional[str]
    settlement_id: Optional[str]
    due_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Dispute(TypedDict):
    id: str
    household_id: str
    expense_id: Optional[str]
    settlement_id: Optional[str]
    filed_by_id: str
    reason: str
    adjusted_amount_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


# Immutable child rows — carry ONLY id + created_at (no updated_at, no version).

class BillSplit(TypedDict):
    id: str
    bill_id: str
    profile_id: str
    share_cents: int
    paid: bool
    created_at: str


class ExpenseShare(TypedDict):
    id: str
    expense_id: str
    profile_id: str
    share_cents: int
    created_at: str
