"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    MEMBER = "Member"
    CONCIERGE_AGENT = "ConciergeAgent"
    PLATFORM_ADMIN = "PlatformAdmin"


class MemberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class SavingsAccountStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class LinkedAccountStatus(str, Enum):
    LINKED = "LINKED"
    UNLINKED = "UNLINKED"


class RecurringChargeStatus(str, Enum):
    DETECTED = "DETECTED"
    CONFIRMED = "CONFIRMED"
    DISMISSED = "DISMISSED"


class SubscriptionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    CANCELLED = "CANCELLED"
    CANCEL_FAILED = "CANCEL_FAILED"


class NegotiationCaseStatus(str, Enum):
    OPEN = "OPEN"
    PROPOSED = "PROPOSED"
    COUNTERED = "COUNTERED"
    WON = "WON"
    LOST = "LOST"
    CANCELLED = "CANCELLED"


class RefundClaimStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    DISPUTED = "DISPUTED"
    REFUNDED = "REFUNDED"
    DENIED = "DENIED"


class LedgerTransferStatus(str, Enum):
    PENDING = "PENDING"
    TRANSFERRED = "TRANSFERRED"
    REVERSED = "REVERSED"


class Cadence(str, Enum):
    MONTHLY = "MONTHLY"
    ANNUAL = "ANNUAL"
    WEEKLY = "WEEKLY"


class ChargeCategory(str, Enum):
    STREAMING = "STREAMING"
    TELECOM = "TELECOM"
    INSURANCE = "INSURANCE"
    UTILITY = "UTILITY"
    SOFTWARE = "SOFTWARE"
    OTHER = "OTHER"


class AccountType(str, Enum):
    CHECKING = "CHECKING"
    CREDIT_CARD = "CREDIT_CARD"


class ClaimType(str, Enum):
    PRICE_DROP = "PRICE_DROP"
    DOUBLE_BILL = "DOUBLE_BILL"
    SERVICE_OUTAGE = "SERVICE_OUTAGE"


class LedgerSourceType(str, Enum):
    NEGOTIATION = "NEGOTIATION"
    REFUND = "REFUND"


# --- Entity TypedDicts ---
# common_fields: true -> id + created_at + updated_at + version

class Member(TypedDict):
    id: str
    email: str
    full_name: str
    success_fee_pct: float
    savings_account_id: Optional[str]
    status: str
    lifetime_gross_savings_cents: int
    lifetime_member_savings_cents: int
    created_at: str
    updated_at: str
    version: int


class SavingsAccount(TypedDict):
    id: str
    member_id: str
    nickname: str
    balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class LinkedAccount(TypedDict):
    id: str
    member_id: str
    institution_name: str
    account_type: str
    status: str
    detected_charge_count: int
    created_at: str
    updated_at: str
    version: int


class RecurringCharge(TypedDict):
    id: str
    linked_account_id: str
    merchant_name: str
    amount_cents: int
    cadence: str
    category: str
    first_seen_utc: str
    annualized_cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict):
    id: str
    member_id: str
    recurring_charge_id: str
    plan_name: str
    monthly_cost_cents: int
    is_free_trial: bool
    trial_end_utc: Optional[str]
    trial_reminder_lead_days: int
    reminder_due: bool
    status: str
    cancelled_utc: Optional[str]
    created_at: str
    updated_at: str
    version: int


class NegotiationCase(TypedDict):
    id: str
    member_id: str
    recurring_charge_id: str
    assigned_agent_id: Optional[str]
    baseline_annual_cost_cents: int
    current_offer_annual_cost_cents: Optional[int]
    agreed_annual_cost_cents: Optional[int]
    round_count: int
    gross_annual_savings_cents: int
    success_fee_cents: int
    member_net_savings_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RefundClaim(TypedDict):
    id: str
    member_id: str
    recurring_charge_id: str
    claim_type: str
    observed_old_amount_cents: int
    observed_new_amount_cents: int
    claimed_refund_cents: int
    approved_refund_cents: Optional[int]
    success_fee_cents: int
    member_net_savings_cents: int
    dispute_round: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false -> ONLY id + created_at (no updated_at, no version)

class ConciergeAgentProfile(TypedDict):
    id: str
    display_name: str
    max_open_cases: int
    open_case_count: int
    created_at: str


class SavingsLedgerEntry(TypedDict):
    id: str
    member_id: str
    source_type: str
    negotiation_case_id: Optional[str]
    refund_claim_id: Optional[str]
    gross_savings_cents: int
    success_fee_cents: int
    member_net_cents: int
    transfer_status: str
    transferred_utc: Optional[str]
    created_at: str
