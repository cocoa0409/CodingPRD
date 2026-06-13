"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the Consignment Thrift Resale PRD. Mutable resources carry the
common quartet (id, created_at, updated_at, version); the three append-only
ledger records (SaleLine, PayoutLedgerEntry, StoreCreditTransaction) carry only
id and created_at.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Status enums ────────────────────────────────────────────────────────────

class ConsignorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class AgreementStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class SplitBasis(str, Enum):
    GROSS = "GROSS"
    NET = "NET"


class UnsoldDisposition(str, Enum):
    RETURN_TO_CONSIGNOR = "RETURN_TO_CONSIGNOR"
    DONATE = "DONATE"
    STORE_KEEPS = "STORE_KEEPS"


class PayoutMethod(str, Enum):
    CASH = "CASH"
    STORE_CREDIT = "STORE_CREDIT"


class BatchStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class GradingStatus(str, Enum):
    PENDING_GRADE = "PENDING_GRADE"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class ListingStatus(str, Enum):
    NOT_LISTED = "NOT_LISTED"
    ON_FLOOR = "ON_FLOOR"
    SOLD = "SOLD"
    RETURNED = "RETURNED"
    DONATED = "DONATED"
    PULLED = "PULLED"


class AuthenticationStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING_AUTH = "PENDING_AUTH"
    AUTHENTIC = "AUTHENTIC"
    COUNTERFEIT = "COUNTERFEIT"


class ReviewStatus(str, Enum):
    IN_REVIEW = "IN_REVIEW"
    DISPUTED = "DISPUTED"
    AUTHENTIC = "AUTHENTIC"
    COUNTERFEIT = "COUNTERFEIT"


class SaleStatus(str, Enum):
    COMPLETED = "COMPLETED"
    VOIDED = "VOIDED"


class PaymentMethod(str, Enum):
    CASH = "CASH"
    CARD = "CARD"
    STORE_CREDIT = "STORE_CREDIT"


class SettlementStatus(str, Enum):
    OPEN = "OPEN"
    FINALIZED = "FINALIZED"
    VOIDED = "VOIDED"


class LedgerEntryType(str, Enum):
    SALE_PAYOUT = "SALE_PAYOUT"
    REVERSAL = "REVERSAL"


class StoreCreditTxnType(str, Enum):
    ISSUE = "ISSUE"
    REDEEM = "REDEEM"


class StoreCreditTxnStatus(str, Enum):
    POSTED = "POSTED"
    VOID = "VOID"


class DonationDisposition(str, Enum):
    RETURNED = "RETURNED"
    DONATED = "DONATED"
    STORE_KEPT = "STORE_KEPT"


class UserRole(str, Enum):
    STORE_ADMIN = "StoreAdmin"
    INTAKE_GRADER = "IntakeGrader"
    AUTHENTICATOR = "Authenticator"
    CASHIER_CLERK = "CashierClerk"
    SETTLEMENT_MANAGER = "SettlementManager"


# ─── Entity TypedDicts (common_fields: true — id/created_at/updated_at/version) ─

class Consignor(TypedDict):
    id: str
    full_name: str
    email: str
    status: str
    store_credit_cents: int
    unsettled_payable_cents: int
    lifetime_payout_cents: int
    created_at: str
    updated_at: str
    version: int


class MarkdownSchedule(TypedDict):
    id: str
    name: str
    base_floor_pct: float
    tiers: list
    is_archived: bool
    created_at: str
    updated_at: str
    version: int


class ConsignorAgreement(TypedDict):
    id: str
    consignor_id: str
    markdown_schedule_id: str
    split_pct: float
    split_basis: str
    unsold_disposition: str
    return_window_days: int
    payout_method: str
    status: str
    created_at: str
    updated_at: str
    version: int


class IntakeBatch(TypedDict):
    id: str
    agreement_id: str
    received_at: str
    status: str
    item_count: int
    created_at: str
    updated_at: str
    version: int


class Item(TypedDict):
    id: str
    batch_id: str
    agreement_id: str
    consignor_id: str
    title: str
    requires_authentication: bool
    list_price_cents: Optional[int]
    graded_by_user_id: Optional[str]
    grading_status: str
    listing_status: str
    authentication_status: str
    floor_date: Optional[str]
    current_price_cents: Optional[int]
    sold_price_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class AuthenticationReview(TypedDict):
    id: str
    item_id: str
    opened_by_user_id: str
    status: str
    dispute_round: int
    verdict_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Sale(TypedDict):
    id: str
    sold_at: str
    business_date: str
    rung_by_user_id: str
    payment_method: str
    gross_total_cents: int
    status: str
    settlement_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DailySettlement(TypedDict):
    id: str
    business_date: str
    status: str
    total_gross_cents: int
    total_consignor_payable_cents: int
    total_store_credit_issued_cents: int
    total_store_share_cents: int
    swept_sale_count: int
    created_at: str
    updated_at: str
    version: int


class DonationRecord(TypedDict):
    id: str
    item_id: str
    consignor_id: str
    disposition: str
    tax_receipt_value_cents: int
    created_at: str
    updated_at: str
    version: int


# ─── Append-only ledger records (common_fields: false — id/created_at only) ───

class SaleLine(TypedDict):
    id: str
    sale_id: str
    item_id: str
    consignor_id: str
    sold_price_cents: int
    processing_fee_cents: int
    split_base_cents: int
    consignor_proceeds_cents: int
    store_share_cents: int
    created_at: str


class PayoutLedgerEntry(TypedDict):
    id: str
    consignor_id: str
    sale_line_ref: Optional[str]
    entry_type: str
    amount_cents: int
    settlement_id: Optional[str]
    created_at: str


class StoreCreditTransaction(TypedDict):
    id: str
    consignor_id: str
    txn_type: str
    amount_cents: int
    status: str
    created_at: str
