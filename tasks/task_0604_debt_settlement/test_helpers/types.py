"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the PRD's resource definitions. Every primary resource carries
id, created_at, updated_at, and version per PRD §2.4.
"""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    NEGOTIATION_AGENT = "NegotiationAgent"
    CLIENT = "Client"


class ProgramPhase(str, Enum):
    ENROLLING = "ENROLLING"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    TERMINATED = "TERMINATED"


class AccountStanding(str, Enum):
    CURRENT = "CURRENT"
    DELINQUENT = "DELINQUENT"
    DEFAULTED = "DEFAULTED"


class DebtStatus(str, Enum):
    ENROLLED = "ENROLLED"
    IN_NEGOTIATION = "IN_NEGOTIATION"
    LAWSUIT = "LAWSUIT"
    SETTLED = "SETTLED"
    WITHDRAWN = "WITHDRAWN"


class DepositStatus(str, Enum):
    CLEARED = "CLEARED"
    MISSED = "MISSED"
    RETURNED = "RETURNED"


class OfferStatus(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class SettlementStatus(str, Enum):
    FUNDED = "FUNDED"
    COMPLETED = "COMPLETED"
    VOIDED = "VOIDED"


class FeeStatus(str, Enum):
    OUTSTANDING = "OUTSTANDING"
    PAID = "PAID"
    WAIVED = "WAIVED"


class LawsuitStatus(str, Enum):
    REFERRED = "REFERRED"
    RESOLVED_SETTLED = "RESOLVED_SETTLED"
    RESOLVED_DISMISSED = "RESOLVED_DISMISSED"


class TaxEventStatus(str, Enum):
    ISSUED = "ISSUED"
    VOIDED = "VOIDED"


class Program(TypedDict):
    id: str
    client_id: str
    program_phase: str
    account_standing: str
    target_settlement_pct: float
    monthly_deposit_amount: float
    deposit_day_of_month: int
    total_enrolled_balance: float
    fee_tier_pct: float
    missed_deposit_count: int
    estimated_total_savings: float
    realized_total_savings: float
    completion_eligible: bool
    created_at: str
    updated_at: str
    version: int


class Client(TypedDict):
    id: str
    full_name: str
    email: str
    state_code: str
    refunded_to_client_cents: int
    created_at: str
    updated_at: str
    version: int


class DedicatedAccount(TypedDict):
    id: str
    program_id: str
    balance: float
    lifetime_deposited: float
    lifetime_disbursed: float
    reserve_floor: float
    created_at: str
    updated_at: str
    version: int


class Debt(TypedDict):
    id: str
    program_id: str
    creditor_name: str
    account_number: str
    original_balance: float
    current_balance: float
    settled_amount: float
    forgiven_amount: float
    fee_rate_pct: float
    status: str
    settled_offer_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MonthlyDeposit(TypedDict):
    id: str
    program_id: str
    scheduled_for: str
    amount: float
    status: str
    created_at: str
    updated_at: str
    version: int


class SettlementOffer(TypedDict):
    id: str
    program_id: str
    debt_id: str
    offer_pct: float
    settlement_amount: float
    projected_fee: float
    due_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Settlement(TypedDict):
    id: str
    program_id: str
    offer_id: str
    debt_id: str
    funded_amount: float
    forgiven_amount: float
    status: str
    created_at: str
    updated_at: str
    version: int


class SettlementFee(TypedDict):
    id: str
    program_id: str
    settlement_id: str
    amount: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Lawsuit(TypedDict):
    id: str
    program_id: str
    debt_id: str
    court_reference: str
    filed_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class TaxEvent(TypedDict):
    id: str
    program_id: str
    source_settlement_id: str
    forgiven_amount: float
    tax_year: int
    reportable: bool
    status: str
    created_at: str
    updated_at: str
    version: int
