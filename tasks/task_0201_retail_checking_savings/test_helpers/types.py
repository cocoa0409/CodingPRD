"""Domain types: entity TypedDicts, status enums, role enum (PRD §3)."""
from enum import Enum
from typing import TypedDict, Optional


# ─── Role enum (PRD §2.1) ──────────────────────────────────────────────
class UserRole(str, Enum):
    ACCOUNT_HOLDER = "AccountHolder"
    TELLER = "Teller"
    COMPLIANCE_OFFICER = "ComplianceOfficer"


# ─── Status enums (PRD §3) ─────────────────────────────────────────────
class CipStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DORMANT = "DORMANT"
    FROZEN = "FROZEN"
    ESCHEATED = "ESCHEATED"
    CLOSED = "CLOSED"


class ProductType(str, Enum):
    CHECKING = "CHECKING"
    SAVINGS = "SAVINGS"


class OwnershipRole(str, Enum):
    PRIMARY = "PRIMARY"
    JOINT = "JOINT"
    POD_BENEFICIARY = "POD_BENEFICIARY"


class TxnType(str, Enum):
    DEPOSIT = "DEPOSIT"
    WITHDRAWAL = "WITHDRAWAL"
    ACH_CREDIT = "ACH_CREDIT"
    ACH_DEBIT = "ACH_DEBIT"
    CHECK_DEBIT = "CHECK_DEBIT"
    INTEREST = "INTEREST"
    FEE = "FEE"
    ESCHEAT_SWEEP = "ESCHEAT_SWEEP"


class TxnDirection(str, Enum):
    CREDIT = "CREDIT"
    DEBIT = "DEBIT"


class TxnStatus(str, Enum):
    PENDING = "PENDING"
    POSTED = "POSTED"
    RETURNED = "RETURNED"
    STOPPED = "STOPPED"


class ReturnReasonCode(str, Enum):
    NSF = "NSF"
    STOP_PAYMENT = "STOP_PAYMENT"
    ACCOUNT_FROZEN = "ACCOUNT_FROZEN"


class FeeType(str, Enum):
    OVERDRAFT = "OVERDRAFT"
    NSF = "NSF"


class StopPaymentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CONSUMED = "CONSUMED"
    EXPIRED = "EXPIRED"


class AchOriginationStatus(str, Enum):
    STAGED = "STAGED"
    SETTLED = "SETTLED"
    REVERSED = "REVERSED"


class AchLegRole(str, Enum):
    DEBIT = "DEBIT"
    CREDIT = "CREDIT"


class AchSettlementOutcome(str, Enum):
    POSTED = "POSTED"
    RETURNED_NSF = "RETURNED_NSF"


class PostingOrder(str, Enum):
    CHRONOLOGICAL = "CHRONOLOGICAL"
    HIGH_TO_LOW = "HIGH_TO_LOW"


class RejectionReasonCode(str, Enum):
    CIP_MISMATCH = "CIP_MISMATCH"
    SANCTIONS_HIT = "SANCTIONS_HIT"
    UNDERAGE = "UNDERAGE"
    DUPLICATE = "DUPLICATE"


# ─── Entity TypedDicts ─────────────────────────────────────────────────
# Entities carrying the full common-field envelope (PRD §2.4):
# id, created_at, updated_at, version.

class Customer(TypedDict):
    id: str
    legal_name: str
    date_of_birth: str
    tax_id_last4: str
    country_of_residence: str
    cip_status: str
    created_at: str
    updated_at: str
    version: int


class Application(TypedDict):
    id: str
    customer_id: str
    product_type: str
    requested_apy_tier_code: str
    submitted_by_user_id: Optional[str]
    status: str
    kyc_risk_score: Optional[int]
    opened_account_id: Optional[str]
    rejection_reason_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Account(TypedDict):
    id: str
    product_type: str
    origin_application_id: str
    apy_tier_code: str
    status: str
    courtesy_pay_opted_in: bool
    courtesy_pay_limit_cents: int
    ledger_balance_cents: int
    hold_total_cents: int
    available_balance_cents: int
    accrued_interest_cents: int
    od_nsf_items_today: int
    last_activity_date: Optional[str]
    dormancy_threshold_days: int
    escheat_threshold_days: int
    created_at: str
    updated_at: str
    version: int


class AccountOwner(TypedDict):
    id: str
    account_id: str
    customer_id: str
    ownership_role: str
    is_active: bool
    created_at: str
    updated_at: str
    version: int


class Transaction(TypedDict):
    id: str
    account_id: str
    ach_origination_id: Optional[str]
    txn_type: str
    direction: str
    amount_cents: int
    status: str
    posted_balance_cents: Optional[int]
    check_number: Optional[str]
    return_reason_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FeeAssessment(TypedDict):
    id: str
    account_id: str
    source_transaction_id: str
    fee_type: str
    tier_ordinal: int
    fee_amount_cents: int
    assessed_date: str
    created_at: str
    updated_at: str
    version: int


class StopPayment(TypedDict):
    id: str
    account_id: str
    check_number: str
    max_amount_cents: int
    status: str
    expires_on: str
    created_at: str
    updated_at: str
    version: int


class AchOrigination(TypedDict):
    id: str
    debtor_account_id: str
    creditor_account_id: str
    posting_order: str
    status: str
    total_debit_cents: int
    total_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class AchLeg(TypedDict):
    id: str
    ach_origination_id: str
    leg_role: str
    amount_cents: int
    produced_transaction_id: Optional[str]
    settlement_outcome: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InterestPosting(TypedDict):
    id: str
    account_id: str
    period_start_date: str
    period_end_date: str
    posted_interest_cents: int
    applied_apy_tier_code: str
    created_at: str
    updated_at: str
    version: int


class EscheatEvent(TypedDict):
    id: str
    account_id: str
    swept_amount_cents: int
    jurisdiction: str
    dormancy_days_at_escheat: int
    created_at: str
    updated_at: str
    version: int


# ─── ApyTier: reference configuration, common_fields false (PRD §2.4) ──
# Carries ONLY id and created_at — no updated_at, no version.
class ApyTier(TypedDict):
    id: str
    code: str
    product_type: str
    min_balance_cents: int
    annual_rate_bps: int
    created_at: str
