"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.5, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List, Any


class UserRole(str, Enum):
    DESK_ADMINISTRATOR = "DeskAdministrator"
    VENDOR_FEED = "VendorFeed"
    EVENT_ANALYST = "EventAnalyst"
    OPERATIONS_MANAGER = "OperationsManager"
    ACCOUNT_HOLDER = "AccountHolder"
    CLAIMS_EXAMINER = "ClaimsExaminer"
    CUSTODIAN_FEED = "CustodianFeed"


class SecurityStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"
    CLOSED = "CLOSED"


class PositionLotStatus(str, Enum):
    OPEN = "OPEN"
    FULLY_SURRENDERED = "FULLY_SURRENDERED"


class EventSourceType(str, Enum):
    CUSTODIAN = "CUSTODIAN"
    VENDOR = "VENDOR"
    DEPOSITORY = "DEPOSITORY"


class SourceNotificationStatus(str, Enum):
    RECEIVED = "RECEIVED"
    MATCHED = "MATCHED"
    REJECTED = "REJECTED"


class EventType(str, Enum):
    SPLIT = "SPLIT"
    MERGER = "MERGER"
    SPIN_OFF = "SPIN_OFF"
    CASH_DIVIDEND = "CASH_DIVIDEND"
    STOCK_DIVIDEND = "STOCK_DIVIDEND"
    RIGHTS_OFFERING = "RIGHTS_OFFERING"


class EventStatus(str, Enum):
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    AMENDED = "AMENDED"
    BOOKED = "BOOKED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class EntitlementStatus(str, Enum):
    PROJECTED = "PROJECTED"
    FIRM = "FIRM"
    SETTLED = "SETTLED"
    MISSED = "MISSED"
    COMPENSATED = "COMPENSATED"
    SUPERSEDED = "SUPERSEDED"


class CalculationBasis(str, Enum):
    TRADE_DATE_BASIS = "TRADE_DATE_BASIS"
    SETTLED_BASIS = "SETTLED_BASIS"


class FractionalPolicy(str, Enum):
    ROUND_HALF_UP = "ROUND_HALF_UP"
    ROUND_DOWN = "ROUND_DOWN"
    ROUND_UP = "ROUND_UP"


class ElectionStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    WITHDRAWN = "WITHDRAWN"
    SUPERSEDED = "SUPERSEDED"
    APPLIED = "APPLIED"
    LAPSED = "LAPSED"
    VOID = "VOID"


class ElectionOption(str, Enum):
    CASH = "CASH"
    STOCK = "STOCK"
    EXERCISE = "EXERCISE"


class BookingStatus(str, Enum):
    POSTED = "POSTED"
    REVERSED = "REVERSED"


class BookingLineKind(str, Enum):
    LOT_MUTATION = "LOT_MUTATION"
    LOT_CREATION = "LOT_CREATION"
    CASH_CREDIT = "CASH_CREDIT"
    CASH_DEBIT = "CASH_DEBIT"
    CASH_IN_LIEU = "CASH_IN_LIEU"


class ClaimReason(str, Enum):
    MISSED_ENTITLEMENT = "MISSED_ENTITLEMENT"
    INCORRECT_AMOUNT = "INCORRECT_AMOUNT"
    FRACTIONAL_DISPUTE = "FRACTIONAL_DISPUTE"


class ClaimReviewStatus(str, Enum):
    FILED = "FILED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class ClaimPaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PAID = "PAID"


class ClaimCompensationBasis(str, Enum):
    EVENT_TERMS = "EVENT_TERMS"
    MARKET_VALUE = "MARKET_VALUE"


class CustodianStatementStatus(str, Enum):
    RECEIVED = "RECEIVED"
    RECONCILED = "RECONCILED"


class ReconBreakType(str, Enum):
    POSITION_MISMATCH = "POSITION_MISMATCH"
    CASH_MISMATCH = "CASH_MISMATCH"
    MISSED_ENTITLEMENT = "MISSED_ENTITLEMENT"


class ReconBreakStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    WRITTEN_OFF = "WRITTEN_OFF"


class ReconBreakResolution(str, Enum):
    AUTO_BOOKING = "AUTO_BOOKING"
    MANUAL = "MANUAL"
    WRITTEN_OFF = "WRITTEN_OFF"


# --- common_fields: true entities (id + created_at + updated_at + version) ---

class Security(TypedDict, total=False):
    id: str
    ticker: str
    cusip: str
    name: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Account(TypedDict, total=False):
    id: str
    account_number: str
    holder_name: str
    opening_cash_cents: int
    cash_balance_cents: int
    total_cost_basis_cents: int
    pending_entitlement_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PositionLot(TypedDict, total=False):
    id: str
    account_id: str
    security_id: str
    origin_booking_id: Optional[str]
    quantity: float
    acquisition_date: str
    cost_basis_total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class EventSource(TypedDict, total=False):
    id: str
    name: str
    source_type: str
    reliability_weight: int
    created_at: str
    updated_at: str
    version: int


class CorporateActionEvent(TypedDict, total=False):
    id: str
    security_id: str
    event_type: str
    election_required: bool
    terms: dict
    record_date: str
    payable_date: str
    election_deadline: Optional[str]
    compensation_pool_cents: int
    compensation_pool_remaining_cents: int
    claim_compensation_basis: str
    scrubbed_by_user_id: str
    confirmed_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Entitlement(TypedDict, total=False):
    id: str
    event_id: str
    account_id: str
    supersedes_entitlement_id: Optional[str]
    calculation_basis: str
    record_position_quantity: float
    entitled_shares: int
    fractional_shares: float
    cash_in_lieu_cents: int
    cash_amount_cents: int
    booked_whole_shares: Optional[int]
    booked_cash_in_lieu_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Election(TypedDict, total=False):
    id: str
    event_id: str
    account_id: str
    option_code: str
    quantity: Optional[int]
    election_seq: int
    submitted_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Booking(TypedDict, total=False):
    id: str
    event_id: str
    booked_by_user_id: str
    booked_at: str
    total_whole_shares_credited: int
    total_cash_credited_cents: int
    total_cash_in_lieu_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict, total=False):
    id: str
    event_id: str
    entitlement_id: str
    account_id: str
    reason: str
    claimed_amount_cents: int
    market_price_cents: Optional[int]
    compensation_cents: Optional[int]
    filed_by_user_id: str
    reviewed_by_user_id: Optional[str]
    review_status: str
    payment_status: str
    created_at: str
    updated_at: str
    version: int


class CustodianStatement(TypedDict, total=False):
    id: str
    source_id: str
    coverage_start_date: str
    coverage_end_date: str
    lines: List[Any]
    status: str
    created_at: str
    updated_at: str
    version: int


class ReconBreak(TypedDict, total=False):
    id: str
    statement_id: str
    event_id: Optional[str]
    account_id: str
    security_id: str
    break_type: str
    expected_quantity: float
    reported_quantity: float
    expected_cash_cents: Optional[int]
    reported_cash_cents: Optional[int]
    auto_claim_id: Optional[str]
    resolution: Optional[str]
    resolution_note: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# --- common_fields: false entities (id + created_at ONLY; no updated_at/version) ---

class SourceNotification(TypedDict, total=False):
    id: str
    source_id: str
    security_id: str
    event_type: str
    record_date: str
    announced_terms: dict
    status: str
    created_at: str


class EventAmendment(TypedDict, total=False):
    id: str
    event_id: str
    amended_terms: dict
    reason: str
    amendment_seq: int
    applied_by_user_id: str
    created_at: str


class BookingLine(TypedDict, total=False):
    id: str
    booking_id: str
    entitlement_id: str
    position_lot_id: Optional[str]
    line_kind: str
    quantity_delta: float
    basis_delta_cents: int
    cash_delta_cents: int
    prior_quantity: float
    prior_basis_cents: int
    created_at: str
