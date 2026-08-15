"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    BROKER_ADMIN = "BrokerAdmin"
    OFFICE_MANAGER = "OfficeManager"
    TRANSACTION_COORDINATOR = "TransactionCoordinator"
    AGENT = "Agent"
    AUDITOR = "Auditor"


class AgentStatus(str, Enum):
    ONBOARDING = "ONBOARDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class EnrollmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    ENDED = "ENDED"
    CANCELLED = "CANCELLED"


class AnniversaryStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class DealStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_CLOSING = "PENDING_CLOSING"
    CLOSED = "CLOSED"
    SETTLED = "SETTLED"
    DISBURSED = "DISBURSED"
    FELL_THROUGH = "FELL_THROUGH"
    VOIDED = "VOIDED"


class SettlementStatus(str, Enum):
    POSTED = "POSTED"
    REVERSED = "REVERSED"


class LegStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    AUTHORIZED = "AUTHORIZED"
    RELEASED = "RELEASED"
    VOIDED = "VOIDED"


class LegPayeeType(str, Enum):
    AGENT = "AGENT"
    MENTOR = "MENTOR"
    TEAM_LEAD = "TEAM_LEAD"
    REFERRAL = "REFERRAL"
    CO_BROKE = "CO_BROKE"
    ROYALTY = "ROYALTY"
    COMPANY = "COMPANY"


class LedgerEntryType(str, Enum):
    FEE_SHORTFALL_ACCRUAL = "FEE_SHORTFALL_ACCRUAL"
    FEE_SHORTFALL_REVERSAL = "FEE_SHORTFALL_REVERSAL"
    DEBIT_RECOVERY = "DEBIT_RECOVERY"
    DEBIT_RECOVERY_REVERSAL = "DEBIT_RECOVERY_REVERSAL"
    MANUAL_DEBIT = "MANUAL_DEBIT"
    DEBIT_WRITE_OFF = "DEBIT_WRITE_OFF"


class TaxFormStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    VOIDED = "VOIDED"


class TrustKind(str, Enum):
    RECEIPT = "RECEIPT"
    RECEIPT_REVERSAL = "RECEIPT_REVERSAL"
    RELEASE = "RELEASE"


# common_fields: true — id + created_at + updated_at + version
class Agent(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    license_number: str
    joined_at: str
    mentor_agent_id: Optional[str]
    team_lead_agent_id: Optional[str]
    team_override_pct: float
    status: str
    debit_balance_cents: int
    settled_deal_count: int
    created_at: str
    updated_at: str
    version: int


class CommissionPlan(TypedDict, total=False):
    id: str
    name: str
    royalty_pct: float
    royalty_cap_cents: int
    eo_fee_cents: int
    transaction_fee_cents: int
    mentor_split_pct: float
    mentor_deal_count: int
    tiers: list
    status: str
    created_at: str
    updated_at: str
    version: int


class PlanEnrollment(TypedDict, total=False):
    id: str
    agent_id: str
    plan_id: str
    plan_version: int
    effective_from: str
    effective_to: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AnniversaryPeriod(TypedDict, total=False):
    id: str
    agent_id: str
    window_index: int
    window_start: str
    window_end: str
    company_dollar_accrued_cents: int
    royalty_accrued_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Deal(TypedDict, total=False):
    id: str
    agent_id: str
    address: str
    gross_commission_cents: int
    closing_date: str
    cobroke_payout_cents: int
    cobroke_payee_name: Optional[str]
    referral_pct: float
    referral_agent_id: Optional[str]
    trust_received_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Settlement(TypedDict, total=False):
    id: str
    deal_id: str
    agent_id: str
    enrollment_id: str
    plan_version_used: int
    window_start: str
    gross_commission_cents: int
    cobroke_payout_cents: int
    net_office_commission_cents: int
    referral_fee_cents: int
    adjusted_commission_cents: int
    royalty_cents: int
    royalty_capped: bool
    after_royalty_cents: int
    tier_index_applied: int
    company_dollar_cents: int
    cap_clipped: bool
    agent_gross_cents: int
    mentor_split_cents: int
    mentor_applied: bool
    mentor_agent_id: Optional[str]
    team_override_cents: int
    team_lead_agent_id: Optional[str]
    eo_fee_cents: int
    transaction_fee_cents: int
    fee_shortfall_cents: int
    debit_recovery_cents: int
    agent_net_cents: int
    status: str
    posted_by_user_id: str
    posted_at: str
    reversed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DisbursementLeg(TypedDict, total=False):
    id: str
    settlement_id: str
    payee_type: str
    payee_agent_id: Optional[str]
    payee_name: Optional[str]
    amount_cents: int
    status: str
    authorized_by_user_id: Optional[str]
    authorized_at: Optional[str]
    released_by_user_id: Optional[str]
    released_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only, NO updated_at, NO version
class LedgerEntry(TypedDict, total=False):
    id: str
    created_at: str
    agent_id: str
    deal_id: Optional[str]
    settlement_id: Optional[str]
    entry_type: str
    amount_cents: int
    resulting_balance_cents: int
    reason: Optional[str]


class TaxForm1099(TypedDict, total=False):
    id: str
    agent_id: str
    tax_year: int
    gross_paid_cents: int
    accrual_gross_cents: int
    filing_required: bool
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only
class TrustTransaction(TypedDict, total=False):
    id: str
    created_at: str
    deal_id: str
    kind: str
    amount_cents: int
    disbursement_leg_id: Optional[str]
    trust_balance_after_cents: int
