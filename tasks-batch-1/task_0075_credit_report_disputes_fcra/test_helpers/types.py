"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Roles ---
class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    CONSUMER = "Consumer"
    FURNISHER = "Furnisher"
    CREDIT_BUREAU = "CreditBureau"
    REGULATOR = "Regulator"


# --- Status / enum domains ---
class ConsumerStatus(str, Enum):
    ACTIVE = "ACTIVE"


class FurnisherType(str, Enum):
    BANK = "BANK"
    CARD_ISSUER = "CARD_ISSUER"
    COLLECTION_AGENCY = "COLLECTION_AGENCY"
    LENDER = "LENDER"


class FurnisherStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class BureauCode(str, Enum):
    EQUIFAX = "EQUIFAX"
    EXPERIAN = "EXPERIAN"
    TRANSUNION = "TRANSUNION"


class ProtectionState(str, Enum):
    OPEN = "OPEN"
    LOCKED = "LOCKED"
    FROZEN = "FROZEN"


class AccountType(str, Enum):
    REVOLVING = "REVOLVING"
    INSTALLMENT = "INSTALLMENT"
    COLLECTION = "COLLECTION"


class TradelineStatus(str, Enum):
    REPORTING = "REPORTING"
    DISPUTED = "DISPUTED"
    CORRECTED = "CORRECTED"
    VERIFIED = "VERIFIED"
    DELETED = "DELETED"


class DisputeReason(str, Enum):
    NOT_MINE = "NOT_MINE"
    INACCURATE_BALANCE = "INACCURATE_BALANCE"
    ILLEGAL_REAGE = "ILLEGAL_REAGE"
    PAID_IN_FULL = "PAID_IN_FULL"
    IDENTITY_THEFT = "IDENTITY_THEFT"


class ClockMode(str, Enum):
    CALENDAR = "CALENDAR"
    EXPEDITED = "EXPEDITED"


class DisputeStatus(str, Enum):
    FILED = "FILED"
    INVESTIGATING = "INVESTIGATING"
    REVERIFYING = "REVERIFYING"
    REOPENED = "REOPENED"
    RESOLVED_DELETE = "RESOLVED_DELETE"
    RESOLVED_CORRECT = "RESOLVED_CORRECT"
    RESOLVED_VERIFY = "RESOLVED_VERIFY"
    AUTO_DELETED = "AUTO_DELETED"


class DisputeOutcomeReason(str, Enum):
    FURNISHER_DELETED = "FURNISHER_DELETED"
    FURNISHER_CORRECTED = "FURNISHER_CORRECTED"
    FURNISHER_VERIFIED = "FURNISHER_VERIFIED"
    DEADLINE_BREACH = "DEADLINE_BREACH"


class ReverificationResponseType(str, Enum):
    DELETE = "DELETE"
    MODIFY = "MODIFY"
    VERIFY = "VERIFY"


class ReverificationStatus(str, Enum):
    PENDING = "PENDING"
    RESPONDED = "RESPONDED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class FreezeType(str, Enum):
    LOCK = "LOCK"
    FREEZE = "FREEZE"


class SecurityFreezeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LIFTED = "LIFTED"


class ComplaintAgency(str, Enum):
    CFPB = "CFPB"
    STATE_AG = "STATE_AG"


class ComplaintStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    UPHELD = "UPHELD"
    DISMISSED = "DISMISSED"


class NotificationSubjectType(str, Enum):
    DISPUTE = "DISPUTE"
    SECURITY_FREEZE = "SECURITY_FREEZE"
    REGULATORY_COMPLAINT = "REGULATORY_COMPLAINT"
    TRADELINE = "TRADELINE"


class NotificationEventCode(str, Enum):
    DISPUTE_FILED = "DISPUTE_FILED"
    DISPUTE_RESOLVED = "DISPUTE_RESOLVED"
    DISPUTE_AUTO_DELETED = "DISPUTE_AUTO_DELETED"
    TRADELINE_CORRECTED = "TRADELINE_CORRECTED"
    TRADELINE_DELETED = "TRADELINE_DELETED"
    FREEZE_PLACED = "FREEZE_PLACED"
    FREEZE_LIFTED = "FREEZE_LIFTED"
    COMPLAINT_SUBMITTED = "COMPLAINT_SUBMITTED"
    COMPLAINT_ADJUDICATED = "COMPLAINT_ADJUDICATED"


# --- Entity TypedDicts ---
# common_fields: true -> id + created_at + updated_at + version
class Consumer(TypedDict):
    id: str
    email: str
    full_name: str
    ssn_last4: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Furnisher(TypedDict):
    id: str
    name: str
    furnisher_type: str
    status: str
    open_reverification_count: int
    created_at: str
    updated_at: str
    version: int


class CreditFile(TypedDict):
    id: str
    consumer_id: str
    bureau_code: str
    protection_state: str
    open_dispute_count: int
    tradeline_count: int
    created_at: str
    updated_at: str
    version: int


class Tradeline(TypedDict):
    id: str
    credit_file_id: str
    furnisher_id: str
    account_type: str
    balance_cents: int
    date_of_first_delinquency: str
    reported_delinquency_date: str
    status: str
    reage_violation: bool
    purge_due_at: str
    created_at: str
    updated_at: str
    version: int


class Dispute(TypedDict):
    id: str
    credit_file_id: str
    tradeline_id: str
    consumer_id: str
    dispute_reason: str
    clock_mode: str
    filed_at: str
    deadline_at: str
    priority_score: int
    reopen_count: int
    status: str
    outcome_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReverificationRequest(TypedDict):
    id: str
    dispute_id: str
    furnisher_id: str
    response_type: Optional[str]
    corrected_balance_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class SecurityFreeze(TypedDict):
    id: str
    credit_file_id: str
    freeze_type: str
    effective_at: str
    expires_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class RegulatoryComplaint(TypedDict):
    id: str
    dispute_id: str
    consumer_id: str
    agency: str
    narrative: str
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false -> append-only, id + created_at ONLY (no updated_at / version)
class Notification(TypedDict):
    id: str
    credit_file_id: str
    subject_type: str
    subject_id: str
    event_code: str
    dispatched_at: str
    created_at: str


class ReageEvent(TypedDict):
    id: str
    tradeline_id: str
    prior_delinquency_date: str
    new_delinquency_date: str
    was_violation: bool
    source_dispute_id: Optional[str]
    created_at: str
