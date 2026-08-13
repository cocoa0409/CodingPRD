"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Optional, TypedDict


# --- Status enums -----------------------------------------------------------

class CardAccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RESTRICTED = "RESTRICTED"


class CardTransactionStatus(str, Enum):
    POSTED = "POSTED"
    DISPUTED = "DISPUTED"
    CHARGED_BACK = "CHARGED_BACK"
    RE_PRESENTED = "RE_PRESENTED"
    SETTLED = "SETTLED"


class DisputeCaseStatus(str, Enum):
    RECEIVED = "RECEIVED"
    CLASSIFIED = "CLASSIFIED"
    CHARGEBACK_FILED = "CHARGEBACK_FILED"
    REPRESENTMENT_REVIEW = "REPRESENTMENT_REVIEW"
    REVERSAL_PENDING = "REVERSAL_PENDING"
    RESOLVED_CARDHOLDER_FAVOR = "RESOLVED_CARDHOLDER_FAVOR"
    RESOLVED_MERCHANT_FAVOR = "RESOLVED_MERCHANT_FAVOR"
    WITHDRAWN = "WITHDRAWN"


class ProvisionalCreditStatus(str, Enum):
    GRANTED = "GRANTED"
    REVERSED = "REVERSED"
    REINSTATED = "REINSTATED"
    FINALIZED = "FINALIZED"


class ChargebackStatus(str, Enum):
    FILED = "FILED"
    REPRESENTED = "REPRESENTED"
    SECOND_PRESENTED = "SECOND_PRESENTED"
    CLOSED_WON = "CLOSED_WON"
    CLOSED_LOST = "CLOSED_LOST"
    CANCELLED = "CANCELLED"
    WITHDRAWN = "WITHDRAWN"


class RepresentmentStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class NotificationType(str, Enum):
    PROVISIONAL_CREDIT_ADVICE = "PROVISIONAL_CREDIT_ADVICE"
    REVERSAL_NOTICE = "REVERSAL_NOTICE"
    RESOLUTION_LETTER = "RESOLUTION_LETTER"


class LossRecoveryType(str, Enum):
    LOSS_RECOGNIZED = "LOSS_RECOGNIZED"
    RECOVERY_RECEIVED = "RECOVERY_RECEIVED"


class LossRecoverySource(str, Enum):
    AUTO = "AUTO"
    MANUAL = "MANUAL"


class TransactionType(str, Enum):
    POS_PIN = "POS_PIN"
    POS_SIGNATURE = "POS_SIGNATURE"
    ATM_WITHDRAWAL = "ATM_WITHDRAWAL"
    ECOMMERCE = "ECOMMERCE"
    RECURRING = "RECURRING"


class Network(str, Enum):
    VISA = "VISA"
    MASTERCARD = "MASTERCARD"


class ErrorType(str, Enum):
    UNAUTHORIZED = "UNAUTHORIZED"
    INCORRECT_AMOUNT = "INCORRECT_AMOUNT"
    DUPLICATE_CHARGE = "DUPLICATE_CHARGE"
    SERVICE_NOT_RECEIVED = "SERVICE_NOT_RECEIVED"
    CANCELLED_RECURRING = "CANCELLED_RECURRING"


class ReasonCode(str, Enum):
    V10_4 = "V10_4"
    V10_5 = "V10_5"
    V13_1 = "V13_1"
    V13_3 = "V13_3"
    M4837 = "M4837"
    M4870 = "M4870"
    M4853 = "M4853"
    M4855 = "M4855"


class EscalationStage(str, Enum):
    PRE_COMPLIANCE = "PRE_COMPLIANCE"
    ARBITRATION = "ARBITRATION"


class StageEntered(str, Enum):
    NONE = "NONE"
    PRE_COMPLIANCE = "PRE_COMPLIANCE"
    ARBITRATION = "ARBITRATION"


class ChargebackOutcome(str, Enum):
    WON = "WON"
    LOST = "LOST"
    WITHDRAWN = "WITHDRAWN"


class ResolveOutcome(str, Enum):
    ERROR_CONFIRMED = "ERROR_CONFIRMED"
    NO_ERROR = "NO_ERROR"


class ReviewDecision(str, Enum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"


class UserRole(str, Enum):
    CARDHOLDER = "Cardholder"
    INTAKE_AGENT = "IntakeAgent"
    DISPUTE_INVESTIGATOR = "DisputeInvestigator"
    CHARGEBACK_ANALYST = "ChargebackAnalyst"
    FINANCE_OFFICER = "FinanceOfficer"
    BANK_ADMIN = "BankAdmin"


# --- Entity TypedDicts ------------------------------------------------------
# CardAccount, CardTransaction, DisputeCase, ProvisionalCredit, Chargeback,
# Representment carry id + created_at + updated_at + version.
# Notification and LossRecovery are immutable: only id + created_at.

class CardAccount(TypedDict, total=False):
    id: str
    cardholder_name: str
    opened_at: str
    status: str
    balance_cents: int
    provisional_outstanding_cents: int
    created_at: str
    updated_at: str
    version: int


class CardTransaction(TypedDict, total=False):
    id: str
    card_account_id: str
    merchant_name: str
    amount_cents: int
    transaction_type: str
    network: str
    posted_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DisputeCase(TypedDict, total=False):
    id: str
    card_transaction_id: str
    card_account_id: str
    intake_agent_id: Optional[str]
    error_type: str
    claim_amount_cents: int
    claimed_report_delay_days: int
    received_at: str
    is_fraud_claim: bool
    verified_report_delay_days: int
    provisional_holdback_cents: int
    provisional_credit_due_at: str
    investigation_window_days: int
    investigation_deadline_at: str
    final_liability_cents: int
    cardholder_keeps_cents: int
    outstanding_loss_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ProvisionalCredit(TypedDict, total=False):
    id: str
    dispute_case_id: str
    amount_cents: int
    final_amount_cents: Optional[int]
    granted_at: str
    granted_late: bool
    reversed_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Chargeback(TypedDict, total=False):
    id: str
    dispute_case_id: str
    card_transaction_id: str
    reason_code: str
    amount_cents: int
    network: str
    filed_at: str
    network_filing_deadline_at: str
    response_window_end_at: str
    fees_total_cents: int
    stage_entered: str
    outcome: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Representment(TypedDict, total=False):
    id: str
    chargeback_id: str
    merchant_ref: str
    evidence_documents: list
    received_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


# Immutable letter: id + created_at only — NO updated_at, NO version.
class Notification(TypedDict, total=False):
    id: str
    dispute_case_id: str
    type: str
    sent_at: str
    detail: str
    created_at: str


# Immutable ledger entry: id + created_at only — NO updated_at, NO version.
class LossRecovery(TypedDict, total=False):
    id: str
    dispute_case_id: str
    type: str
    amount_cents: int
    source: str
    memo: Optional[str]
    created_at: str
