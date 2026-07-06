"""Domain types: entity TypedDicts, status enums, role enum (Comic Book Shop API)."""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    CUSTOMER = "Customer"
    CLERK = "Clerk"
    MANAGER = "Manager"


# ---------------------------------------------------------------------------
# Status / enum value sets
# ---------------------------------------------------------------------------
class CustomerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    BANNED = "BANNED"


class LoyaltyTier(str, Enum):
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"


class ComicSeriesStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class ComicIssueStatus(str, Enum):
    SOLICITED = "SOLICITED"
    ORDERED = "ORDERED"
    ON_SALE = "ON_SALE"
    CLOSED = "CLOSED"


class PullSubscriptionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"


class ReservationStatus(str, Enum):
    RESERVED = "RESERVED"
    WAITLISTED = "WAITLISTED"
    ALLOCATED = "ALLOCATED"
    PULLED = "PULLED"
    SOLD = "SOLD"
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"


class PreOrderStatus(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class BackIssueCondition(str, Enum):
    RAW = "RAW"
    GRADED = "GRADED"


class BackIssueStatus(str, Enum):
    IN_STOCK = "IN_STOCK"
    RESERVED = "RESERVED"
    SOLD = "SOLD"


class GradingSubmissionStatus(str, Enum):
    INTAKE = "INTAKE"
    SUBMITTED = "SUBMITTED"
    AT_GRADER = "AT_GRADER"
    RETURNED = "RETURNED"
    READY_FOR_PICKUP = "READY_FOR_PICKUP"
    PICKED_UP = "PICKED_UP"


class CreditTransactionReason(str, Enum):
    CONSIGNMENT_PAYOUT = "CONSIGNMENT_PAYOUT"
    REFUND = "REFUND"
    ADJUSTMENT = "ADJUSTMENT"
    REDEMPTION = "REDEMPTION"


class EventStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class EventRegistrationStatus(str, Enum):
    REGISTERED = "REGISTERED"
    CHECKED_IN = "CHECKED_IN"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class ConsignmentStatus(str, Enum):
    RECEIVED = "RECEIVED"
    LISTED = "LISTED"
    SOLD = "SOLD"
    RETURNED_TO_CONSIGNOR = "RETURNED_TO_CONSIGNOR"
    PAID_OUT = "PAID_OUT"


# ---------------------------------------------------------------------------
# Entity TypedDicts — entities carrying the full common-field set
# (id + created_at + updated_at + version)
# ---------------------------------------------------------------------------
class Customer(TypedDict):
    id: str
    email: str
    full_name: str
    loyalty_tier: str
    loyalty_points_balance: int
    store_credit_cents: int
    lifetime_spend_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ComicSeries(TypedDict):
    id: str
    title: str
    publisher: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ComicIssue(TypedDict):
    id: str
    series_id: str
    issue_number: str
    cover_price_cents: int
    on_sale_date: str
    order_cutoff_date: str
    copies_ordered: int
    copies_reserved: int
    copies_allocated: int
    copies_available: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PullSubscription(TypedDict):
    id: str
    customer_id: str
    series_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Reservation(TypedDict):
    id: str
    customer_id: str
    issue_id: str
    subscription_id: Optional[str]
    requested_qty: int
    allocated_qty: int
    unit_price_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PreOrder(TypedDict):
    id: str
    customer_id: str
    issue_id: str
    quantity: int
    estimated_total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class BackIssue(TypedDict):
    id: str
    series_id: str
    issue_number: str
    condition: str
    grade_value: Optional[float]
    price_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class GradingSubmission(TypedDict):
    id: str
    customer_id: str
    description: str
    declared_value_cents: int
    grade_result: Optional[float]
    dispute_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Event(TypedDict):
    id: str
    name: str
    store_location: str
    starts_at: str
    ends_at: str
    capacity: int
    registered_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class EventRegistration(TypedDict):
    id: str
    customer_id: str
    event_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Consignment(TypedDict):
    id: str
    consignor_id: str
    description: str
    asking_price_cents: int
    commission_pct: float
    sale_price_cents: Optional[int]
    provisional_payout_cents: Optional[int]
    final_payout_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Append-only ledger event — carries ONLY id + created_at (no updated_at/version)
# ---------------------------------------------------------------------------
class CreditTransaction(TypedDict):
    id: str
    customer_id: str
    amount_cents: int
    reason: str
    balance_after_cents: int
    created_at: str
