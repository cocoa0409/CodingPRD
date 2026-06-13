"""Domain types: entity TypedDicts, status enums, role enum.

All entities in the Public Library Management API are mutable and carry the
common fields id, created_at, updated_at, version (PRD §2.4).
"""
from enum import Enum
from typing import TypedDict, Optional


# --- Role enum ---
class UserRole(str, Enum):
    PATRON = "Patron"
    LIBRARIAN = "Librarian"
    BRANCH_MANAGER = "BranchManager"


# --- Status enums ---
class PatronType(str, Enum):
    ADULT = "ADULT"
    JUVENILE = "JUVENILE"
    STAFF = "STAFF"


class CardStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"


class BorrowingStatus(str, Enum):
    CLEAR = "CLEAR"
    BLOCKED = "BLOCKED"


class TitleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    WITHDRAWN = "WITHDRAWN"


class CopyStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    ON_LOAN = "ON_LOAN"
    ON_HOLD_SHELF = "ON_HOLD_SHELF"
    LOST = "LOST"
    WITHDRAWN = "WITHDRAWN"


class LoanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    OVERDUE = "OVERDUE"
    RETURNED = "RETURNED"
    LOST = "LOST"


class HoldStatus(str, Enum):
    WAITING = "WAITING"
    READY = "READY"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class ReservationStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class ResourceKind(str, Enum):
    ROOM = "ROOM"
    COMPUTER = "COMPUTER"


class ResourceStatus(str, Enum):
    IN_SERVICE = "IN_SERVICE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class IllStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    SHIPPED = "SHIPPED"
    RECEIVED = "RECEIVED"
    RETURNED = "RETURNED"
    DENIED = "DENIED"


class EbookLoanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETURNED = "RETURNED"
    EXPIRED = "EXPIRED"


class FineType(str, Enum):
    OVERDUE = "OVERDUE"
    LOST = "LOST"
    ILL_FEE = "ILL_FEE"


class SettlementStatus(str, Enum):
    UNPAID = "UNPAID"
    PAID = "PAID"
    WAIVED = "WAIVED"


# --- Entity TypedDicts (all common_fields: true → id/created_at/updated_at/version) ---
class Branch(TypedDict):
    id: str
    name: str
    fine_free: bool
    daily_fine_cents: int
    max_fine_cents: int
    grace_days: int
    loan_period_days: int
    block_threshold_cents: int
    reservation_buffer_minutes: int
    created_at: str
    updated_at: str
    version: int


class Patron(TypedDict):
    id: str
    branch_id: str
    full_name: str
    patron_type: str
    card_status: str
    borrowing_status: str
    checkout_limit: int
    hold_limit: int
    active_loan_count: int
    active_hold_count: int
    total_owed_cents: int
    ready_pickup_count: int
    created_at: str
    updated_at: str
    version: int


class Title(TypedDict):
    id: str
    branch_id: str
    isbn: str
    title_text: str
    status: str
    default_replacement_cents: int
    available_copy_count: int
    total_copy_count: int
    waiting_hold_count: int
    created_at: str
    updated_at: str
    version: int


class Copy(TypedDict):
    id: str
    title_id: str
    branch_id: str
    barcode: str
    status: str
    acquired_on: str
    condition_factor: float
    created_at: str
    updated_at: str
    version: int


class Loan(TypedDict):
    id: str
    copy_id: str
    patron_id: str
    status: str
    checked_out_at: str
    due_date: str
    renewal_count: int
    returned_at: Optional[str]
    accrued_fine_cents: int
    created_at: str
    updated_at: str
    version: int


class Hold(TypedDict):
    id: str
    title_id: str
    patron_id: str
    status: str
    queue_position: int
    ready_copy_id: Optional[str]
    ready_at: Optional[str]
    pickup_deadline: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Reservation(TypedDict):
    id: str
    resource_id: str
    patron_id: str
    status: str
    start_at: str
    end_at: str
    checked_in_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BookableResource(TypedDict):
    id: str
    branch_id: str
    resource_kind: str
    label: str
    capacity: int
    status: str
    created_at: str
    updated_at: str
    version: int


class IllRequest(TypedDict):
    id: str
    patron_id: str
    branch_id: str
    isbn: str
    status: str
    lending_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class LicensePool(TypedDict):
    id: str
    title_id: str
    total_licenses: int
    loan_term_days: int
    loaned_licenses: int
    available_licenses: int
    created_at: str
    updated_at: str
    version: int


class EbookLoan(TypedDict):
    id: str
    pool_id: str
    patron_id: str
    status: str
    checked_out_at: str
    expires_at: str
    created_at: str
    updated_at: str
    version: int


class Fine(TypedDict):
    id: str
    patron_id: str
    loan_id: Optional[str]
    fine_type: str
    amount_cents: int
    settlement_status: str
    settled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
