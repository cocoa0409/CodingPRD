"""Domain types: entity TypedDicts, status enums, role enum (Debt Collection Agency API)."""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Role enum
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    CREDITOR = "Creditor"
    COLLECTOR = "Collector"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    BUREAU_OPERATOR = "BureauOperator"
    SYSTEM = "System"


# ---------------------------------------------------------------------------
# Status / enum dimensions
# ---------------------------------------------------------------------------
class CommissionBasis(str, Enum):
    GROSS_OF_FEES = "GROSS_OF_FEES"
    NET_OF_FEES = "NET_OF_FEES"


class Contactability(str, Enum):
    UNKNOWN = "UNKNOWN"
    LOCATED = "LOCATED"
    UNLOCATABLE = "UNLOCATABLE"


class WorkStatus(str, Enum):
    PLACED = "PLACED"
    VALIDATION_SENT = "VALIDATION_SENT"
    WORKING = "WORKING"
    RECALLED = "RECALLED"
    CLOSED_PAID = "CLOSED_PAID"
    CLOSED_UNCOLLECTIBLE = "CLOSED_UNCOLLECTIBLE"


class ContactStatus(str, Enum):
    PRE_VALIDATION = "PRE_VALIDATION"
    CONTACTABLE = "CONTACTABLE"
    VALIDATION_HELD = "VALIDATION_HELD"
    CEASED = "CEASED"


class SolAnchorBasis(str, Enum):
    CHARGE_OFF = "CHARGE_OFF"
    LAST_PAYMENT = "LAST_PAYMENT"


class CommunicationChannel(str, Enum):
    PHONE = "PHONE"
    LETTER = "LETTER"
    EMAIL = "EMAIL"


class CommunicationOutcome(str, Enum):
    LOGGED = "LOGGED"
    CONVERSATION = "CONVERSATION"
    CANCELLED = "CANCELLED"


class DisputeType(str, Enum):
    VALIDATION = "VALIDATION"
    ACCURACY = "ACCURACY"


class DisputeResolution(str, Enum):
    VERIFIED = "VERIFIED"
    DELETED = "DELETED"


class DisputeStatus(str, Enum):
    OPEN = "OPEN"
    INVESTIGATING = "INVESTIGATING"
    RESOLVED = "RESOLVED"
    REOPENED = "REOPENED"


class ArrangementType(str, Enum):
    PLAN = "PLAN"
    SETTLEMENT = "SETTLEMENT"


class ArrangementStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACCEPTED = "ACCEPTED"
    COUNTERED = "COUNTERED"
    REJECTED = "REJECTED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class PaymentStatus(str, Enum):
    POSTED = "POSTED"
    REVERSED = "REVERSED"
    VOIDED = "VOIDED"


class SkipTraceResult(str, Enum):
    LOCATED = "LOCATED"
    NOT_FOUND = "NOT_FOUND"


class Bureau(str, Enum):
    EQUIFAX = "EQUIFAX"
    EXPERIAN = "EXPERIAN"
    TRANSUNION = "TRANSUNION"


class BureauFurnishingStatus(str, Enum):
    REPORTED = "REPORTED"
    UPDATED = "UPDATED"
    DELETED = "DELETED"


class BureauDisputeOutcome(str, Enum):
    VERIFIED = "VERIFIED"
    CORRECTED = "CORRECTED"
    DELETED = "DELETED"


class BureauDisputeStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    REOPENED = "REOPENED"


class PayoffAsOf(str, Enum):
    QUOTE_DATE = "QUOTE_DATE"
    GOOD_THROUGH = "GOOD_THROUGH"


# ---------------------------------------------------------------------------
# Entity TypedDicts — all entities carry common fields
# (id + created_at + updated_at + version) per PRD §2.5.
# ---------------------------------------------------------------------------
class Creditor(TypedDict):
    id: str
    name: str
    commission_basis: str
    commission_rate_bps: int
    expense_recovery_cents: int
    created_at: str
    updated_at: str
    version: int


class Consumer(TypedDict):
    id: str
    full_name: str
    timezone_offset_minutes: int
    phone: Optional[str]
    address: Optional[str]
    contactability: str
    created_at: str
    updated_at: str
    version: int


class Account(TypedDict):
    id: str
    creditor_id: str
    consumer_id: str
    original_principal_cents: int
    balance_cents: int
    amount_collected_cents: int
    amount_settled_forgiven_cents: int
    charge_off_date: str
    last_payment_date: Optional[str]
    sol_years: int
    sol_anchor_basis: str
    placement_date: str
    validation_notice_sent_at: Optional[str]
    validation_deadline: Optional[str]
    work_status: str
    contact_status: str
    attempts_in_window_count: int
    last_conversation_at: Optional[str]
    commission_earned_cents: int
    time_barred: bool
    created_at: str
    updated_at: str
    version: int


class CommunicationAttempt(TypedDict):
    id: str
    account_id: str
    channel: str
    attempted_at: str
    outcome: str
    counts_toward_cadence: bool
    created_at: str
    updated_at: str
    version: int


class Dispute(TypedDict):
    id: str
    account_id: str
    dispute_type: str
    raised_at: str
    within_validation_window: bool
    resolution: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PaymentArrangement(TypedDict):
    id: str
    account_id: str
    arrangement_type: str
    offer_pct_bps: Optional[int]
    settlement_amount_cents: Optional[int]
    installment_count: int
    good_through: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict):
    id: str
    account_id: str
    arrangement_id: Optional[str]
    amount_cents: int
    posted_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SkipTrace(TypedDict):
    id: str
    consumer_id: str
    result: str
    new_phone: Optional[str]
    new_address: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BureauFurnishing(TypedDict):
    id: str
    account_id: str
    bureau: str
    furnished_balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class BureauDispute(TypedDict):
    id: str
    furnishing_id: str
    opened_at: str
    investigation_deadline: str
    outcome: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
