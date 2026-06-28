"""Domain types: entity TypedDicts, status enums, role enum (PRD §3)."""
from enum import Enum
from typing import TypedDict, Optional


# --- Roles (PRD §2.1) ---
class UserRole(str, Enum):
    TELLER = "Teller"
    STORE_MANAGER = "StoreManager"


# --- Enums (PRD §3) ---
class KycStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    OFAC_BLOCKED = "OFAC_BLOCKED"
    REJECTED = "REJECTED"


class RiskTier(str, Enum):
    STANDARD = "STANDARD"
    ELEVATED = "ELEVATED"
    HIGH = "HIGH"


class IdType(str, Enum):
    DRIVERS_LICENSE = "DRIVERS_LICENSE"
    STATE_ID = "STATE_ID"
    PASSPORT = "PASSPORT"
    MILITARY_ID = "MILITARY_ID"


class ScreenOutcome(str, Enum):
    VERIFIED = "VERIFIED"
    OFAC_BLOCKED = "OFAC_BLOCKED"
    REJECTED = "REJECTED"


class CheckType(str, Enum):
    PAYROLL = "PAYROLL"
    GOVERNMENT = "GOVERNMENT"
    PERSONAL = "PERSONAL"
    MONEY_ORDER_CHECK = "MONEY_ORDER_CHECK"
    INSURANCE = "INSURANCE"


class DrawerStatus(str, Enum):
    OPEN = "OPEN"
    RECONCILING = "RECONCILING"
    CLOSED = "CLOSED"
    OVER_SHORT = "OVER_SHORT"


class TxnType(str, Enum):
    CHECK_CASH = "CHECK_CASH"
    MONEY_ORDER = "MONEY_ORDER"
    WIRE = "WIRE"
    BILL_PAY = "BILL_PAY"
    PREPAID_LOAD = "PREPAID_LOAD"


class LifecycleState(str, Enum):
    DRAFT = "DRAFT"
    POSTED = "POSTED"
    VOIDED = "VOIDED"


class SettlementState(str, Enum):
    UNSETTLED = "UNSETTLED"
    SETTLED = "SETTLED"
    RETURNED = "RETURNED"
    RECOVERED = "RECOVERED"


class VerificationState(str, Enum):
    VERIFYING = "VERIFYING"
    CLEARED = "CLEARED"
    RISK_HELD = "RISK_HELD"
    REJECTED = "REJECTED"


class HoldReason(str, Enum):
    AMOUNT_THRESHOLD = "AMOUNT_THRESHOLD"
    MAKER_RISK = "MAKER_RISK"
    VELOCITY = "VELOCITY"


class MakerAccountRisk(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class MoneyOrderStatus(str, Enum):
    ISSUED = "ISSUED"
    VOIDED = "VOIDED"


class WireStatus(str, Enum):
    SENT = "SENT"
    RECALLED = "RECALLED"


class BillPaymentStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VOIDED = "VOIDED"


class PrepaidLoadStatus(str, Enum):
    LOADED = "LOADED"
    REVERSED = "REVERSED"


class ReturnReason(str, Enum):
    NSF = "NSF"
    ACCOUNT_CLOSED = "ACCOUNT_CLOSED"
    STOP_PAYMENT = "STOP_PAYMENT"
    FRAUD = "FRAUD"


class ReturnedItemStatus(str, Enum):
    OUTSTANDING = "OUTSTANDING"
    PARTIALLY_RECOVERED = "PARTIALLY_RECOVERED"
    RECOVERED = "RECOVERED"
    WRITTEN_OFF = "WRITTEN_OFF"


# --- Entity TypedDicts (PRD §2.4, §3) ---
# Common-fields entities carry id + created_at + updated_at + version.

class Customer(TypedDict):
    id: str
    full_name: str
    id_type: str
    id_number: str
    date_of_birth: str
    kyc_status: str
    risk_tier: str
    risk_score: int
    daily_cashed_amount_cents: int
    daily_transaction_count: int
    limit_window_opened_at: Optional[str]
    outstanding_recovery_cents: int
    created_at: str
    updated_at: str
    version: int


# ComplianceScreen: immutable audit record — id + created_at ONLY (PRD §2.4).
class ComplianceScreen(TypedDict):
    id: str
    customer_id: str
    ofac_list_hit: bool
    kyc_documents_valid: bool
    outcome: str
    created_at: str


class FeeSchedule(TypedDict):
    id: str
    check_type: str
    base_fee_cents: int
    percent_rate_bps: int
    tier_breakpoint_cents: int
    high_percent_rate_bps: int
    max_fee_cents: int
    active: bool
    created_at: str
    updated_at: str
    version: int


class CashDrawer(TypedDict):
    id: str
    store_code: str
    business_date: str
    opening_float_cents: int
    status: str
    expected_cash_cents: int
    counted_cash_cents: Optional[int]
    variance_cents: int
    created_at: str
    updated_at: str
    version: int


class Transaction(TypedDict):
    id: str
    customer_id: str
    drawer_id: str
    txn_type: str
    face_amount_cents: int
    fee_schedule_id: Optional[str]
    fee_cents: int
    net_disbursed_cents: int
    lifecycle_state: str
    settlement_state: str
    created_at: str
    updated_at: str
    version: int


class CheckItem(TypedDict):
    id: str
    transaction_id: str
    check_face_cents: int
    maker_account_risk: str
    verification_state: str
    hold_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MoneyOrder(TypedDict):
    id: str
    transaction_id: str
    serial_number: str
    payee_name: str
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class WireTransfer(TypedDict):
    id: str
    transaction_id: str
    destination_country: str
    beneficiary_name: str
    status: str
    created_at: str
    updated_at: str
    version: int


class BillPayment(TypedDict):
    id: str
    transaction_id: str
    biller_code: str
    account_reference: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PrepaidCardLoad(TypedDict):
    id: str
    transaction_id: str
    card_last_four: str
    loaded_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ReturnedItem(TypedDict):
    id: str
    transaction_id: str
    customer_id: str
    return_reason: str
    return_fee_cents: int
    recovered_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
