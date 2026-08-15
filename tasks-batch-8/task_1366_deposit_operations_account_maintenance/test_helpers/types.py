"""Domain types: entity TypedDicts, status enums, role enum.

Field names follow the PRD exactly. DepositAccount, AuthorizedSigner,
AccountDocument, TitleChangeRequest, DeceasedCase, GarnishmentOrder,
StatementCycle, and ProductConversion carry the standard system-managed set
(id, created_at, updated_at, version). AccountTransaction is the append-only
event log: it carries only id and created_at from the common set — a posted
transaction never changes state, so updated_at and version are absent.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    OPS_OFFICER = "OpsOfficer"
    OPS_MANAGER = "OpsManager"
    SYSTEM = "System"
    AUDITOR = "Auditor"


class OwnershipType(str, Enum):
    INDIVIDUAL = "INDIVIDUAL"
    JOINT = "JOINT"
    POD = "POD"
    TRUST = "TRUST"
    BUSINESS = "BUSINESS"


class ProductCode(str, Enum):
    BASIC_CHECKING = "BASIC_CHECKING"
    PREMIUM_CHECKING = "PREMIUM_CHECKING"
    SAVINGS = "SAVINGS"
    MONEY_MARKET = "MONEY_MARKET"


class LifecycleStatus(str, Enum):
    OPEN = "OPEN"
    DORMANT = "DORMANT"
    ESCHEAT_PENDING = "ESCHEAT_PENDING"
    CLOSED = "CLOSED"


class RestrictionStatus(str, Enum):
    NONE = "NONE"
    LEGAL_HOLD = "LEGAL_HOLD"
    DECEASED_HOLD = "DECEASED_HOLD"


class StatementSuppression(str, Enum):
    NONE = "NONE"
    DORMANT = "DORMANT"
    DECEASED = "DECEASED"
    CLOSED = "CLOSED"


class ClosurePayoutDestination(str, Enum):
    OWNER = "OWNER"
    ESTATE = "ESTATE"
    STATE_ESCHEAT = "STATE_ESCHEAT"


class TxnType(str, Enum):
    DEPOSIT = "DEPOSIT"
    WITHDRAWAL = "WITHDRAWAL"
    FEDERAL_BENEFIT_DEPOSIT = "FEDERAL_BENEFIT_DEPOSIT"
    INACTIVITY_FEE = "INACTIVITY_FEE"
    INTEREST_CREDIT = "INTEREST_CREDIT"
    LEGAL_REMITTANCE = "LEGAL_REMITTANCE"
    CLOSURE_PAYOUT = "CLOSURE_PAYOUT"
    ESTATE_RELEASE = "ESTATE_RELEASE"


CREDIT_TXN_TYPES = [
    TxnType.DEPOSIT.value,
    TxnType.FEDERAL_BENEFIT_DEPOSIT.value,
    TxnType.INTEREST_CREDIT.value,
]
DEBIT_TXN_TYPES = [
    TxnType.WITHDRAWAL.value,
    TxnType.INACTIVITY_FEE.value,
    TxnType.LEGAL_REMITTANCE.value,
    TxnType.CLOSURE_PAYOUT.value,
    TxnType.ESTATE_RELEASE.value,
]


class SignerRole(str, Enum):
    OWNER = "OWNER"
    AUTHORIZED_SIGNER = "AUTHORIZED_SIGNER"
    POWER_OF_ATTORNEY = "POWER_OF_ATTORNEY"
    TRUSTEE = "TRUSTEE"
    BUSINESS_OFFICER = "BUSINESS_OFFICER"


class SignerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REMOVED = "REMOVED"


class RemovedReason(str, Enum):
    STAFF_REQUEST = "STAFF_REQUEST"
    DECEASED_CASCADE = "DECEASED_CASCADE"
    ACCOUNT_CLOSED = "ACCOUNT_CLOSED"


class DocType(str, Enum):
    SIGNATURE_CARD = "SIGNATURE_CARD"
    DEATH_CERTIFICATE = "DEATH_CERTIFICATE"
    LETTERS_TESTAMENTARY = "LETTERS_TESTAMENTARY"
    TRUST_AGREEMENT = "TRUST_AGREEMENT"
    POD_DESIGNATION = "POD_DESIGNATION"
    BUSINESS_RESOLUTION = "BUSINESS_RESOLUTION"
    COURT_ORDER = "COURT_ORDER"


class DocumentStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class TitleChangeStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class DeceasedCaseStatus(str, Enum):
    REPORTED = "REPORTED"
    VERIFIED = "VERIFIED"
    RELEASE_PENDING = "RELEASE_PENDING"
    RELEASED = "RELEASED"


class ReleaseVariant(str, Enum):
    DATE_OF_DEATH = "DATE_OF_DEATH"
    DATE_OF_RELEASE = "DATE_OF_RELEASE"


class GarnishmentOrderType(str, Enum):
    GARNISHMENT = "GARNISHMENT"
    TAX_LEVY = "TAX_LEVY"
    CHILD_SUPPORT = "CHILD_SUPPORT"


class ExemptionMethod(str, Enum):
    FEDERAL_LOOKBACK = "FEDERAL_LOOKBACK"
    STATE_MINIMUM = "STATE_MINIMUM"


class GarnishmentStatus(str, Enum):
    FUNDS_HELD = "FUNDS_HELD"
    REMITTED = "REMITTED"
    RELEASED = "RELEASED"


class StatementCycleStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PRODUCED = "PRODUCED"
    SUPPRESSED = "SUPPRESSED"


class SuppressionReason(str, Enum):
    DORMANT = "DORMANT"
    DECEASED = "DECEASED"
    CLOSED = "CLOSED"


class ConversionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# ---------------------------------------------------------------------------

class DepositAccount(TypedDict, total=False):
    id: str
    account_number: str
    primary_owner_name: str
    owner_tax_id: str
    ownership_type: str
    pod_beneficiary_name: Optional[str]
    product_code: str
    rate_bps: int
    lifecycle_status: str
    restriction_status: str
    balance_cents: int
    total_held_cents: int
    available_balance_cents: int
    accrual_start_date: str
    accrued_interest_cents: int
    last_customer_activity_date: str
    dormant_since_date: Optional[str]
    fees_assessed_count: int
    statement_suppression: str
    closure_payout_cents: Optional[int]
    closure_payout_destination: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AccountTransaction(TypedDict, total=False):
    # Append-only event log: carries ONLY id + created_at from the common set.
    id: str
    created_at: str
    account_id: str
    txn_type: str
    amount_cents: int
    customer_initiated: bool
    posted_date: str
    balance_after_cents: int


class AuthorizedSigner(TypedDict, total=False):
    id: str
    account_id: str
    full_name: str
    tax_id: str
    signer_role: str
    signature_card_reference: str
    status: str
    removed_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AccountDocument(TypedDict, total=False):
    id: str
    account_id: str
    doc_type: str
    reference_number: str
    status: str
    reviewed_by_user_id: Optional[str]
    review_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TitleChangeRequest(TypedDict, total=False):
    id: str
    account_id: str
    current_ownership_type: str
    requested_ownership_type: str
    pod_beneficiary_name: Optional[str]
    required_doc_types: List[str]
    status: str
    created_by_user_id: str
    decided_by_user_id: Optional[str]
    decision_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DeceasedCase(TypedDict, total=False):
    id: str
    account_id: str
    decedent_name: str
    date_of_death: str
    reported_by: str
    status: str
    balance_at_death_cents: Optional[int]
    accrued_interest_at_death_cents: Optional[int]
    release_variant: Optional[str]
    release_amount_cents: Optional[int]
    estate_representative_name: Optional[str]
    initiated_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class GarnishmentOrder(TypedDict, total=False):
    id: str
    account_id: str
    order_type: str
    creditor_name: str
    amount_cents: int
    served_date: str
    answer_deadline_date: str
    exemption_method: str
    held_amount_cents: int
    exempt_amount_cents: int
    collectible_cents: int
    remitted_amount_cents: int
    released_amount_cents: int
    received_by_user_id: str
    resolved_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class StatementCycle(TypedDict, total=False):
    id: str
    account_id: str
    cycle_start: str
    cycle_end: str
    status: str
    suppression_reason: Optional[str]
    produced_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProductConversion(TypedDict, total=False):
    id: str
    account_id: str
    from_product_code: str
    to_product_code: str
    new_rate_bps: int
    effective_date: str
    accrued_interest_settled_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int
